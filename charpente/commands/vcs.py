"""`charpente status | commit | push | pr | hooks` -- Git and GitHub, with the quality gate in front.

Git stays the source of truth: these commands run `git` (and `gh` when installed) and add the gate, the commit
message discipline and the reporting. Nothing here rewrites history or force-pushes without an explicit, typed
confirmation, and no token is ever written to a file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from ..core import history
from ..errors import ChError
from ..events import EventBus
from ..output import PlainRenderer
from ..quality import gate
from ..quality.model import GateResult
from ..vcs import git as git_mod
from ..vcs import hooks as hooks_mod
from ..vcs import pr as pr_mod
from ._common import find_root


def _bus(quiet: bool = False) -> EventBus:
    bus = EventBus()
    if not quiet:
        PlainRenderer(bus, verbose=False)
    return bus


def _git(root: Optional[Path] = None) -> git_mod.Git:
    g = git_mod.Git(root or find_root())
    g.require_repo()
    return g


def _why_blocked(result: GateResult) -> str:
    names = ", ".join(r.name for r in result.failed)
    return f"the quality gate failed: {names}" if names else "the quality gate skipped checks and fail_on_skipped is set"


def _run_gate(g: git_mod.Git, level: str, changed: bool, bus: EventBus) -> GateResult:
    result = gate.run_gate(g.root, level=level, changed=changed, bus=bus, say=print)
    gate.write_record(g.root, result, tree=gate.index_tree(g.root) if changed else None)
    print(gate.render(result))
    return result


# ------------------------------------------------------------------ status
def execute_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente status", description="Git state, last build and last quality-gate result.")
    parser.add_argument("--json", action="store_true")
    parsed = parser.parse_args(args)
    g = _git()
    status = g.status()
    record = gate.read_record(g.root)
    sessions = history.list_sessions(g.root / "build" / ".charpente" / "history.db", limit=1)
    last_build = sessions[0] if sessions else None
    if parsed.json:
        print(json.dumps({"branch": status.branch, "upstream": status.upstream, "ahead": status.ahead, "behind": status.behind,
                          "staged": list(status.staged), "modified": list(status.modified),
                          "untracked": list(status.untracked), "gate": record,
                          "last_build": None if last_build is None else {"command": last_build.command, "ok": last_build.ok,
                                                                          "duration": last_build.duration}}, indent=1))
        return 0
    where = status.branch or "(detached HEAD)"
    sync = f"  [{status.upstream}: ahead {status.ahead}, behind {status.behind}]" if status.upstream else "  [no upstream]"
    print(f"Git:    {where}{sync}")
    print(f"        {len(status.staged)} staged, {len(status.modified)} modified, {len(status.untracked)} untracked"
          + (f", {len(status.conflicted)} CONFLICTED" if status.conflicted else ""))
    if last_build is None:
        print("Build:  no build recorded yet")
    else:
        print(f"Build:  last `{last_build.command}` {'succeeded' if last_build.ok else 'FAILED'} in {last_build.duration:.1f}s "
              f"({last_build.executed} run, {last_build.cached} cached)")
    if record is None:
        print("Gate:   `charpente check` has not been run here")
    else:
        failed = [r["check"] for r in record["results"] if r["status"] == "failed"]
        print(f"Gate:   {record['level']} -- {'passed' if record['ok'] else 'BLOCKED (' + ', '.join(failed) + ')'} at {record.get('when', '?')}")
    return 0


# ------------------------------------------------------------------ commit
def _propose(g: git_mod.Git, use_ai: bool) -> Tuple[str, str]:
    """(message, where it came from)."""
    files = g.staged_files()
    draft = git_mod.propose_message(files, g.staged_diff(stat=True))
    if use_ai:
        from ..ai.provider import select_provider

        provider = select_provider()
        if provider.is_available():
            diff = g.staged_diff()[:12000]
            try:
                text = provider.complete(
                    "Write a Conventional Commit message (type(scope): subject, max 72 chars, then an optional body) for this "
                    "diff. Answer with the message only.\n\n" + diff,
                    system="You write precise Git commit messages.").strip().strip("`")
                if text and git_mod.check_message(text) is None:
                    return text, f"drafted by {provider.name} from the diff (sent to that provider)"
            except Exception as exc:                    # the draft is a convenience; never block a commit on it
                print(f"charpente: the AI draft failed ({exc}); using a plain draft", file=sys.stderr)
        else:
            print("charpente: no AI provider is configured; using a plain draft", file=sys.stderr)
    return draft, "drafted from the changed paths"


def execute_commit(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente commit", description="Run the quality gate on what changed, then commit.")
    parser.add_argument("-m", "--message", help="The commit message (Conventional Commits). Without it Charpente drafts one for you to edit")
    parser.add_argument("-a", "--all", action="store_true", help="Stage all modified tracked files first")
    parser.add_argument("--level", default="rapide", choices=["rapide", "standard", "strict"])
    parser.add_argument("--no-verify", action="store_true", help="Skip the gate (recorded in the build history and flagged in PRs)")
    parser.add_argument("--ai", action="store_true", help="Let the configured AI provider draft the message from the diff "
                                                          "(the diff is sent to it; you always review the result)")
    parser.add_argument("--any-format", action="store_true", help="Accept a message that is not a Conventional Commit")
    parsed = parser.parse_args(args)

    g = _git()
    if parsed.all:
        g.add_all_tracked()
    if not g.staged_files():
        print("Nothing staged. Stage files with `git add`, or use -a for modified tracked files.")
        return 1
    bus = _bus()
    if parsed.no_verify:
        print("charpente: --no-verify: the quality gate is skipped. This is recorded and will be flagged in pull requests.",
              file=sys.stderr)
    else:
        result = _run_gate(g, parsed.level, True, bus)
        if not result.ok:
            raise ChError("CH8014", reason=_why_blocked(result))
    message, source = parsed.message, "given with -m"
    edit = False
    if not message:
        message, source = _propose(g, parsed.ai)
        if not sys.stdin.isatty():
            raise ChError("CH8014", reason=f"no message given and this session is not interactive; the draft would be: {message!r} "
                                           "(pass it with -m to accept it)")
        print(f"Draft message ({source}); your editor opens so you can review and change it.")
        edit = True
    problem = None if parsed.any_format else git_mod.check_message(message)
    if problem and not edit:
        raise ChError("CH8014", reason=problem + " (use --any-format to override)")
    sha = g.commit(message, no_verify=parsed.no_verify, edit=edit)
    tree = g.tree_of("HEAD")
    if tree and not parsed.no_verify:
        gate.remember_tree(g.root, tree, parsed.level)                 # this exact tree passed the gate
    bus.emit("vcs.commit_created", sha=sha, message=message.splitlines()[0])
    print(f"Committed {sha[:7]}: {message.splitlines()[0]}")
    if parsed.no_verify:
        _note_no_verify(g.root, sha)
    return 0


def _note_no_verify(root: Path, sha: str) -> None:
    """Remember that the gate was skipped for this commit (the history `charpente status`/`pr` reads)."""
    path = root / "build" / ".charpente" / "no-verify.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        data.append(sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except (OSError, ValueError):
        pass


# ------------------------------------------------------------------ push
def execute_push(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente push", description="Run the standard quality gate, then push.")
    parser.add_argument("remote", nargs="?", default="origin")
    parser.add_argument("--level", default="standard", choices=["rapide", "standard", "strict"])
    parser.add_argument("--no-verify", action="store_true", help="Skip the gate (recorded, flagged in PRs)")
    parser.add_argument("--force-with-lease", action="store_true",
                        help="Overwrite the remote branch if nobody else changed it; asks you to type the branch name")
    parser.add_argument("--set-upstream", "-u", action="store_true")
    parsed = parser.parse_args(args)
    g = _git()
    status = g.status()
    if not status.branch:
        raise ChError("CH8014", reason="HEAD is detached: check out a branch before pushing")
    if status.conflicted:
        raise ChError("CH8014", reason="there are unresolved merge conflicts")
    bus = _bus()
    if not parsed.no_verify:
        result = gate.run_gate(g.root, level=parsed.level, bus=bus, say=print)
        gate.write_record(g.root, result)
        print(gate.render(result))
        if not result.ok:
            raise ChError("CH8014", reason=_why_blocked(result))
    else:
        print("charpente: --no-verify: the quality gate is skipped for this push.", file=sys.stderr)
    if parsed.force_with_lease:
        if not sys.stdin.isatty():
            raise ChError("CH8014", reason="a forced push needs interactive confirmation")
        typed = input(f"Type the branch name ({status.branch}) to overwrite {parsed.remote}/{status.branch}: ").strip()
        if typed != status.branch:
            raise ChError("CH8014", reason="confirmation did not match; nothing was pushed")
    g.push(parsed.remote, status.branch, set_upstream=parsed.set_upstream or not status.upstream,
           force_with_lease=parsed.force_with_lease)
    bus.emit("vcs.push_done", remote=parsed.remote, branch=status.branch)
    print(f"Pushed {status.branch} to {parsed.remote}.")
    return 0


# ------------------------------------------------------------------ pr
def _sbom_components(root: Path) -> Optional[Sequence[Tuple[str, str, str]]]:
    lock_path = root / "charpente.lock"
    if not lock_path.is_file():
        return None
    from ..commands.pkg import _recipes
    from ..pkg import lock as lock_mod
    from ..pkg.store import PackageStore
    from ._common import load

    lock = lock_mod.load(root)
    if lock is None:
        return None
    from ..workspace_finder import find_workspace_file

    recipes = _recipes(load(str(find_workspace_file(start_dir=root)), None, materialize_packages=False), PackageStore())
    return [(n, lock.packages[n].version, recipes[n].license if n in recipes else "unknown") for n in sorted(lock.packages)]


def execute_pr(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente pr", description="Open a pull request with the change summary, the gate result "
                                                                        "and warnings about unverified commits.")
    parser.add_argument("--base", help="Base branch (default: the remote's default branch)")
    parser.add_argument("--title")
    parser.add_argument("--summary", help="Text for the Summary section (default: from the commits)")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--sbom", action="store_true", help="List the locked dependencies and their licenses in the description")
    parser.add_argument("--push", action="store_true", help="Push the branch first (through the standard gate)")
    parser.add_argument("--dry-run", action="store_true", help="Print the title and description; open nothing")
    parser.add_argument("--remote", default="origin")
    parsed = parser.parse_args(args)
    g = _git()
    status = g.status()
    if not status.branch:
        raise ChError("CH8015", detail="HEAD is detached: check out the branch that holds your change")
    base = parsed.base or g.default_base(parsed.remote)
    if status.branch == base:
        raise ChError("CH8015", detail=f"you are on the base branch ({base}); create a branch for the change first")
    if parsed.push and not parsed.dry_run:
        code = execute_push([parsed.remote])
        if code:
            return code
        status = g.status()
    elif status.ahead and not parsed.dry_run:
        raise ChError("CH8015", detail=f"{status.ahead} local commit(s) are not pushed yet: use `charpente pr --push`")
    commits = list(reversed(g.log(f"{base}..HEAD"))) or list(reversed(g.log(f"{parsed.remote}/{base}..HEAD")))
    body = pr_mod.build_body(commits, gate.read_record(g.root), gate.read_log(g.root),
                             _sbom_components(g.root) if parsed.sbom else None, parsed.summary or "")
    title = parsed.title or pr_mod.title_for(commits, status.branch)
    if parsed.dry_run:
        print(f"Title: {title}\nBase:  {base}   Head: {status.branch}\n\n{body}")
        return 0
    url = pr_mod.open_with_gh(title, body, base, status.branch, draft=parsed.draft)
    if url is None:
        remote_url = g.remote_url(parsed.remote)
        if not remote_url:
            raise ChError("CH8015", detail=f"remote {parsed.remote!r} does not exist")
        url = pr_mod.open_with_api(remote_url, title, body, base, status.branch, draft=parsed.draft, auth=pr_mod.token())
    _bus(quiet=True).emit("vcs.pr_opened", url=url)
    print(f"Opened {url}")
    return 0


# ------------------------------------------------------------------ hooks
def execute_hooks(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente hooks", description="Install Git hooks that run the quality gate.")
    sub = parser.add_subparsers(dest="action", required=True)
    install = sub.add_parser("install", help="Install pre-commit (rapide) and pre-push (standard) hooks")
    install.add_argument("--force", action="store_true", help="Replace hooks Charpente did not write (they are kept as .pre-charpente)")
    sub.add_parser("uninstall", help="Remove Charpente's hooks (and restore any hook it replaced)")
    sub.add_parser("status", help="Show which hooks are installed")
    parsed = parser.parse_args(args)
    g = _git()
    directory = g.hooks_dir()
    if parsed.action == "install":
        for name, what in hooks_mod.install(directory, force=parsed.force):
            print(f"  {name}: {what}")
        print(f"Hooks are in {directory}. `git commit --no-verify` still skips them; Charpente flags such commits in PRs.")
    elif parsed.action == "uninstall":
        for name, what in hooks_mod.uninstall(directory):
            print(f"  {name}: {what}")
    else:
        for s in hooks_mod.state(directory):
            print(f"  {s.name:<11} " + ("installed (Charpente)" if s.installed else "another hook is in place" if s.foreign else "not installed")
                  + ("  [backup exists]" if s.backup else ""))
    return 0
