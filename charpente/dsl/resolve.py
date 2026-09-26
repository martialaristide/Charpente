"""From what the DSL recorded to what a build of one (config, platform,
toolchain) actually needs. Pure functions over the model.

* `on_config` / `on_platform` / `on_toolchain` overlays are applied;
* `uses(...)` is expanded: build order, linking (including the transitive
  libraries of static libraries), and the *public* / *interface* include
  directories, defines and flags of the used targets, re-exported through
  `uses_public`;
* header-only targets contribute settings but no build actions.

The result is an ordinary `Target`, so `flags.py` and the rest of the engine
stay exactly as they were.
"""
from __future__ import annotations

import fnmatch
import platform as _platform
from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Mapping, Set, Tuple

from ..errors import ChValueError
from .model import LIBRARY_KINDS, Kind, Overlay, Target, Workspace

_ARCHES = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64", "x86": "x86", "i386": "x86",
           "i686": "x86", "armv7l": "arm", "riscv64": "riscv64"}


@dataclass(frozen=True)
class BuildContext:
    config: str = "Debug"
    platform: str = ""
    toolchain: str = ""
    #: workspace option values (as strings), for `option:<name>` conditions in charpente.toml
    options: Tuple[Tuple[str, str], ...] = ()


def host_platform() -> str:
    """'windows-x64', 'linux-arm64', 'macos-arm64'..."""
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(_platform.system(), _platform.system().lower())
    machine = _platform.machine().lower()
    return f"{system}-{_ARCHES.get(machine, machine or 'unknown')}"


def _match(pattern: str, value: str) -> bool:
    return fnmatch.fnmatchcase(value.lower(), pattern.lower())


def overlay_applies(overlay: Overlay, ctx: BuildContext) -> bool:
    values = {"config": ctx.config, "platform": ctx.platform, "toolchain": ctx.toolchain}
    values.update({f"option:{k}": v for k, v in ctx.options})
    return all(_match(pattern, values.get(dim, "")) for dim, pattern in overlay.when.items())


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def apply_overlays(target: Target, ctx: BuildContext) -> Target:
    """A copy of `target` with the overlays matching `ctx` folded in."""
    active = [o for o in target.overlays if overlay_applies(o, ctx)]
    if not active:
        return replace(target, overlays=[])
    merged = replace(
        target,
        source_patterns=list(target.source_patterns), exclude_patterns=list(target.exclude_patterns),
        include_dirs=list(target.include_dirs), define_macros=list(target.define_macros),
        link_libraries=list(target.link_libraries), depends_on=list(target.depends_on),
        extra_compile_flags=list(target.extra_compile_flags), extra_link_flags=list(target.extra_link_flags),
        public_include_dirs=list(target.public_include_dirs), public_define_macros=list(target.public_define_macros),
        public_compile_flags=list(target.public_compile_flags),
        public_link_libraries=list(target.public_link_libraries),
        uses=list(target.uses), platform_settings={k: dict(v) for k, v in target.platform_settings.items()},
        overlays=[],
    )
    for o in active:
        merged.source_patterns += o.source_patterns
        merged.exclude_patterns += o.exclude_patterns
        merged.include_dirs += o.include_dirs
        merged.define_macros += o.define_macros
        merged.link_libraries += o.link_libraries
        merged.depends_on += o.depends_on
        merged.extra_compile_flags += o.extra_compile_flags
        merged.extra_link_flags += o.extra_link_flags
        merged.public_include_dirs += o.public_include_dirs
        merged.public_define_macros += o.public_define_macros
        merged.public_compile_flags += o.public_compile_flags
        merged.public_link_libraries += o.public_link_libraries
        merged.uses += o.uses
        for key, values in o.platform_settings.items():
            merged.platform_settings.setdefault(key, {}).update(values)
    return merged


@dataclass
class _Exports:
    include_dirs: List[str]
    defines: List[str]
    flags: List[str]
    links: List[str]


def target_available(target: Target, ctx: BuildContext) -> bool:
    """False if the target is restricted (`t.platforms([...])`) to other platforms."""
    if target.platforms is None or not ctx.platform:
        return True
    return any(_match(p, ctx.platform) for p in target.platforms)


def effective_targets(workspace: Workspace, names: Iterable[str], ctx: BuildContext) -> Dict[str, Target]:
    """The effective Target of each of `names` (and of everything they use)."""
    based: Dict[str, Target] = {}

    def base(name: str) -> Target:
        if name not in based:
            target = workspace.targets.get(name)
            if target is None:
                raise ChValueError("CH3005", target="?", dependency=name)
            based[name] = apply_overlays(target, ctx)
        return based[name]

    exports_memo: Dict[str, _Exports] = {}

    def exports(name: str, path: Tuple[str, ...] = ()) -> _Exports:
        if name in exports_memo:
            return exports_memo[name]
        if name in path:
            raise ChValueError("CH3004", cycle=" -> ".join((*path, name)))
        t = base(name)
        inc = list(t.public_include_dirs) + list(t.interface_include_dirs)
        dfn = list(t.public_define_macros) + list(t.interface_define_macros)
        flg = list(t.public_compile_flags)
        lnk = list(t.public_link_libraries)
        for reexported in t.uses_public:
            sub = exports(reexported, (*path, name))
            inc += sub.include_dirs
            dfn += sub.defines
            flg += sub.flags
            lnk += sub.links
        result = _Exports(_dedupe(inc), _dedupe(dfn), _dedupe(flg), _dedupe(lnk))
        exports_memo[name] = result
        return result

    def library_closure(name: str, path: Tuple[str, ...] = ()) -> List[str]:
        """Dependency-first order of `name`'s used targets (all kinds), excluding `name`."""
        out: List[str] = []
        seen: Set[str] = set()

        def visit(current: str, trail: Tuple[str, ...]) -> None:
            if current in trail:
                raise ChValueError("CH3004", cycle=" -> ".join((*trail, current)))
            t = base(current)
            for dep in _dedupe([*t.uses, *t.uses_public]):
                if dep in seen:
                    continue
                visit(dep, (*trail, current))
                seen.add(dep)
                out.append(dep)

        visit(name, path)
        return out

    def build(name: str) -> Target:
        t = base(name)
        direct = _dedupe([*t.uses, *t.uses_public])
        for dep in direct:
            if dep not in workspace.targets:
                raise ChValueError("CH3005", target=name, dependency=dep)
            if not target_available(workspace.targets[dep], ctx):
                raise ChValueError("CH3014", target=name, dependency=dep, platform=ctx.platform)

        inc = list(t.include_dirs) + list(t.public_include_dirs)
        dfn = list(t.define_macros) + list(t.public_define_macros)
        flg = list(t.extra_compile_flags) + list(t.public_compile_flags)
        sys_libs = list(t.link_libraries) + list(t.public_link_libraries)
        for dep in direct:
            e = exports(dep)
            inc += e.include_dirs
            dfn += e.defines
            flg += e.flags
            sys_libs += e.links

        closure = library_closure(name)                       # dependency-first
        target_libs: List[str] = []
        depends = list(t.depends_on)
        for dep in closure:
            d = base(dep)
            if d.kind == Kind.HEADER_ONLY:
                # nothing to build or link; but its own system libs travel along
                sys_libs += d.public_link_libraries
                continue
            depends.append(dep)
            if d.kind in LIBRARY_KINDS and d.kind != Kind.PLUGIN:
                target_libs.append(dep)
                if d.kind == Kind.STATIC_LIBRARY:
                    sys_libs += [lib for lib in d.link_libraries if lib not in workspace.targets]
                    sys_libs += d.public_link_libraries
        # dependents first: `-lA -lB` when A uses B
        ordered_targets = list(reversed(target_libs))
        legacy = [lib for lib in t.link_libraries if lib not in ordered_targets]
        links = _dedupe([*ordered_targets, *legacy, *[lib for lib in sys_libs if lib not in ordered_targets]])
        return replace(
            t,
            include_dirs=_dedupe(inc), define_macros=_dedupe(dfn), extra_compile_flags=_dedupe(flg),
            link_libraries=links, depends_on=_dedupe(depends),
        )

    out: Dict[str, Target] = {}
    for name in names:
        out[name] = build(name)
    return out


def topo_order(targets: Mapping[str, Target]) -> List[str]:
    """Dependency-first order over `depends_on` (which, for effective targets,
    already includes everything they `use`)."""
    order: List[str] = []
    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(name: str, path: List[str]) -> None:
        if name in visited:
            return
        if name not in targets:
            offender = path[-1] if path else name
            raise ChValueError("CH3005", target=offender, dependency=name)
        if name in visiting:
            raise ChValueError("CH3004", cycle=" -> ".join([*path, name]))
        visiting.add(name)
        for dep in targets[name].depends_on:
            visit(dep, [*path, name])
        visiting.discard(name)
        visited.add(name)
        order.append(name)

    for name in targets:
        visit(name, [])
    return order


def all_dependencies(target: Target) -> List[str]:
    """Every target this one may depend on in *any* context (a superset: overlays
    are included whatever their condition). Used for closures, where building a
    little more is safe and building too little is not."""
    deps: List[str] = [*target.depends_on, *target.uses, *target.uses_public]
    for overlay in target.overlays:
        deps += [*overlay.depends_on, *overlay.uses]
    return _dedupe(deps)


def closure(workspace: Workspace, name: str) -> Set[str]:
    """`name` plus everything it may depend on, transitively."""
    needed: Set[str] = set()
    stack = [name]
    while stack:
        current = stack.pop()
        if current in needed or current not in workspace.targets:
            continue
        needed.add(current)
        stack.extend(all_dependencies(workspace.targets[current]))
    return needed

