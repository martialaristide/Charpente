"""Project documentation: what each target exposes (from the doc comments of its public headers) and how the targets depend on each other.

The extractor is deliberately small and honest: it finds documentation comments (`///`, `//!`, `/** */`, `/*! */`) and the declaration that follows each one, understands
the common Doxygen tags (`@brief`, `@param`, `@return`, `@note`, `@warning`, `@see`) and classifies classes, structs, enums, unions, namespaces, functions, aliases, macros and variables.
It is a text scanner, not a C++ parser: templates with unusual layouts, declarations produced by macros and comments in the middle of a declaration can be misread.
When Doxygen is installed, `charpente docs --doxygen` runs it instead for full C++ understanding (a Doxyfile is generated from the workspace).
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .dsl.model import Kind, Target, Workspace

HEADER_SUFFIXES = (".h", ".hh", ".hpp", ".hxx", ".inl")
_TAG = re.compile(r"^[@\\](brief|param|return|returns|note|warning|see|throws|deprecated|since|tparam)\b\s*(.*)$")


@dataclass
class Item:
    kind: str                       # class | struct | enum | union | namespace | function | alias | macro | variable
    name: str
    signature: str
    brief: str = ""
    body: str = ""
    params: List[Tuple[str, str]] = field(default_factory=list)
    returns: str = ""
    notes: List[str] = field(default_factory=list)
    line: int = 0


def _clean_comment(raw: str) -> List[str]:
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        line = re.sub(r"^(/\*\*|/\*!|\*/|\*|///|//!)\s?", "", line)
        line = re.sub(r"\s*\*/$", "", line)
        lines.append(line.rstrip())
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _comment_blocks(text: str) -> List[Tuple[int, int, str]]:
    """(start line, end offset, raw comment) for every documentation comment, in order."""
    blocks: List[Tuple[int, int, str]] = []
    for match in re.finditer(r"/\*[*!](?!/)[\s\S]*?\*/", text):
        blocks.append((text.count("\n", 0, match.start()) + 1, match.end(), match.group(0)))
    for match in re.finditer(r"(?:^[ \t]*(?:///|//!)[^\n]*\n?)+", text, re.MULTILINE):
        blocks.append((text.count("\n", 0, match.start()) + 1, match.end(), match.group(0)))
    return sorted(blocks, key=lambda b: b[1])


def _declaration_after(text: str, offset: int) -> str:
    """The declaration that starts at `offset`: up to the first `;` or `{` at depth zero (parentheses and angle brackets balanced)."""
    rest = text[offset:]
    depth = 0
    out: List[str] = []
    for ch in rest:
        if ch in "(<[":
            depth += 1
        elif ch in ")>]":
            depth = max(depth - 1, 0)
        if depth == 0 and ch in ";{":
            break
        out.append(ch)
        if len(out) > 1500:
            break
    declaration = " ".join("".join(out).split())
    return re.sub(r"\s*=\s*(default|delete)\s*$", r" = \1", declaration)


_CLASSIFY = [
    (re.compile(r"^(?:template\s*<[^>]*>\s*)?(class|struct|union)\s+(?:\[\[[^\]]*\]\]\s*)?(?:\w+_API\s+)?(\w+)"), None),
    (re.compile(r"^enum\s+(?:class\s+|struct\s+)?(\w+)"), "enum"),
    (re.compile(r"^namespace\s+([\w:]+)"), "namespace"),
    (re.compile(r"^#\s*define\s+(\w+)"), "macro"),
    (re.compile(r"^(?:template\s*<[^>]*>\s*)?using\s+(\w+)\s*="), "alias"),
    (re.compile(r"^typedef\b.*?(\w+)\s*(?:\[[^\]]*\])?$"), "alias"),
]
_FUNCTION = re.compile(r"(~?[A-Za-z_]\w*(?:::\w+)*|operator\s*[^\s(]+)\s*\(")


def classify(declaration: str) -> Optional[Tuple[str, str]]:
    """(kind, name) of a declaration, or None when it is not one we document."""
    for pattern, fixed in _CLASSIFY:
        match = pattern.match(declaration)
        if match:
            if fixed is None:
                return match.group(1), match.group(2)
            return fixed, match.group(1)
    if "(" in declaration and not declaration.startswith(("if", "for", "while", "return")):
        match = _FUNCTION.search(declaration)
        if match:
            return "function", match.group(1)
    match = re.search(r"(\w+)\s*(?:\[[^\]]*\])?\s*(?:=.*)?$", declaration)
    if match and re.match(r"^(?:static\s+|extern\s+|inline\s+|constexpr\s+|const\s+|\w+[\w:<>,\s*&]*\s+)\w", declaration) and " " in declaration:
        return "variable", match.group(1)
    return None


def parse_comment(lines: Sequence[str]) -> Tuple[str, str, List[Tuple[str, str]], str, List[str]]:
    """(brief, body, params, returns, notes) from cleaned comment lines."""
    brief_parts: List[str] = []
    body: List[str] = []
    params: List[Tuple[str, str]] = []
    returns = ""
    notes: List[str] = []
    current: Optional[str] = None
    for line in lines:
        tag = _TAG.match(line)
        if tag:
            name, rest = tag.group(1), tag.group(2)
            current = name
            if name == "brief":
                brief_parts.append(rest)
            elif name == "param" or name == "tparam":
                pm = re.match(r"(?:\[[a-z,]+\]\s*)?(\w+)\s*(.*)", rest)
                params.append((pm.group(1), pm.group(2)) if pm else ("", rest))
            elif name in ("return", "returns"):
                returns = rest
            else:
                notes.append(f"{name}: {rest}")
            continue
        if not line:
            current = current if current in ("brief",) else None
            if body and body[-1] != "":
                body.append("")
            continue
        if current == "brief":
            brief_parts.append(line)
        elif current in ("param", "tparam") and params:
            params[-1] = (params[-1][0], " ".join((params[-1][1] + " " + line).split()))
        elif current in ("return", "returns"):
            returns = " ".join((returns + " " + line).split())
        elif current in ("note", "warning", "see", "throws", "deprecated", "since") and notes:
            notes[-1] = " ".join((notes[-1] + " " + line).split())
        else:
            body.append(line)
    brief = " ".join(brief_parts).strip()
    text = "\n".join(body).strip()
    if not brief and text:                                        # no @brief: the first sentence/paragraph is the summary
        first, _, remainder = text.partition("\n\n")
        brief, text = " ".join(first.split()), remainder.strip()
    return brief, text, params, returns, notes


def extract(text: str) -> List[Item]:
    """The documented declarations of a header, in order."""
    items: List[Item] = []
    for line, end, raw in _comment_blocks(text):
        declaration = _declaration_after(text, end)
        if raw.lstrip().startswith(("//", "/*")) and re.match(r"^\s*$", declaration):
            continue
        classified = classify(declaration.strip())
        if classified is None:
            continue
        kind, name = classified
        brief, body, params, returns, notes = parse_comment(_clean_comment(raw))
        items.append(Item(kind, name, declaration.strip(), brief, body, params, returns, notes, line))
    return items


# ---------------------------------------------------------------------- output
def public_headers(workspace: Workspace, target: Target) -> List[Path]:
    base = target.location or workspace.root
    found: List[Path] = []
    for directory in [*target.public_include_dirs, *target.interface_include_dirs, *target.include_dirs]:
        folder = Path(directory) if Path(directory).is_absolute() else base / directory
        if folder.is_dir():
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path.suffix.lower() in HEADER_SUFFIXES and path not in found:
                    found.append(path)
    return found


def render_items(items: Sequence[Item]) -> str:
    out: List[str] = []
    for item in items:
        out.append(f"### `{item.name}` — {item.kind}")
        out.append("")
        out.append("```cpp\n" + item.signature + "\n```")
        if item.brief:
            out += ["", item.brief]
        if item.body:
            out += ["", item.body]
        if item.params:
            out += ["", "**Parameters**", ""] + [f"- `{n}`: {d}" for n, d in item.params]
        if item.returns:
            out += ["", f"**Returns:** {item.returns}"]
        for note in item.notes:
            out += ["", f"> {note}"]
        out.append("")
    return "\n".join(out)


def target_page(workspace: Workspace, target: Target) -> Tuple[str, int]:
    root = workspace.root
    lines = [f"# {target.name}", "", f"{target.kind.value.replace('_', ' ')}, {target.language.value} `{target.standard}`", ""]
    if target.uses or target.uses_public:
        lines += ["Uses: " + ", ".join(f"[{u}]({u}.md)" if u in workspace.targets and not workspace.targets[u].external else u for u in [*target.uses, *target.uses_public]), ""]
    total = 0
    for header in public_headers(workspace, target):
        try:
            items = extract(header.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if not items:
            continue
        total += len(items)
        try:
            shown = header.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            shown = header.as_posix()
        lines += [f"## `{shown}`", "", render_items(items)]
    if total == 0:
        lines += ["_No documented declarations were found in this target's public headers (documentation comments start with `///`, `//!` or `/** */`)._", ""]
    return "\n".join(lines).rstrip() + "\n", total


def mermaid(workspace: Workspace) -> str:
    lines = ["graph LR"]
    own = [n for n, t in workspace.targets.items() if not t.external]
    for name in own:
        target = workspace.targets[name]
        shape = {"executable": "([{}])", "test": "{{{{{}}}}}", "static_library": "[{}]", "shared_library": "[[{}]]", "plugin": "[[{}]]"}.get(target.kind.value, "[{}]")
        lines.append(f"  {name}{shape.format(name)}")
    for name in own:
        for dep in workspace.targets[name].dependencies():
            if dep in own:
                lines.append(f"  {name} --> {dep}")
    return "\n".join(lines) + "\n"


def svg(workspace: Workspace) -> str:
    """The dependency graph as a standalone SVG (layers by dependency depth, dependencies on the left)."""
    own = [n for n, t in workspace.targets.items() if not t.external]
    deps = {n: [d for d in workspace.targets[n].dependencies() if d in own] for n in own}
    depth: Dict[str, int] = {}

    def level(name: str, seen: Tuple[str, ...] = ()) -> int:
        if name in depth:
            return depth[name]
        if name in seen:
            return 0
        depth[name] = max((level(d, seen + (name,)) + 1 for d in deps[name]), default=0)
        return depth[name]

    for n in own:
        level(n)
    columns: Dict[int, List[str]] = {}
    for n in sorted(own):
        columns.setdefault(depth[n], []).append(n)
    width, height = 170, 44
    positions = {n: (16 + c * 220, 16 + r * 64) for c, names in columns.items() for r, n in enumerate(names)}
    total_w = 32 + (max(columns) if columns else 0) * 220 + width
    total_h = 32 + max((len(v) for v in columns.values()), default=1) * 64
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {total_h}" width="{total_w}" height="{total_h}" font-family="sans-serif" font-size="13">',
             '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#6b7280"/></marker></defs>']
    for n in own:
        for d in deps[n]:
            x1, y1 = positions[d][0] + width, positions[d][1] + height / 2
            x2, y2 = positions[n][0], positions[n][1] + height / 2
            mid = (x1 + x2) / 2
            parts.append(f'<path d="M{x1} {y1} C{mid} {y1} {mid} {y2} {x2} {y2}" fill="none" stroke="#6b7280" stroke-width="1.4" marker-end="url(#a)"/>')
    for n in own:
        x, y = positions[n]
        kind = workspace.targets[n].kind
        fill = "#dbeafe" if kind == Kind.EXECUTABLE else "#f3f4f6"
        parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="7" fill="{fill}" stroke="#9ca3af"/>')
        parts.append(f'<text x="{x + 10}" y="{y + 19}" font-weight="600">{html.escape(n)}</text>')
        parts.append(f'<text x="{x + 10}" y="{y + 35}" fill="#6b7280">{html.escape(kind.value)}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def index_page(workspace: Workspace, counts: Dict[str, int]) -> str:
    lines = [f"# {workspace.name}", ""]
    if workspace.version:
        lines += [f"Version {workspace.version}", ""]
    lines += ["## Targets", "", "| Target | Kind | Language | Documented declarations |", "|---|---|---|---|"]
    for name in workspace.build_order():
        t = workspace.targets[name]
        if t.external:
            continue
        lines.append(f"| [{name}](targets/{name}.md) | {t.kind.value} | {t.language.value} `{t.standard}` | {counts.get(name, 0)} |")
    lines += ["", "## Dependencies", "", "![target dependency graph](graph.svg)", "", "```mermaid", mermaid(workspace).rstrip(), "```", ""]
    if workspace.requires:
        lines += ["## Packages", ""] + [f"- `{spec}`" for spec in workspace.requires] + [""]
    return "\n".join(lines)


def doxyfile(workspace: Workspace, out: Path) -> str:
    inputs = sorted({str(d if Path(d).is_absolute() else (t.location or workspace.root) / d) for t in workspace.targets.values() if not t.external
                     for d in [*t.public_include_dirs, *t.include_dirs]})
    return "\n".join([f"PROJECT_NAME = {workspace.name!r}".replace("'", '"'), f"PROJECT_NUMBER = {workspace.version}", f"OUTPUT_DIRECTORY = {out}",
                      "INPUT = " + " ".join(f'"{i}"' for i in inputs), "RECURSIVE = YES", "FILE_PATTERNS = *.h *.hh *.hpp *.hxx *.inl", "EXTRACT_ALL = NO", "GENERATE_LATEX = NO",
                      "GENERATE_HTML = YES", "QUIET = YES", "WARN_IF_UNDOCUMENTED = NO"]) + "\n"
