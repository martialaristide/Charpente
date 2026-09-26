"""Import a CMake project: ask CMake itself (its File API, "codemodel v2") what the project builds, then write the equivalent `.charpente`.

CMake's own answer is used, not a parse of `CMakeLists.txt`: variables, `if()`, `find_package`, generator expressions and included files are already
evaluated. The project is configured in a scratch build folder (the source folder is never written to). Everything that cannot be translated is listed
in a report instead of being dropped silently: custom commands, generated sources, external libraries found by absolute path, unknown compile flags,
per-configuration settings, tests (`add_test`).

Public/private include directories are not distinguished by the File API: a library's project include directories are all exported to whatever uses it
(a superset of CMake's PUBLIC), which the report says.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core import process
from ..errors import ChError

QUERIES = ("codemodel-v2", "cache-v2", "toolchains-v1")
KIND = {"EXECUTABLE": "Kind.EXECUTABLE", "STATIC_LIBRARY": "Kind.STATIC_LIBRARY", "SHARED_LIBRARY": "Kind.SHARED_LIBRARY", "MODULE_LIBRARY": "Kind.PLUGIN",
        "OBJECT_LIBRARY": "Kind.STATIC_LIBRARY", "INTERFACE_LIBRARY": "Kind.HEADER_ONLY"}
SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".c++", ".m", ".mm", ".s", ".asm")
KEPT_FLAG = re.compile(r"^-(?:W\w[\w=+-]*|Werror(?:=\S+)?|f(?:no-)?(?:exceptions|rtti|strict-aliasing|visibility=\w+|PIC|pic|openmp|permissive|lto)|pthread|m\w[\w=-]*)$")
DROPPED_FLAG = re.compile(r"^-(?:g\d?|O[0-3sgz]?|DNDEBUG|std=\S+|isystem|I\S*|D\S*|MD|MT|MF|MMD|o|c)$|^/(?:Z[i7I]|O\w|MD|MT|std:\S+|I\S*|D\S*|Fo\S*|Fd\S*|FS|c)$|^-fdiagnostics-\S+")


@dataclass
class ImportedTarget:
    name: str
    kind: str
    language: str = "cpp"
    standard: str = ""
    sources: List[str] = field(default_factory=list)
    include_dirs: List[str] = field(default_factory=list)
    defines: List[str] = field(default_factory=list)
    compile_flags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    uses: List[str] = field(default_factory=list)


@dataclass
class Imported:
    name: str
    version: str
    targets: List[ImportedTarget]
    report: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------- running CMake
def configure(source: Path, build: Path, *, cmake: str = "cmake", args: Sequence[str] = (), which: Any = shutil.which) -> Path:
    """Configure `source` into `build` with the File API queries in place; return the folder holding CMake's replies."""
    if not (source / "CMakeLists.txt").is_file():
        raise ChError("CH8026", detail=f"{source} has no CMakeLists.txt")
    exe = which(cmake) or (cmake if Path(cmake).is_file() else None)
    if exe is None:
        raise ChError("CH8026", detail="CMake was not found on PATH (`pip install cmake` gives one, or install it from cmake.org)")
    query = build / ".cmake" / "api" / "v1" / "query"
    query.mkdir(parents=True, exist_ok=True)
    for name in QUERIES:
        (query / name).write_text("", encoding="utf-8")
    argv = [exe, "-S", str(source), "-B", str(build), *args]
    if which("ninja") and not any(a.startswith("-G") for a in args):
        argv += ["-G", "Ninja"]
    result = process.run(argv, timeout=900)
    if result.returncode != 0:
        raise ChError("CH8026", detail=f"CMake could not configure the project:\n{result.output[-1500:]}")
    return build / ".cmake" / "api" / "v1" / "reply"


# ---------------------------------------------------------------------- reading the reply
def _load(reply: Path, name: str) -> Dict[str, Any]:
    try:
        data = json.loads((reply / name).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ChError("CH8026", detail=f"cannot read CMake's reply {name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ChError("CH8026", detail=f"unexpected CMake reply {name}")
    return data


def read_reply(reply: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """(codemodel, [target json...], cache entries by name) from a reply folder."""
    indexes = sorted(reply.glob("index-*.json"))
    if not indexes:
        raise ChError("CH8026", detail=f"CMake wrote no File API reply in {reply}")
    index = _load(reply, indexes[-1].name)
    files = {obj["kind"]: obj["jsonFile"] for obj in index.get("objects", []) if "jsonFile" in obj}
    if "codemodel" not in files:
        raise ChError("CH8026", detail="CMake did not answer the codemodel query (CMake 3.14 or newer is needed)")
    model = _load(reply, files["codemodel"])
    configuration = (model.get("configurations") or [{}])[0]
    targets = [_load(reply, t["jsonFile"]) for t in configuration.get("targets", []) if "jsonFile" in t]
    cache: Dict[str, Any] = {}
    if "cache" in files:
        cache = {e["name"]: e.get("value", "") for e in _load(reply, files["cache"]).get("entries", []) if "name" in e}
    return model, targets, cache


# ---------------------------------------------------------------------- translating
def _relative(path: str, source: Path, build: Path) -> Optional[str]:
    """`path` relative to the source folder (with `/`), or None when it is elsewhere."""
    try:
        return Path(path).resolve().relative_to(source.resolve()).as_posix() or "."
    except (ValueError, OSError):
        return None


def _standard(group: Dict[str, Any], fragments: Sequence[str], language: str) -> str:
    number = str((group.get("languageStandard") or {}).get("standard", ""))
    if not number:
        for fragment in fragments:
            match = re.match(r"^(?:-std=(?:gnu|c)\+\+|/std:c\+\+)(\w+)$", fragment) if language == "cpp" else re.match(r"^(?:-std=(?:gnu|c)|/std:c)(\d+)$", fragment)
            if match:
                number = match.group(1)
                break
    if not number:
        return ""
    return f"c++{number}" if language == "cpp" else f"c{number}"


def convert(model: Dict[str, Any], targets: List[Dict[str, Any]], cache: Dict[str, Any], source: Path, build: Path) -> Imported:
    """Translate CMake's target descriptions into `ImportedTarget`s and a report of what was left behind."""
    report: List[str] = []
    ids = {t["id"]: t["name"] for t in targets}
    imported: List[ImportedTarget] = []
    projects = (model.get("configurations") or [{}])[0].get("projects", [])
    name = str((projects[0] if projects else {}).get("name") or source.name or "project")
    version = str(cache.get("CMAKE_PROJECT_VERSION") or cache.get(f"{name}_VERSION") or "")
    for target in targets:
        kind_name = str(target.get("type", ""))
        tname = str(target["name"])
        if kind_name == "UTILITY" or kind_name not in KIND:
            report.append(f"{tname}: a custom/utility target ({kind_name.lower() or 'unknown'}) has no equivalent: recreate it with a Charpente Rule or a hook if it matters")
            continue
        entry = ImportedTarget(tname, KIND[kind_name])
        if kind_name == "OBJECT_LIBRARY":
            report.append(f"{tname}: an OBJECT library became a static library (its objects are archived, not linked directly)")
        seen_flags: List[str] = []
        languages: set = set()  # type: ignore[type-arg]
        for src in target.get("sources", []):
            path = str(src["path"])
            if src.get("isGenerated"):
                report.append(f"{tname}: {path} is generated at build time (by a custom command): declare a Rule for it, it was left out")
                continue
            rel = _relative(str(source / path), source, build) if not Path(path).is_absolute() else _relative(path, source, build)
            if rel is None:
                report.append(f"{tname}: source {path} is outside the project: left out")
            elif Path(rel).suffix.lower() in SOURCE_SUFFIXES:
                entry.sources.append(rel)
        for group in target.get("compileGroups", []):
            language = "cpp" if str(group.get("language", "CXX")).upper() in ("CXX", "OBJCXX") else "c"
            languages.add(language)
            fragments = [f.get("fragment", "") for f in group.get("compileCommandFragments", [])]
            standard = _standard(group, fragments, language)
            if standard and not entry.standard:
                entry.standard = standard
            for inc in group.get("includes", []):
                if inc.get("isSystem"):
                    continue
                rel = _relative(str(inc["path"]), source, build)
                if rel is None:
                    report.append(f"{tname}: include directory {inc['path']} is outside the project: kept as an absolute path (adjust it, or use ws.requires for a library)")
                    entry.include_dirs.append(str(inc["path"]).replace("\\", "/"))
                elif rel not in entry.include_dirs:
                    entry.include_dirs.append(rel)
            for define in group.get("defines", []):
                text = str(define.get("define", ""))
                if text and text not in entry.defines:
                    entry.defines.append(text)
            for fragment in fragments:
                for part in fragment.split():
                    if KEPT_FLAG.match(part):
                        if part not in entry.compile_flags:
                            entry.compile_flags.append(part)
                    elif not DROPPED_FLAG.match(part) and part not in seen_flags and not part.startswith(("-I", "-D", "/I", "/D")):
                        seen_flags.append(part)
        entry.language = "cpp" if ("cpp" in languages or not languages) else "c"            # a target that compiles C++ at all is a C++ target
        if seen_flags:
            report.append(f"{tname}: compile flags not translated: {' '.join(seen_flags)}")
        link = target.get("link") or {}
        for fragment in link.get("commandFragments", []):
            text = str(fragment.get("fragment", "")).strip()
            role = fragment.get("role", "")
            if role == "libraries":
                for piece in text.split():
                    _translate_library(piece, entry, tname, source, report)
            elif role == "flags" and text:
                report.append(f"{tname}: link flags not translated: {text}")
        for dep in target.get("dependencies", []):
            dname = ids.get(dep.get("id"))
            if dname and dname not in entry.uses:
                entry.uses.append(dname)
        if not entry.standard:
            entry.standard = "c++17" if entry.language == "cpp" else "c11"
            report.append(f"{tname}: no language standard was set in CMake: assumed {entry.standard}")
        imported.append(entry)
    names = {t.name for t in imported}
    for entry in imported:
        entry.uses = [u for u in entry.uses if u in names]
        entry.links = [lib for lib in entry.links if lib not in names]                    # a project library is `uses`, not a system `-l`
    imported = _dependencies_first(imported)
    report.append("Include directories are exported to every target that uses a library (CMake's PUBLIC): CMake's File API does not say which were PRIVATE.")
    report.append("Per-configuration flags (-g, -O2, -DNDEBUG...) were dropped: Charpente adds its own for Debug and Release.")
    report.append("Tests (add_test/CTest) are not part of CMake's target model: mark your test executables with Kind.TEST by hand.")
    return Imported(name, version, imported, report)


#: Libraries CMake puts on every Windows link line (the toolchain's implicit ones): the compiler driver adds them itself.
IMPLICIT_LIBRARIES = frozenset({"kernel32", "user32", "gdi32", "winspool", "shell32", "ole32", "oleaut32", "uuid", "comdlg32", "advapi32",
                                "kernel32.lib", "user32.lib", "gdi32.lib", "winspool.lib", "shell32.lib", "ole32.lib", "oleaut32.lib", "uuid.lib",
                                "comdlg32.lib", "advapi32.lib", "msvcrt", "m", "c", "gcc", "gcc_s", "stdc++"})


def _translate_library(piece: str, entry: ImportedTarget, tname: str, source: Path, report: List[str]) -> None:
    if piece.lstrip("-l") in IMPLICIT_LIBRARIES or piece in IMPLICIT_LIBRARIES:
        return
    if piece.startswith("-l") and len(piece) > 2:
        if piece[2:] not in entry.links:
            entry.links.append(piece[2:])
    elif re.match(r"^(?:lib)?[\w+.-]+\.(?:a|lib|so|dll|dylib)$", piece) and not ("/" in piece or "\\" in piece):
        stem = re.sub(r"^lib", "", piece.rsplit(".", 1)[0])
        if stem not in entry.links:
            entry.links.append(stem)
    elif piece in ("-pthread", "-lm") or piece.startswith(("-Wl,", "-framework")):
        report.append(f"{tname}: link option {piece} not translated")
    elif "/" in piece or "\\" in piece:
        if _relative(piece, source, source) is None:
            report.append(f"{tname}: links {piece}, a library outside the project: replace with ws.requires(\"name\") (a package recipe) or t.links([\"name\"]) and a search path")
    else:
        report.append(f"{tname}: link input {piece!r} not translated")


def _dependencies_first(targets: List[ImportedTarget]) -> List[ImportedTarget]:
    """Order targets so each comes after what it uses (ties by name): the file then reads bottom-up like a build."""
    by_name = {t.name: t for t in targets}
    ordered: List[ImportedTarget] = []
    state: Dict[str, int] = {}

    def visit(name: str) -> None:
        if state.get(name):
            return
        state[name] = 1
        for dep in sorted(by_name[name].uses):
            visit(dep)
        ordered.append(by_name[name])

    for name in sorted(by_name):
        visit(name)
    return ordered


# ---------------------------------------------------------------------- writing
def _list(values: Sequence[str]) -> str:
    return "[" + ", ".join(json.dumps(v) for v in values) + "]"


def render(imported: Imported, source_name: str = "CMakeLists.txt") -> str:
    lines = ["from charpente import *", "", f"# Imported from {source_name} by `charpente import cmake`. Review it: the report at the end of this file lists what could not be translated.",
             f"with Workspace({json.dumps(imported.name)}" + (f", version={json.dumps(imported.version)}" if imported.version else "") + ") as ws:",
             '    ws.configurations(["Debug", "Release"])', ""]
    for t in imported.targets:
        var = "t"
        lines.append(f"    with Target({json.dumps(t.name)}) as {var}:")
        lines.append(f"        {var}.kind({t.kind})")
        if t.kind != "Kind.HEADER_ONLY":
            lines.append(f"        {var}.standard({json.dumps(t.standard)})")
        if t.sources:
            lines.append(f"        {var}.sources({_list(sorted(t.sources))})")
        if t.include_dirs:
            method = "public_include_dirs" if t.kind in ("Kind.STATIC_LIBRARY", "Kind.SHARED_LIBRARY", "Kind.HEADER_ONLY", "Kind.PLUGIN") else "include_dirs"
            lines.append(f"        {var}.{method}({_list(t.include_dirs)})")
        if t.defines:
            lines.append(f"        {var}.defines({_list(t.defines)})")
        if t.compile_flags:
            lines.append(f"        {var}.compile_flags({_list(t.compile_flags)})")
        if t.links:
            lines.append(f"        {var}.links({_list(t.links)})")
        if t.uses:
            lines.append(f"        {var}.uses({', '.join(json.dumps(u) for u in t.uses)})")
        lines.append("")
    lines += ["# ---- import report " + "-" * 60] + [f"# - {item}" for item in imported.report]
    return "\n".join(lines).rstrip() + "\n"


def import_project(source: Path, *, out_build: Optional[Path] = None, cmake: str = "cmake", args: Sequence[str] = ()) -> Imported:
    """Configure `source` in a scratch folder (or `out_build`) and convert the result."""
    source = source.resolve()
    if out_build is not None:
        reply = configure(source, out_build.resolve(), cmake=cmake, args=args)
        return convert(*read_reply(reply), source, out_build.resolve())
    scratch = Path(tempfile.mkdtemp(prefix="charpente-import-"))
    try:
        reply = configure(source, scratch, cmake=cmake, args=args)
        return convert(*read_reply(reply), source, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
