"""Releases: the next version, the changelog, checksums, signatures and a provenance statement.

Pure functions first: what version comes next given the commits, what the changelog says, what the provenance
statement contains. `commands/release.py` sequences them with Git, packaging and (only when asked) GitHub.

Provenance: Charpente writes an in-toto Statement with a SLSA v1 provenance predicate and signs it as a DSSE envelope with
your release key. Produced on a developer machine this documents *what was built from which commit with which command*; it
is not SLSA build level 3, which needs an isolated, hosted builder. In GitHub Actions, add `actions/attest-build-provenance`
for that. The statement says so itself (`builder.id`).
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..errors import ChError
from ..semver import Version
from .git import CONVENTIONAL, Commit

parse_version = Version.parse

SLSA_PREDICATE = "https://slsa.dev/provenance/v1"
IN_TOTO_STATEMENT = "https://in-toto.io/Statement/v1"
DSSE_PAYLOAD_TYPE = "application/vnd.in-toto+json"
BUILD_TYPE = "https://charpente.dev/build/v1"

SECTIONS = [("breaking", "Breaking changes"), ("feat", "Features"), ("fix", "Fixes"), ("perf", "Performance"),
            ("refactor", "Refactoring"), ("docs", "Documentation"), ("build", "Build"), ("ci", "CI"), ("test", "Tests")]


def classify(commit: Commit) -> Tuple[str, str, str]:
    """(type, scope, subject) of a commit; non-conventional commits are type `other`. `breaking` when `!` or a footer says so."""
    match = CONVENTIONAL.match(commit.subject)
    if not match:
        return "other", "", commit.subject
    breaking = bool(match.group("breaking")) or "BREAKING CHANGE" in commit.body or "BREAKING-CHANGE" in commit.body
    return ("breaking" if breaking else match.group("type")), match.group("scope") or "", match.group("subject")


def bump_kind(commits: Sequence[Commit], current: str) -> Optional[str]:
    """`major`/`minor`/`patch` implied by the commits, or None when nothing releasable changed.

    Conventional Commits rules, with the usual pre-1.0 convention: while the major version is 0 a breaking change bumps the
    minor and features bump the patch, so that `0.x` can move without claiming stability."""
    kinds = {classify(c)[0] for c in commits}
    pre_one = parse_version(current).major == 0 if current else True
    if "breaking" in kinds:
        return "minor" if pre_one else "major"
    if "feat" in kinds:
        return "patch" if pre_one else "minor"
    if kinds & {"fix", "perf", "refactor", "revert"}:
        return "patch"
    return None


def next_version(current: str, kind: str) -> str:
    """`current` bumped by `major|minor|patch`, or `kind` itself when it is an explicit X.Y.Z."""
    if re.fullmatch(r"\d+\.\d+\.\d+", kind):
        parse_version(kind)
        return kind
    base = parse_version(current or "0.0.0")
    if kind == "major":
        return f"{base.major + 1}.0.0"
    if kind == "minor":
        return f"{base.major}.{base.minor + 1}.0"
    if kind == "patch":
        return f"{base.major}.{base.minor}.{base.patch + 1}"
    raise ChError("CH8016", reason=f"{kind!r} is not major, minor, patch or a version like 1.2.3")


def changelog_section(version: str, commits: Sequence[Commit], today: Optional[datetime.date] = None) -> str:
    """The Markdown block for this release, grouped by type, newest sections first."""
    date = (today or datetime.date.today()).isoformat()
    grouped: Dict[str, List[str]] = {}
    for commit in commits:
        kind, scope, subject = classify(commit)
        if kind in ("other", "chore", "style", "revert"):
            continue
        line = f"- {'**' + scope + ':** ' if scope else ''}{subject} ({commit.short})"
        grouped.setdefault(kind, []).append(line)
    lines = [f"## v{version} -- {date}", ""]
    for key, title in SECTIONS:
        if key in grouped:
            lines += [f"### {title}", "", *grouped[key], ""]
    if len(lines) == 2:
        lines += ["Maintenance release.", ""]
    return "\n".join(lines)


def prepend_changelog(existing: str, section: str) -> str:
    """Put `section` under the changelog's title (adding one if there is none)."""
    if existing.lstrip().startswith("# "):
        head, _, rest = existing.partition("\n")
        return head + "\n\n" + section.rstrip("\n") + "\n\n" + rest.lstrip("\n")
    return "# Changelog\n\n" + section.rstrip("\n") + "\n\n" + existing.lstrip("\n")


# ------------------------------------------------------------------ version files
def _workspace_files(root: Path) -> List[Path]:
    """`*.charpente` *files* (a project's `.charpente/` directory matches the pattern too and is not a workspace)."""
    return sorted(p for p in root.glob("*.charpente") if p.is_file())


def read_version(root: Path) -> Optional[str]:
    """The workspace's declared version (`Workspace(..., version="1.2.3")` or `[workspace] version` in charpente.toml)."""
    for path in _workspace_files(root):
        found = re.search(r"""Workspace\([^)]*?\bversion\s*=\s*["']([^"']+)["']""", path.read_text(encoding="utf-8-sig"), re.S)
        if found:
            return found.group(1)
    toml = root / "charpente.toml"
    if toml.is_file():
        found = re.search(r'(?m)^version\s*=\s*"([^"]+)"', toml.read_text(encoding="utf-8"))
        if found:
            return found.group(1)
    return None


def write_version(root: Path, old: str, new: str) -> Path:
    """Replace the declared version in place (only the literal in the workspace declaration); returns the file changed."""
    for path in _workspace_files(root):
        text = path.read_text(encoding="utf-8-sig")
        pattern = re.compile(r"""(Workspace\([^)]*?\bversion\s*=\s*)(["'])""" + re.escape(old) + r"""\2""", re.S)
        if pattern.search(text):
            path.write_text(pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{new}{m.group(2)}", text, count=1), encoding="utf-8")
            return path
    toml = root / "charpente.toml"
    if toml.is_file():
        text = toml.read_text(encoding="utf-8")
        pattern = re.compile(r'(?m)^(version\s*=\s*)"' + re.escape(old) + '"')
        if pattern.search(text):
            toml.write_text(pattern.sub(lambda m: f'{m.group(1)}"{new}"', text, count=1), encoding="utf-8")
            return toml
    raise ChError("CH8016", reason=f"could not find `version=\"{old}\"` in the workspace declaration to update "
                                   "(declare it as a string literal: Workspace(\"name\", version=\"1.2.3\"))")


# ------------------------------------------------------------------ checksums, signatures, provenance
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def checksums(files: Sequence[Path]) -> str:
    """`sha256sum`-compatible text: `<hex>  <name>` per file, sorted by name."""
    return "".join(f"{sha256_file(f)}  {f.name}\n" for f in sorted(files, key=lambda p: p.name))


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE pre-authentication encoding: `DSSEv1 <len(type)> <type> <len(body)> <body>`."""
    return b"DSSEv1 %d %s %d %s" % (len(payload_type), payload_type.encode(), len(payload), payload)


def provenance_statement(artifacts: Sequence[Path], *, source_uri: str, commit: str, command: Sequence[str], version: str,
                         builder_id: str, started: str, finished: str, dependencies: Optional[Sequence[Tuple[str, str]]] = None
                         ) -> Dict[str, Any]:
    """An in-toto Statement v1 with a SLSA provenance v1 predicate for `artifacts`."""
    return {
        "_type": IN_TOTO_STATEMENT,
        "subject": [{"name": a.name, "digest": {"sha256": sha256_file(a)}} for a in sorted(artifacts, key=lambda p: p.name)],
        "predicateType": SLSA_PREDICATE,
        "predicate": {
            "buildDefinition": {
                "buildType": BUILD_TYPE,
                "externalParameters": {"command": list(command), "version": version, "source": source_uri},
                "internalParameters": {},
                "resolvedDependencies": [{"uri": source_uri, "digest": {"gitCommit": commit}},
                                         *[{"name": n, "digest": {"sha256": d}} for n, d in (dependencies or [])]],
            },
            "runDetails": {"builder": {"id": builder_id}, "metadata": {"startedOn": started, "finishedOn": finished}},
        },
    }


def dsse_envelope(statement: Dict[str, Any], key_id: str, sign: Any) -> Dict[str, Any]:
    """Wrap `statement` in a DSSE envelope signed with `sign(bytes) -> signature bytes`."""
    payload = json.dumps(statement, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = sign(pae(DSSE_PAYLOAD_TYPE, payload))
    return {"payloadType": DSSE_PAYLOAD_TYPE, "payload": base64.b64encode(payload).decode("ascii"),
            "signatures": [{"keyid": key_id, "sig": base64.b64encode(signature).decode("ascii")}]}


def verify_envelope(envelope: Dict[str, Any], verify: Any) -> Dict[str, Any]:
    """The statement inside `envelope` if a signature verifies (`verify(message, signature) -> bool`), else CH8016."""
    payload = base64.b64decode(envelope["payload"])
    message = pae(str(envelope["payloadType"]), payload)
    if not any(verify(message, base64.b64decode(s["sig"])) for s in envelope.get("signatures", [])):
        raise ChError("CH8016", reason="the provenance signature does not verify")
    statement: Dict[str, Any] = json.loads(payload)
    return statement


def builder_identity(env: Dict[str, str]) -> str:
    """Who built it, as honestly as Charpente can say: the GitHub Actions run, or a local machine (no isolation claim)."""
    if env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_SERVER_URL") and env.get("GITHUB_REPOSITORY"):
        return f"{env['GITHUB_SERVER_URL']}/{env['GITHUB_REPOSITORY']}/actions/runs/{env.get('GITHUB_RUN_ID', '0')}"
    return "charpente:local-build (not an isolated builder: SLSA build level 1 documentation only)"
