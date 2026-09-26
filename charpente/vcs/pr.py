"""Pull requests: the body Charpente writes, and how it is opened (`gh` if installed, else the GitHub API).

The body carries what a reviewer needs to trust the change: the commits, the last quality-gate result, and a warning for any
commit that has no passing gate record (it may have been made with `git commit --no-verify`). Tokens are never written to a
file: they come from `GH_TOKEN`/`GITHUB_TOKEN` or the system keyring (if the optional `keyring` package is installed).
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..core import process
from ..errors import ChError
from .git import Commit, parse_remote

KEYRING_SERVICE = "charpente-github"


def token(env: Optional[Mapping[str, str]] = None, keyring_module: Any = None) -> Optional[str]:
    """`GH_TOKEN`, `GITHUB_TOKEN`, or the keyring's entry; None when there is none."""
    env = os.environ if env is None else env
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if env.get(name):
            return env[name]
    if keyring_module is None:
        try:
            import keyring as keyring_module  # optional dependency
        except ImportError:
            return None
    try:
        value = keyring_module.get_password(KEYRING_SERVICE, "token")
        return str(value) if value else None
    except Exception:                                   # a broken keyring backend is "no token", not a crash
        return None


def unverified(commits: Sequence[Commit], gate_log: Mapping[str, Any]) -> List[Commit]:
    """Commits whose tree has no passing gate record -- possibly made with --no-verify, or outside Charpente."""
    return [c for c in commits if c.tree not in gate_log]


def build_body(commits: Sequence[Commit], record: Optional[Mapping[str, Any]], gate_log: Mapping[str, Any],
               sbom_components: Optional[Sequence[Tuple[str, str, str]]] = None, summary: str = "") -> str:
    lines: List[str] = ["## Summary", "", summary.strip() or _summary(commits), "", "## Commits", ""]
    lines += [f"- `{c.short}` {c.subject}" for c in commits] or ["- (none)"]
    lines += ["", "## Quality gate", ""]
    if record:
        verdict = "passed" if record.get("ok") else "**blocked**"
        lines.append(f"Last run: level `{record.get('level')}`, {verdict} ({record.get('when', 'unknown time')}).")
        for r in record.get("results", []):
            lines.append(f"- {r['status']}: {r['check']}" + (f" -- {r['message']}" if r.get("message") else ""))
    else:
        lines.append("No gate run recorded on the author's machine (`charpente check` was not run).")
    missing = unverified(commits, gate_log)
    if missing:
        lines += ["", f"> **Warning:** {len(missing)} commit(s) have no passing quality-gate record; they may have been "
                      "committed with `--no-verify` or outside Charpente:",
                  *[f"> - `{c.short}` {c.subject}" for c in missing]]
    if sbom_components is not None:
        lines += ["", "<details><summary>SBOM: dependencies</summary>", ""]
        lines += [f"- {name} {version} ({license})" for name, version, license in sbom_components] or ["- none"]
        lines += ["", "</details>"]
    lines += ["", "---", "Opened with `charpente pr`."]
    return "\n".join(lines) + "\n"


def _summary(commits: Sequence[Commit]) -> str:
    if not commits:
        return "No commits ahead of the base branch."
    if len(commits) == 1:
        return commits[0].body or commits[0].subject
    return f"{len(commits)} commits: " + "; ".join(c.subject for c in list(commits)[:5]) + ("; ..." if len(commits) > 5 else "")


def title_for(commits: Sequence[Commit], branch: str) -> str:
    return commits[0].subject if len(commits) == 1 else (commits[-1].subject if commits else branch)


def open_with_gh(title: str, body: str, base: str, head: str, *, draft: bool = False, run: Callable[..., process.ProcessResult] = process.run,
                 which: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    """Create the PR with the GitHub CLI; returns its URL, or None when `gh` is not installed."""
    gh = which("gh")
    if not gh:
        return None
    result = run([gh, "pr", "create", "--title", title, "--body-file", "-", "--base", base, "--head", head,
                  *(["--draft"] if draft else [])], input=body, timeout=120)
    if result.returncode != 0:
        raise ChError("CH8015", detail=result.output.strip()[-800:] or "gh pr create failed")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith("http")]
    return lines[-1] if lines else result.stdout.strip()


def open_with_api(remote_url: str, title: str, body: str, base: str, head: str, *, draft: bool = False,
                  auth: Optional[str] = None, opener: Optional[Callable[..., Any]] = None) -> str:
    """POST /repos/{owner}/{repo}/pulls. Needs a token (never taken from a file)."""
    parsed = parse_remote(remote_url)
    if parsed is None:
        raise ChError("CH8015", detail=f"{remote_url!r} is not a GitHub remote")
    if not auth:
        raise ChError("CH8015", detail="no GitHub token: install the GitHub CLI (`gh auth login`), set GH_TOKEN, or store one "
                                       "in the system keyring (`pip install keyring`; `charpente auth github`)")
    owner, repo = parsed
    request = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/pulls", method="POST",
        data=json.dumps({"title": title, "body": body, "base": base, "head": head, "draft": draft}).encode("utf-8"),
        headers={"Authorization": f"Bearer {auth}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json", "User-Agent": "charpente"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=30) as response:
            data: Dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise ChError("CH8015", detail=f"GitHub answered {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ChError("CH8015", detail=f"could not reach GitHub: {getattr(exc, 'reason', exc)}") from exc
    return str(data.get("html_url", ""))
