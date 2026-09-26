"""What Charpente sends to an AI provider: minimal, secret-free, and shown to the user before it leaves the machine.

A `Context` is a list of labelled `Item`s (the error text, the lines of code around each reported location, a one-line workspace summary...).
It is built from the files of the project only (never outside), never includes files that look like secrets stores, passes every text through
`redact`, and stays under a size limit. `Context.render()` is exactly the text sent, and `Context.summary()` is what `--show-context` shows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..quality.checks_static import _ASSIGNMENT, _PLACEHOLDER, SECRET_PATTERNS, entropy

DEFAULT_LIMIT = 12000
SNIPPET_RADIUS = 18
MAX_FILES = 4

# Files that hold secrets by convention are never sent, whatever the compiler said about them.
_SECRET_FILES = re.compile(r"(?i)(?:^|/)(?:\.env(?:\..*)?|.*\.(?:pem|key|p12|pfx|jks|keystore|kdbx)|id_(?:rsa|dsa|ecdsa|ed25519)|.*secrets?\..*|"
                           r"credentials(?:\..*)?|\.netrc|\.npmrc|\.pypirc)$")
_URL_CREDENTIALS = re.compile(r"(?P<scheme>\b[a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@")
_BEARER = re.compile(r"(?i)\b(?P<label>authorization\s*:\s*(?:bearer|basic|token)\s+)[A-Za-z0-9._~+/=-]{8,}")
LOCATION = re.compile(r"(?P<file>(?:[A-Za-z]:)?[^\s:()\"'<>|]+\.(?:c|cc|cpp|cxx|h|hh|hpp|hxx|inl|charpente)):(?P<line>\d+)")


def redact_text(text: str) -> Tuple[str, int]:
    """(text with secrets replaced by `[REDACTED ...]`, number of replacements). Conservative: known token formats, credentials in URLs,
    Authorization headers, and quoted high-entropy values assigned to names like `password`/`api_key`."""
    count = 0

    def sub(pattern: "re.Pattern[str]", replacement: str, value: str) -> str:
        nonlocal count
        value, n = pattern.subn(replacement, value)
        count += n
        return value

    for label, pattern in SECRET_PATTERNS:
        text = sub(pattern, f"[REDACTED {label}]", text)
    text = sub(_URL_CREDENTIALS, r"\g<scheme>[REDACTED credentials]@", text)
    text = sub(_BEARER, r"\g<label>[REDACTED token]", text)

    def assignment(match: "re.Match[str]") -> str:
        nonlocal count
        value = match.group("value")
        if _PLACEHOLDER.match(value) or entropy(value) < 3.3:
            return match.group(0)
        count += 1
        return match.group(0).replace(value, "[REDACTED value]")

    return _ASSIGNMENT.sub(assignment, text), count


def is_secret_file(relative: str) -> bool:
    return bool(_SECRET_FILES.search(relative.replace("\\", "/")))


@dataclass
class Item:
    label: str
    text: str
    redactions: int = 0

    @property
    def chars(self) -> int:
        return len(self.text)


@dataclass
class Context:
    items: List[Item] = field(default_factory=list)
    limit: int = DEFAULT_LIMIT
    skipped: List[str] = field(default_factory=list)          # things left out, and why (shown to the user)

    @property
    def chars(self) -> int:
        return sum(i.chars for i in self.items)

    @property
    def redactions(self) -> int:
        return sum(i.redactions for i in self.items)

    def add(self, label: str, text: str) -> bool:
        """Add redacted `text`; refused (and noted) when the size limit would be exceeded."""
        clean, redactions = redact_text(text)
        if self.chars + len(clean) > self.limit:
            room = self.limit - self.chars
            if room < 200:
                self.skipped.append(f"{label} (over the {self.limit}-character limit)")
                return False
            clean = clean[:room] + "\n[... cut at the size limit ...]"
        self.items.append(Item(label, clean, redactions))
        return True

    def render(self) -> str:
        """The text that is sent."""
        return "\n\n".join(f"### {item.label}\n{item.text}" for item in self.items)

    def summary(self) -> str:
        lines = [f"  - {item.label}: {item.chars} characters" + (f", {item.redactions} secret(s) replaced" if item.redactions else "")
                 for item in self.items]
        lines += [f"  - left out: {note}" for note in self.skipped]
        lines.append(f"  total: {self.chars} characters")
        return "\n".join(lines)


def workspace_summary(workspace: object) -> str:
    targets = getattr(workspace, "targets", {})
    parts = []
    for name, target in sorted(targets.items()):
        if getattr(target, "external", False):
            continue
        parts.append(f"{name} ({target.kind.value}, {target.language.value} {target.standard})")
    return f"Charpente workspace {getattr(workspace, 'name', '')!r}; targets: " + (", ".join(parts) or "none")


def snippet(root: Path, relative: str, line: int, radius: int = SNIPPET_RADIUS) -> Optional[str]:
    """Numbered lines around `line` of a project file, or None when the file is outside the project, secret-like, missing or not text."""
    if is_secret_file(relative):
        return None
    path = Path(relative)
    candidate = path if path.is_absolute() else root / path
    try:
        resolved = candidate.resolve()
        root_resolved = root.resolve()
        if root_resolved not in resolved.parents or not resolved.is_file() or resolved.stat().st_size > 512 * 1024:
            return None
        rows = resolved.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    first = max(line - radius, 1)
    last = min(line + radius, len(rows))
    return "\n".join(f"{n:>5}| {rows[n - 1]}" for n in range(first, last + 1))


def locations(error_text: str) -> List[Tuple[str, int]]:
    """Distinct (file, line) pairs mentioned in compiler output, in order of appearance."""
    seen: Dict[Tuple[str, int], None] = {}
    for match in LOCATION.finditer(error_text):
        seen.setdefault((match.group("file"), int(match.group("line"))), None)
    return list(seen)


def error_context(root: Path, workspace: object, error_text: str, *, limit: int = DEFAULT_LIMIT, extra: Sequence[Tuple[str, str]] = ()) -> Context:
    """The context for explaining or fixing a failed build: summary, the error, and code around each reported location."""
    context = Context(limit=limit)
    context.add("workspace", workspace_summary(workspace))
    context.add("build output", error_text.strip()[-6000:])
    seen: List[str] = []
    for file, line in locations(error_text):
        rel = _relative(root, file)
        if rel is None:
            context.skipped.append(f"{file} (outside the project)")
            continue
        if is_secret_file(rel):
            context.skipped.append(f"{rel} (looks like a secrets file)")
            continue
        if rel not in seen and len(seen) >= MAX_FILES:
            context.skipped.append(f"{rel}:{line} (more than {MAX_FILES} files)")
            continue
        code = snippet(root, rel, line)
        if code is not None and context.add(f"{rel}:{line}", code) and rel not in seen:
            seen.append(rel)
    for label, text in extra:
        context.add(label, text)
    return context


def _relative(root: Path, file: str) -> Optional[str]:
    path = Path(file)
    try:
        resolved = (path if path.is_absolute() else root / path).resolve()
        return resolved.relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
