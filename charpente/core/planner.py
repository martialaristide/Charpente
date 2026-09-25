"""Analysis: turn a Workspace (+ toolchain, configuration) into actions.

Pure with respect to processes: it reads the filesystem to expand source
globs, and computes commands, but launches nothing. Everything the engine
needs to decide freshness and to cache is described in the `Action`s.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Set

from .. import flags
from ..dsl.model import OS, Kind, Target, Workspace
from ..errors import ChError
from ..toolchains import Toolchain
from .actions import DEP_GNU, DEP_MSVC, KIND_ARCHIVE, KIND_COMPILE, KIND_LINK, Action
from .graph import ActionGraph

_LIBRARY_KINDS = (Kind.STATIC_LIBRARY, Kind.SHARED_LIBRARY)

#: Makes MSVC print `Note: including file:` in English whatever the Windows
#: display language is (the marker text is localised otherwise).
_MSVC_ENV = (("VSLANG", "1033"),)


@dataclass
class Plan:
    graph: ActionGraph
    #: action ids per target, in a stable order (compile actions first, then the final one)
    target_actions: Dict[str, List[str]] = field(default_factory=dict)
    #: final output file of each planned target
    outputs: Dict[str, Path] = field(default_factory=dict)
    #: targets that cannot be planned (e.g. no source files), with the reason
    errors: Dict[str, ChError] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)   # workspace build order (dependencies first)
    config: str = "Debug"


def build_dir(workspace: Workspace, config: str, target: Target) -> Path:
    return workspace.root / "build" / config / target.name


def _object_path(root: Path, obj_dir: Path, source: Path, object_ext: str) -> Path:
    """`obj/<source dir relative to the workspace>/<file name>.o`.

    The whole file name (extension included) is kept so `util.c` and
    `util.cpp`, or two `util.cpp` in different folders, never share an object.
    """
    try:
        rel = source.resolve().relative_to(root.resolve())
        parts = list(PurePosixPath(rel.as_posix()).parts)
    except ValueError:
        # Outside the workspace: keep it apart under a stable per-directory folder.
        tag = hashlib.sha1(str(source.parent).encode("utf-8")).hexdigest()[:8]
        parts = ["_external", tag, source.name]
    parts = [p if p != ".." else "__" for p in parts]
    return obj_dir.joinpath(*parts[:-1], parts[-1] + object_ext)


def _action_id(kind: str, target: str, source: Optional[Path], root: Path) -> str:
    if source is None:
        return f"{kind}:{target}"
    try:
        shown = source.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        shown = source.as_posix()
    return f"{kind}:{target}:{shown}"


def plan_workspace(
    workspace: Workspace,
    toolchain: Toolchain,
    target_os: OS,
    *,
    config: str = "Debug",
    only: Optional[Iterable[str]] = None,
) -> Plan:
    """Actions for every target (or just `only`) in dependency order.

    Raises the workspace's own errors for an unknown dependency or a cycle
    (via `Workspace.build_order`). A target that cannot be planned (no source
    files) is recorded in `Plan.errors` and contributes no actions."""
    order = workspace.build_order()
    if only is not None:
        wanted = set(only)
        order = [name for name in order if name in wanted]

    debug = config.lower() == "debug"
    fam = flags.family(toolchain)
    object_ext = ".obj" if fam == "msvc" else ".o"
    root = workspace.root

    actions: List[Action] = []
    plan_targets: Dict[str, List[str]] = {}
    outputs: Dict[str, Path] = {}
    errors: Dict[str, ChError] = {}
    final_action: Dict[str, str] = {}

    failed: Set[str] = set()
    for name in order:
        target = workspace.targets[name]
        blocked_by = failed.intersection(target.depends_on)
        if blocked_by:
            errors[name] = ChError("CH3006", targets=sorted(blocked_by))
            failed.add(name)
            continue
        sources = target.resolved_sources()
        if not sources:
            failed.add(name)
            errors[name] = ChError("CH3001", target=target.name)
            continue

        out_dir = build_dir(workspace, config, target)
        obj_dir = out_dir / "obj"
        ids: List[str] = []
        objects: List[Path] = []
        used: Set[Path] = set()

        for source in sources:
            obj = _object_path(root, obj_dir, source, object_ext)
            if obj in used:  # cannot happen for distinct sources, but never build silently wrong
                raise ChError("CH3010", path=str(obj), first="?", second=str(source))
            used.add(obj)
            objects.append(obj)
            depfile = None if fam == "msvc" else obj.with_name(obj.name + ".d")
            argv = flags.compile_args(toolchain, target, source, obj, debug=debug, depfile=depfile)
            compiler = argv[0]
            action = Action(
                id=_action_id(KIND_COMPILE, target.name, source, root),
                kind=KIND_COMPILE,
                target=target.name,
                argv=tuple(argv),
                outputs=(obj,),
                inputs=(source,),
                env=_MSVC_ENV if fam == "msvc" else (),
                tool=compiler,
                depfile=depfile,
                dep_format=DEP_MSVC if fam == "msvc" else DEP_GNU,
                description=f"Compiling {source.name}",
                source=source,
                cwd=root,
            )
            actions.append(action)
            ids.append(action.id)

        dependency_dirs: List[Path] = []
        extra_inputs: List[Path] = []
        after: List[str] = []
        for dep_name in target.depends_on:
            dep = workspace.targets.get(dep_name)
            if dep is None:
                continue
            dependency_dirs.append(build_dir(workspace, config, dep))
            if dep_name in final_action:
                after.append(final_action[dep_name])
        for lib in target.link_libraries:
            dep = workspace.targets.get(lib)
            if dep is not None and dep.kind in _LIBRARY_KINDS:
                extra_inputs.append(build_dir(workspace, config, dep) / flags.output_filename(dep, target_os, toolchain))

        output_path = out_dir / flags.output_filename(target, target_os, toolchain)
        argv = flags.link_args(toolchain, target, objects, output_path, library_dirs=dependency_dirs)
        is_archive = target.kind == Kind.STATIC_LIBRARY
        kind = KIND_ARCHIVE if is_archive else KIND_LINK
        tool = toolchain.archiver if is_archive else toolchain.linker
        final = Action(
            id=_action_id(kind, target.name, None, root),
            kind=kind,
            target=target.name,
            argv=tuple(argv),
            outputs=(output_path,),
            inputs=tuple(objects) + tuple(extra_inputs),
            after=tuple(after),
            env=_MSVC_ENV if fam == "msvc" else (),
            tool=argv[0] if argv else tool,
            description=f"{'Archiving' if is_archive else 'Linking'} {output_path.name}",
            cwd=root,
        )
        actions.append(final)
        ids.append(final.id)
        final_action[name] = final.id
        plan_targets[name] = ids
        outputs[name] = output_path

    return Plan(graph=ActionGraph(actions), target_actions=plan_targets, outputs=outputs,
                errors=errors, order=order, config=config)
