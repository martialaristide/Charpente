"""Analysis: turn a Workspace (+ toolchain, configuration) into actions.

Pure with respect to processes: it reads the filesystem to expand source
globs, and computes commands, but launches nothing. Everything the engine
needs to decide freshness and to cache is described in the `Action`s.

The DSL's conveniences (`uses`, public/interface settings, overlays for a
configuration/platform/toolchain) are resolved first (`dsl.resolve`), so the
rest of this module -- and `flags.py` -- only ever sees plain targets.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .. import android, cross, embedded, flags
from ..dsl import resolve
from ..dsl.model import APP_KINDS, LIBRARY_KINDS, OS, Kind, Language, Target, Workspace
from ..errors import ChError
from ..toolchains import Toolchain
from .actions import DEP_GNU, DEP_MSVC, KIND_ARCHIVE, KIND_COMPILE, KIND_CUSTOM, KIND_LINK, Action
from .graph import ActionGraph

#: Kinds this engine builds today. The others (XR_APP, MOBILE_APP...) are
#: accepted by the DSL and refused here, with CH3007, until their platform lands.
_BUILDABLE = (Kind.EXECUTABLE, Kind.TEST, Kind.STATIC_LIBRARY, Kind.SHARED_LIBRARY, Kind.PLUGIN)
_SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".c++", ".s", ".m", ".mm")

#: Makes MSVC print `Note: including file:` in English whatever the Windows
#: display language is (the marker text is localised otherwise).
_MSVC_ENV = (("VSLANG", "1033"),)


@dataclass
class Plan:
    graph: ActionGraph
    #: action ids per target, in a stable order (rule actions, compiles, then the final one)
    target_actions: Dict[str, List[str]] = field(default_factory=dict)
    #: final output file of each planned target
    outputs: Dict[str, Path] = field(default_factory=dict)
    #: targets that cannot be planned (e.g. no source files), with the reason
    errors: Dict[str, ChError] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)   # dependencies first, `only`-filtered
    config: str = "Debug"


def build_dir(workspace: Workspace, variant: str, target: Target) -> Path:
    return workspace.root / "build" / variant / target.name


def context_for(config: str, toolchain: Toolchain, platform_name: Optional[str] = None,
                options: Optional[Dict[str, object]] = None) -> resolve.BuildContext:
    return resolve.BuildContext(config=config, platform=platform_name or toolchain.target or resolve.host_platform(),
                                toolchain=toolchain.name,
                                options=tuple(sorted((k, str(v).lower() if isinstance(v, bool) else str(v))
                                                     for k, v in (options or {}).items())))


def effective_scope(workspace: Workspace, toolchain: Toolchain, config: str,
                    only: Optional[Iterable[str]] = None,
                    platform_name: Optional[str] = None) -> Tuple[List[str], Dict[str, Target]]:
    """(build order restricted to the scope, effective target of everything in the
    scope's closure). Raises the usual CH3004/CH3005 for cycles and unknown targets."""
    ctx = context_for(config, toolchain, platform_name, workspace.option_values)
    wanted: Set[str] = set()
    if only is None:
        # Everything you wrote, plus the packages it actually uses -- not every package that is installed.
        for n in workspace.build_order():
            if not workspace.targets[n].external:
                wanted |= resolve.closure(workspace, n)
    else:
        wanted = set(only)
    names = [n for n in workspace.build_order() if n in wanted]
    needed: Set[str] = set()
    for n in names:
        needed |= resolve.closure(workspace, n)
    available = [n for n in workspace.build_order()
                 if n in needed and resolve.target_available(workspace.targets[n], ctx)]
    effective = resolve.effective_targets(workspace, available, ctx)
    order = [n for n in resolve.topo_order(effective) if n in wanted]
    return order, effective


def _object_path(root: Path, obj_dir: Path, source: Path, object_ext: str) -> Path:
    """`obj/<source dir relative to the workspace>/<file name>.o`.

    The whole file name (extension included) is kept so `util.c` and
    `util.cpp`, or two `util.cpp` in different folders, never share an object.
    """
    try:
        # `source` and `root` are both already absolute (the loader resolves the
        # workspace directory once); avoiding Path.resolve() here matters: it is
        # a syscall per call, and this runs once per source file.
        rel = Path(os.path.normpath(source)).relative_to(root)
        parts = list(PurePosixPath(rel.as_posix()).parts)
    except ValueError:
        # Outside the workspace: keep it apart under a stable per-directory folder.
        tag = hashlib.sha1(str(source.parent).encode("utf-8")).hexdigest()[:8]
        parts = ["_external", tag, source.name]
    parts = [p if p != ".." else "__" for p in parts]
    return obj_dir.joinpath(*parts[:-1], parts[-1] + object_ext)


def _action_id(kind: str, target: str, source: Optional[Path], root: Path, prefix: str = "") -> str:
    """`compile:app:src/main.cpp`; a cross build prefixes its platform (`linux-arm64/compile:...`) so
    each platform keeps its own record and switching between them rebuilds nothing."""
    if source is None:
        return f"{prefix}{kind}:{target}"
    try:
        shown = Path(os.path.normpath(source)).relative_to(root).as_posix()
    except ValueError:
        shown = source.as_posix()
    return f"{prefix}{kind}:{target}:{shown}"


def plan_workspace(
    workspace: Workspace,
    toolchain: Toolchain,
    target_os: OS,
    *,
    config: str = "Debug",
    only: Optional[Iterable[str]] = None,
    sources: Optional[Dict[str, List[str]]] = None,
    scope: Optional[Tuple[List[str], Dict[str, Target]]] = None,
) -> Plan:
    """Actions for every target (or just `only`) in dependency order.

    A target that cannot be planned (no source files, a kind this engine cannot
    build yet) is recorded in `Plan.errors` and contributes no actions; so do
    the targets that depend on it."""
    order, effective = scope if scope is not None else effective_scope(workspace, toolchain, config, only)

    debug = config.lower() == "debug"
    variant = cross.variant_name(config, toolchain)
    id_prefix = cross.id_prefix(toolchain)
    fam = flags.family(toolchain)
    object_ext = ".obj" if fam == "msvc" else ".o"
    root = workspace.root

    actions: List[Action] = []
    plan_targets: Dict[str, List[str]] = {}
    outputs: Dict[str, Path] = {}
    errors: Dict[str, ChError] = {}
    final_action: Dict[str, str] = {}
    rule_actions: Dict[str, Action] = {}

    def rule_action(rule_name: str, owner: str) -> Action:
        """One action per rule, owned by the first target that names it."""
        if rule_name not in rule_actions:
            rule = workspace.rules.get(rule_name)
            if rule is None:
                raise ChError("CH3015", target=owner, rule=rule_name)
            action = Action(
                id=f"rule:{rule_name}", kind=KIND_CUSTOM, target=owner, argv=tuple(rule.argv),
                outputs=tuple(root / p for p in rule.outputs), inputs=tuple(root / p for p in rule.inputs),
                tool=rule.argv[0], description=rule.description or f"Running rule {rule_name}", cwd=root,
            )
            rule_actions[rule_name] = action
            actions.append(action)
            plan_targets.setdefault(owner, []).append(action.id)
        return rule_actions[rule_name]

    failed: Set[str] = set()
    for name in order:
        target = effective[name]
        if target.kind == Kind.HEADER_ONLY:
            continue                                    # contributes settings to its users, builds nothing
        if target.kind not in _BUILDABLE and not (target.kind in APP_KINDS
                                                  and target_os in (OS.ANDROID, OS.IOS, OS.VISIONOS, OS.OHOS)) \
                and not (target.kind == Kind.FIRMWARE and target_os == OS.BAREMETAL):
            errors[name] = ChError("CH3007", kind=target.kind.value)
            failed.add(name)
            continue
        blocked_by = failed.intersection(target.depends_on)
        if blocked_by:
            errors[name] = ChError("CH3006", targets=sorted(blocked_by))
            failed.add(name)
            continue

        my_rules = [rule_action(r, name) for r in target.rules]
        generated = [p for a in my_rules for p in a.outputs]
        target_sources = ([Path(s) for s in sources[name]] if sources is not None and name in sources
                          else target.resolved_sources())
        seen_sources = {str(p) for p in target_sources}
        for path in generated:
            if path.suffix.lower() in _SOURCE_SUFFIXES and str(path) not in seen_sources:
                target_sources.append(path)
                seen_sources.add(str(path))
        if not target_sources:
            failed.add(name)
            errors[name] = ChError("CH3001", target=target.name)
            continue

        c_sources: Set[Path] = set()
        if target_os == OS.ANDROID and target.platform_settings.get("android", {}).get("native_app_glue"):
            glue_dir = android.native_app_glue_dir(toolchain)
            if glue_dir is None:
                failed.add(name)
                errors[name] = ChError("CH8007", what="the NDK's native_app_glue sources",
                                       hint="build with the Android NDK (`charpente platforms` shows what is missing)")
                continue
            glue = glue_dir / "android_native_app_glue.c"
            target_sources.append(glue)
            c_sources.add(glue)
            target = replace(target, include_dirs=[*target.include_dirs, str(glue_dir)],
                             link_libraries=[*target.link_libraries, "android", "log"],
                             extra_link_flags=[*target.extra_link_flags, "-u", "ANativeActivity_onCreate"])

        out_dir = build_dir(workspace, variant, target)
        obj_dir = out_dir / "obj"
        ids: List[str] = plan_targets.setdefault(name, [])
        objects: List[Path] = []
        used: Set[Path] = set()

        for source in target_sources:
            obj = _object_path(root, obj_dir, source, object_ext)
            if obj in used:  # cannot happen for distinct sources, but never build silently wrong
                raise ChError("CH3010", path=str(obj), first="?", second=str(source))
            used.add(obj)
            objects.append(obj)
            depfile = None if fam == "msvc" else obj.with_name(obj.name + ".d")
            argv = flags.compile_args(toolchain, target, source, obj, debug=debug, depfile=depfile,
                                      language=Language.C if source in c_sources else None)
            compiler = argv[0]
            action = Action(
                id=_action_id(KIND_COMPILE, target.name, source, root, id_prefix),
                kind=KIND_COMPILE,
                target=target.name,
                argv=tuple(argv),
                outputs=(obj,),
                inputs=(source, *[p for p in generated if p != source]),
                env=_MSVC_ENV if fam == "msvc" else toolchain.env,
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
            dep = effective.get(dep_name) or workspace.targets.get(dep_name)
            if dep is None:
                continue
            dependency_dirs.append(build_dir(workspace, variant, dep))
            if dep_name in final_action:
                after.append(final_action[dep_name])
        for lib in target.link_libraries:
            dep = effective.get(lib) or workspace.targets.get(lib)
            if dep is not None and dep.kind in LIBRARY_KINDS and dep.kind != Kind.PLUGIN:
                extra_inputs.append(build_dir(workspace, variant, dep) / flags.output_filename(dep, target_os, toolchain))

        output_path = out_dir / flags.output_filename(target, target_os, toolchain)
        argv = flags.link_args(toolchain, target, objects, output_path, library_dirs=dependency_dirs, root=root)
        is_archive = target.kind == Kind.STATIC_LIBRARY
        kind = KIND_ARCHIVE if is_archive else KIND_LINK
        tool = toolchain.archiver if is_archive else toolchain.linker
        final = Action(
            id=_action_id(kind, target.name, None, root, id_prefix),
            kind=kind,
            target=target.name,
            argv=tuple(argv),
            outputs=(output_path, *flags.side_outputs(target, target_os, output_path, toolchain)),
            inputs=tuple(objects) + tuple(extra_inputs),
            after=tuple(after),
            env=_MSVC_ENV if fam == "msvc" else toolchain.env,
            tool=argv[0] if argv else tool,
            description=f"{'Archiving' if is_archive else 'Linking'} {output_path.name}",
            cwd=root,
        )
        actions.append(final)
        ids.append(final.id)
        final_action[name] = final.id
        outputs[name] = output_path
        if target.kind == Kind.FIRMWARE and target_os == OS.BAREMETAL:
            for image in ("bin", "hex"):                # the flashable images, produced (and cached) like anything else
                image_path = output_path.with_suffix(f".{image}")
                image_argv = embedded.objcopy_argv(toolchain, image, output_path, image_path)
                actions.append(Action(
                    id=_action_id(KIND_CUSTOM, target.name, None, root, id_prefix + f"{image}:"),
                    kind=KIND_CUSTOM, target=target.name, argv=tuple(image_argv), outputs=(image_path,),
                    inputs=(output_path,), after=(final.id,), tool=image_argv[0],
                    description=f"Creating {image_path.name}", cwd=root))
                ids.append(actions[-1].id)
            fw = embedded.settings_from(target.name, target.platform_settings.get("embedded", {}))
            if fw.uf2_base:
                uf2_path = output_path.with_suffix(".uf2")
                uf2_cmd = embedded.uf2_argv(output_path.with_suffix(".bin"), uf2_path, fw)
                actions.append(Action(
                    id=_action_id(KIND_CUSTOM, target.name, None, root, id_prefix + "uf2:"),
                    kind=KIND_CUSTOM, target=target.name, argv=tuple(uf2_cmd), outputs=(uf2_path,),
                    inputs=(output_path.with_suffix(".bin"),), after=(actions[-1].id,), tool=uf2_cmd[0],
                    description=f"Creating {uf2_path.name}", cwd=root))
                ids.append(actions[-1].id)

    return Plan(graph=ActionGraph(actions), target_actions=plan_targets, outputs=outputs,
                errors=errors, order=order, config=config)
