"""`CMakeLists.txt` from a Charpente workspace, for people who need CMake (a package manager, an IDE, a company standard).

It is generated from the workspace model: kinds, sources (globs expanded now), public/private include directories, defines, compile flags, `uses`
(as `target_link_libraries`), link libraries, the language standard, tests (`enable_testing`/`add_test`). Not translated, and listed in the file's
header: configuration/platform/toolchain overlays (`on_config`...), rules (generated files), platform settings (Android, HarmonyOS, iOS...), assets,
`ws.requires` packages (CMake needs `find_package` or a FetchContent recipe for those: the names are listed) and hooks.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from ..dsl.model import Kind, Language, Target, Workspace

_BUILD_KIND = {Kind.EXECUTABLE: "add_executable({name} {sources})", Kind.TEST: "add_executable({name} {sources})",
               Kind.STATIC_LIBRARY: "add_library({name} STATIC {sources})", Kind.SHARED_LIBRARY: "add_library({name} SHARED {sources})",
               Kind.PLUGIN: "add_library({name} MODULE {sources})", Kind.HEADER_ONLY: "add_library({name} INTERFACE)"}


def _q(text: str) -> str:
    """A CMake argument: quoted, with backslashes and quotes escaped, `\\` never left to be read as an escape."""
    return '"' + str(text).replace("\\", "/").replace('"', '\\"').replace("$", "\\$") + '"'


def _paths(values: List[str]) -> str:
    return " ".join(_q(v) for v in values)


def _sources(target: Target, root: Path) -> List[str]:
    out: List[str] = []
    for path in target.resolved_sources():
        try:
            out.append(path.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            out.append(path.as_posix())
    return sorted(out)


def _standard(target: Target) -> Optional[str]:
    match = target.standard.lower().replace("gnu++", "").replace("c++", "").replace("gnu", "").lstrip("c")
    return match if match.isdigit() else None


def render(workspace: Workspace) -> str:
    root = workspace.root
    notes: List[str] = []
    languages = sorted({"CXX" if t.language == Language.CPP else "C" for t in workspace.targets.values() if not t.external}) or ["CXX"]
    lines: List[str] = ["cmake_minimum_required(VERSION 3.16)", f"project({workspace.name} VERSION {workspace.version or '0.0.0'} LANGUAGES {' '.join(languages)})", ""]
    has_tests = any(t.kind == Kind.TEST for t in workspace.targets.values())
    if has_tests:
        lines += ["enable_testing()", ""]
    lines += ['if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)', '  set(CMAKE_BUILD_TYPE Debug)', 'endif()', ""]
    order = [n for n in workspace.build_order() if not workspace.targets[n].external]
    for name in order:
        target = workspace.targets[name]
        pattern = _BUILD_KIND.get(target.kind)
        if pattern is None:
            notes.append(f"{name}: kind {target.kind.value} has no CMake equivalent here: left out")
            continue
        sources = _sources(target, root) if target.kind != Kind.HEADER_ONLY else []
        if target.kind != Kind.HEADER_ONLY and not sources:
            notes.append(f"{name}: no source files matched: left out")
            continue
        lines.append(pattern.format(name=name, sources=_paths(sources)))
        scope = "INTERFACE" if target.kind == Kind.HEADER_ONLY else "PRIVATE"
        for keyword, values in ((scope, target.include_dirs), ("PUBLIC" if scope == "PRIVATE" else "INTERFACE", target.public_include_dirs), ("INTERFACE", target.interface_include_dirs)):
            if values:
                lines.append(f"target_include_directories({name} {keyword} {_paths(values)})")
        for keyword, values in ((scope, target.define_macros), ("PUBLIC" if scope == "PRIVATE" else "INTERFACE", target.public_define_macros), ("INTERFACE", target.interface_define_macros)):
            if values:
                lines.append(f"target_compile_definitions({name} {keyword} {_paths(values)})")
        if target.extra_compile_flags:
            lines.append(f"target_compile_options({name} PRIVATE {_paths(target.extra_compile_flags)})")
        if target.public_compile_flags:
            lines.append(f"target_compile_options({name} PUBLIC {_paths(target.public_compile_flags)})")
        libs_private = [u for u in target.uses if u in workspace.targets and not workspace.targets[u].external] + target.link_libraries
        libs_public = [u for u in target.uses_public if u in workspace.targets and not workspace.targets[u].external] + target.public_link_libraries
        if libs_public:
            lines.append(f"target_link_libraries({name} PUBLIC {' '.join(libs_public)})")
        if libs_private:
            lines.append(f"target_link_libraries({name} {'INTERFACE' if scope == 'INTERFACE' else 'PRIVATE'} {' '.join(libs_private)})")
        order_only = [d for d in target.depends_on if d in workspace.targets and not workspace.targets[d].external]
        if order_only:
            lines.append(f"add_dependencies({name} {' '.join(order_only)})")
        standard = _standard(target)
        if standard and target.kind != Kind.HEADER_ONLY:
            prefix = "CXX" if target.language == Language.CPP else "C"
            lines.append(f"set_target_properties({name} PROPERTIES {prefix}_STANDARD {standard} {prefix}_STANDARD_REQUIRED ON {prefix}_EXTENSIONS OFF)")
        if target.output_prefix is not None:
            lines.append(f"set_target_properties({name} PROPERTIES PREFIX {_q(target.output_prefix)})")
        if target.output_extension:
            lines.append(f"set_target_properties({name} PROPERTIES SUFFIX {_q(target.output_extension)})")
        if target.kind == Kind.TEST:
            lines.append(f"add_test(NAME {name} COMMAND {name})")
        if target.overlays:
            notes.append(f"{name}: on_config/on_platform/on_toolchain overlays are not translated (only the base settings)")
        if target.platform_settings:
            notes.append(f"{name}: platform settings ({', '.join(sorted(target.platform_settings))}) are not translated")
        if target.rules:
            notes.append(f"{name}: generated files from rules ({', '.join(target.rules)}) are not translated: add custom commands by hand")
        if target.assets:
            notes.append(f"{name}: assets are not translated")
        lines.append("")
    if workspace.requires:
        notes.append("packages required with ws.requires(...) are not available to CMake: " + ", ".join(workspace.requires) + " (use find_package or FetchContent)")
    if workspace.hooks:
        notes.append("workspace hooks (ws.on) are not translated")
    header = ["# Generated by `charpente generate cmake` from " + json.dumps(workspace.name) + ". Regenerate after changing the .charpente file."]
    if notes:
        header += ["#", "# Not translated:"] + [f"#  - {n}" for n in notes]
    return "\n".join(header + [""] + lines).rstrip() + "\n"
