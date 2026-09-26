"""A thin, testable wrapper around the `git` command line. Git stays the source of truth; nothing here reimplements it.

Every call is an argument list run through the process layer (no shell). `run` is injectable, and most tests use a real
temporary repository instead of mocks, because Git's own behaviour is what has to be right.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from ..core import process
from ..errors import ChError

Run = Callable[..., process.ProcessResult]

CONVENTIONAL = re.compile(r"^(?P<type>feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
                          r"(?:\((?P<scope>[\w./,-]+)\))?(?P<breaking>!)?: (?P<subject>\S.*)$")
TYPES = ("feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert")


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    body: str = ""
    tree: str = ""

    @property
    def short(self) -> str:
        return self.sha[:7]


@dataclass(frozen=True)
class Status:
    branch: str
    upstream: str
    ahead: int
    behind: int
    staged: Tuple[str, ...]
    modified: Tuple[str, ...]
    untracked: Tuple[str, ...]
    conflicted: Tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not (self.staged or self.modified or self.untracked or self.conflicted)


class Git:
    def __init__(self, root: Path, run: Run = process.run, which: Callable[[str], Optional[str]] = shutil.which) -> None:
        self.root = root
        self._run = run
        self._which = which

    # ------------------------------------------------------------------ plumbing
    @property
    def exe(self) -> str:
        exe = self._which("git")
        if not exe:
            raise ChError("CH8007", what="git", hint="install Git (https://git-scm.com) and put it on PATH")
        return exe

    def call(self, args: Sequence[str], *, check: bool = True, timeout: float = 300, input: Optional[str] = None
             ) -> process.ProcessResult:
        result = self._run([self.exe, "-C", str(self.root), *args], timeout=timeout, input=input)
        if check and result.returncode != 0:
            raise ChError("CH8013", command="git " + " ".join(args[:3]), detail=result.output.strip()[-800:] or "(no output)")
        return result

    def lines(self, args: Sequence[str], check: bool = True) -> List[str]:
        result = self.call(args, check=check)
        return [line for line in result.stdout.splitlines() if line.strip()] if result.returncode == 0 else []

    # ------------------------------------------------------------------ queries
    def is_repo(self) -> bool:
        return self.call(["rev-parse", "--is-inside-work-tree"], check=False).stdout.strip() == "true"

    def require_repo(self) -> None:
        if not self.is_repo():
            raise ChError("CH8013", command="git", detail=f"{self.root} is not inside a Git repository (run `git init`)")

    def top_level(self) -> Path:
        return Path(self.call(["rev-parse", "--show-toplevel"]).stdout.strip())

    def hooks_dir(self) -> Path:
        path = Path(self.call(["rev-parse", "--git-path", "hooks"]).stdout.strip())
        return path if path.is_absolute() else self.root / path

    def branch(self) -> str:
        name = self.call(["rev-parse", "--abbrev-ref", "HEAD"], check=False).stdout.strip()
        return "" if name == "HEAD" else name

    def head(self) -> Optional[str]:
        result = self.call(["rev-parse", "--verify", "HEAD"], check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def tree_of(self, revision: str = "HEAD") -> Optional[str]:
        result = self.call(["rev-parse", f"{revision}^{{tree}}"], check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def status(self) -> Status:
        out = self.call(["status", "--porcelain=v2", "--branch"]).stdout
        branch = upstream = ""
        ahead = behind = 0
        staged: List[str] = []
        modified: List[str] = []
        untracked: List[str] = []
        conflicted: List[str] = []
        for line in out.splitlines():
            if line.startswith("# branch.head "):
                branch = line.split(" ", 2)[2]
            elif line.startswith("# branch.upstream "):
                upstream = line.split(" ", 2)[2]
            elif line.startswith("# branch.ab "):
                _, _, plus, minus = line.split()
                ahead, behind = int(plus), abs(int(minus))
            elif line.startswith(("1 ", "2 ")):
                fields = line.split(" ", 8 if line.startswith("1 ") else 9)
                xy, path = fields[1], fields[-1].split("\t")[0]
                if xy[0] != ".":
                    staged.append(path)
                if xy[1] != ".":
                    modified.append(path)
            elif line.startswith("u "):
                conflicted.append(line.split(" ", 10)[-1])
            elif line.startswith("? "):
                untracked.append(line[2:])
        return Status(branch if branch != "(detached)" else "", upstream, ahead, behind, tuple(staged), tuple(modified),
                      tuple(untracked), tuple(conflicted))

    def staged_diff(self, stat: bool = False) -> str:
        return self.call(["diff", "--cached", *(["--stat"] if stat else []), "--no-color"]).stdout

    def staged_files(self) -> List[str]:
        return self.lines(["diff", "--cached", "--name-only"])

    def log(self, revision_range: str, limit: int = 200) -> List[Commit]:
        sep, end = "\x1f", "\x1e"
        out = self.call(["log", revision_range, f"--max-count={limit}", f"--format=%H{sep}%s{sep}%b{sep}%T{end}"],
                        check=False).stdout
        commits = []
        for record in out.split(end):
            parts = record.strip("\n").split(sep)
            if len(parts) == 4 and parts[0].strip():
                commits.append(Commit(parts[0].strip(), parts[1], parts[2].strip(), parts[3]))
        return commits

    def remote_url(self, remote: str = "origin") -> Optional[str]:
        result = self.call(["remote", "get-url", remote], check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def default_base(self, remote: str = "origin") -> str:
        """`main`/`master` (what the remote calls its default), else `main`."""
        result = self.call(["symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD"], check=False)
        if result.returncode == 0 and "/" in result.stdout:
            return result.stdout.strip().split("/", 1)[1]
        for name in ("main", "master"):
            if self.call(["rev-parse", "--verify", "--quiet", f"refs/heads/{name}"], check=False).returncode == 0:
                return name
        return "main"

    def latest_tag(self) -> Optional[str]:
        result = self.call(["describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"], check=False)
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None

    # ------------------------------------------------------------------ actions
    def add_all_tracked(self) -> None:
        self.call(["add", "--update"])

    def commit(self, message: str, *, no_verify: bool = False, edit: bool = False) -> str:
        args = ["commit", "-m", message]
        if no_verify:
            args.append("--no-verify")
        if edit:
            args.append("--edit")
        self.call(args)
        head = self.head()
        assert head is not None
        return head

    def push(self, remote: str, branch: str, *, set_upstream: bool = False, force_with_lease: bool = False,
             tags: bool = False) -> process.ProcessResult:
        args = ["push", *(["--set-upstream"] if set_upstream else []), *(["--force-with-lease"] if force_with_lease else []),
                *(["--tags"] if tags else []), remote, branch]
        return self.call(args, timeout=900)

    def tag(self, name: str, message: str) -> None:
        self.call(["tag", "-a", name, "-m", message])


def parse_remote(url: str) -> Optional[Tuple[str, str]]:
    """(owner, repo) of a GitHub remote URL (https or ssh), else None."""
    match = re.match(r"^(?:https?://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$",
                     url.strip())
    return (match.group(1), match.group(2)) if match else None


def check_message(message: str) -> Optional[str]:
    """None when `message`'s first line is a valid Conventional Commit, else why not."""
    first = message.strip().splitlines()[0] if message.strip() else ""
    if not first:
        return "the commit message is empty"
    if CONVENTIONAL.match(first):
        return None
    return (f"{first!r} is not a Conventional Commit: expected `type(scope): subject` with type one of "
            f"{', '.join(TYPES)} (e.g. `fix(engine): reset the stat cache after a clean`)")


def propose_message(files: Sequence[str], diff_stat: str = "") -> str:
    """A first draft from what changed -- a starting point that `charpente commit` always shows for editing."""
    paths = [f.replace("\\", "/") for f in files]
    if not paths:
        return "chore: update"
    def under(*prefixes: str) -> bool:
        return all(p.startswith(prefixes) for p in paths)

    if all(p.endswith((".md", ".rst")) or p.startswith("docs/") for p in paths):
        kind = "docs"
    elif under("tests/", "test/") or all(re.search(r"(^|/)(test_|.*_test\.)", p) for p in paths):
        kind = "test"
    elif under(".github/", ".gitlab-ci"):
        kind = "ci"
    elif all(p.endswith((".toml", ".json", ".lock", ".yml", ".yaml", ".cmake")) or p.endswith(("Makefile", ".charpente")) for p in paths):
        kind = "build"
    else:
        kind = "feat"
    tops = sorted({p.split("/")[0] if "/" in p else Path(p).stem for p in paths})
    scope = tops[0] if len(tops) == 1 else ""
    subject = f"update {paths[0]}" if len(paths) == 1 else f"update {len(paths)} files"
    return f"{kind}{f'({scope})' if scope else ''}: {subject}"
