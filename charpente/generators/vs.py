"""Visual Studio: a solution and one *Makefile project* per target, whose Build/Rebuild/Clean commands run `charpente`.

A Makefile project gives Visual Studio what it needs for IntelliSense (sources, headers, include directories, preprocessor definitions) and for F7 (build) and
F5 (start the program), while Charpente stays the build system. This is generated from the documented `.sln`/`.vcxproj` formats and has **not been opened in
Visual Studio or built with MSBuild** (neither was available where it was written): only well-formedness and the structure are tested. Xcode projects are not generated.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Dict, List
from xml.sax.saxutils import escape, quoteattr

from ..dsl.model import Kind, Target, Workspace

NAMESPACE = uuid.UUID("6f0f1b5e-6f5f-4b8f-9c53-3f3b6a0f7c11")
CPP_TYPE_GUID = "{8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942}"
HEADER_SUFFIXES = (".h", ".hh", ".hpp", ".hxx", ".inl")


def guid(name: str) -> str:
    """A stable project GUID: the same target always gets the same one (a regenerated solution keeps its history)."""
    return "{" + str(uuid.uuid5(NAMESPACE, name)).upper() + "}"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix().replace("/", "\\")
    except ValueError:
        return str(path).replace("/", "\\")


def _headers(target: Target, root: Path) -> List[str]:
    found: "set[Path]" = set()
    base = target.location or root
    for folder in [*(base / d for d in [*target.public_include_dirs, *target.include_dirs]), *(s.parent for s in target.resolved_sources())]:
        if folder.is_dir():
            found.update(p for p in folder.glob("*") if p.suffix.lower() in HEADER_SUFFIXES)
    return sorted(_rel(p, root) for p in found)


def vcxproj(workspace: Workspace, target: Target, charpente: str = "charpente") -> str:
    root = workspace.root
    include_dirs = [_rel((target.location or root) / d, root) for d in [*target.public_include_dirs, *target.include_dirs]]
    defines = [*target.define_macros, *target.public_define_macros]
    cmd = f'{charpente} build --config $(Configuration) --target {target.name}'
    run = f'{charpente} run --config $(Configuration) --target {target.name}'
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<Project DefaultTargets="Build" ToolsVersion="Current" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">',
             '  <ItemGroup Label="ProjectConfigurations">']
    for config in ("Debug", "Release"):
        lines += [f'    <ProjectConfiguration Include="{config}|x64">', f"      <Configuration>{config}</Configuration>", "      <Platform>x64</Platform>", "    </ProjectConfiguration>"]
    lines += ["  </ItemGroup>", '  <PropertyGroup Label="Globals">', f"    <ProjectGuid>{guid(target.name)}</ProjectGuid>", f"    <RootNamespace>{escape(target.name)}</RootNamespace>",
              "    <Keyword>MakeFileProj</Keyword>", "  </PropertyGroup>", '  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props" />']
    for config in ("Debug", "Release"):
        lines += [f"  <PropertyGroup Condition=\"'$(Configuration)|$(Platform)'=='{config}|x64'\" Label=\"Configuration\">", "    <ConfigurationType>Makefile</ConfigurationType>",
                  "    <PlatformToolset>v143</PlatformToolset>", "  </PropertyGroup>"]
    lines += ['  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props" />', "  <PropertyGroup>",
              f"    <NMakeBuildCommandLine>{escape(cmd)}</NMakeBuildCommandLine>",
              f"    <NMakeReBuildCommandLine>{escape(charpente + ' clean && ' + cmd)}</NMakeReBuildCommandLine>",
              f"    <NMakeCleanCommandLine>{escape(charpente + ' clean')}</NMakeCleanCommandLine>",
              f"    <NMakeIncludeSearchPath>{escape(';'.join(include_dirs))}</NMakeIncludeSearchPath>",
              f"    <NMakePreprocessorDefinitions>{escape(';'.join(defines + ['$(NMakePreprocessorDefinitions)']))}</NMakePreprocessorDefinitions>"]
    if target.kind in (Kind.EXECUTABLE, Kind.TEST):
        lines += [f"    <LocalDebuggerCommand>{escape(charpente)}</LocalDebuggerCommand>", f"    <LocalDebuggerCommandArguments>{escape(run.split(' ', 1)[1])}</LocalDebuggerCommandArguments>"]
    lines += ["  </PropertyGroup>", "  <ItemGroup>"]
    for source in sorted(target.resolved_sources()):
        lines.append(f"    <ClCompile Include={quoteattr(_rel(source, root))} />")
    lines += ["  </ItemGroup>", "  <ItemGroup>"]
    for header in _headers(target, root):
        lines.append(f"    <ClInclude Include={quoteattr(header)} />")
    lines += ["  </ItemGroup>", '  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />', "</Project>"]
    return "\n".join(lines) + "\n"


def solution(workspace: Workspace, names: List[str]) -> str:
    lines = ["", "Microsoft Visual Studio Solution File, Format Version 12.00", "# Visual Studio Version 17"]
    for name in names:
        lines.append(f'Project("{CPP_TYPE_GUID}") = "{name}", "{name}.vcxproj", "{guid(name)}"')
        lines.append("EndProject")
    lines += ["Global", "\tGlobalSection(SolutionConfigurationPlatforms) = preSolution", "\t\tDebug|x64 = Debug|x64", "\t\tRelease|x64 = Release|x64", "\tEndGlobalSection",
              "\tGlobalSection(ProjectConfigurationPlatforms) = postSolution"]
    for name in names:
        for config in ("Debug", "Release"):
            lines += [f"\t\t{guid(name)}.{config}|x64.ActiveCfg = {config}|x64", f"\t\t{guid(name)}.{config}|x64.Build.0 = {config}|x64"]
    lines += ["\tEndGlobalSection", "EndGlobal"]
    return "\r\n".join(lines) + "\r\n"


def render(workspace: Workspace, charpente: str = "charpente") -> Dict[str, str]:
    """{file name: text}: `<workspace>.sln` and one `<target>.vcxproj` per own target that has sources."""
    files: Dict[str, str] = {}
    names: List[str] = []
    for name in workspace.build_order():
        target = workspace.targets[name]
        if target.external or target.kind == Kind.HEADER_ONLY or not target.source_patterns:
            continue
        names.append(name)
        files[f"{name}.vcxproj"] = vcxproj(workspace, target, charpente)
    files[f"{workspace.name}.sln"] = solution(workspace, names)
    return files
