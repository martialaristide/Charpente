"""Data model for a Charpente workspace: plain dataclasses with no behavior
of their own. The DSL (api.py) populates them; the builders (builders/)
read them. Keeping them dumb makes both sides independently testable."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core import globber
from ..errors import ChError, ChValueError
from ..safe_name import validate as _validate_name


class Kind(Enum):
    EXECUTABLE = "executable"
    STATIC_LIBRARY = "static_library"
    SHARED_LIBRARY = "shared_library"
    TEST = "test"
    # Added with DSL v2. Each is accepted by the DSL everywhere; a kind the
    # selected platform cannot build yet is refused when *planning* (CH3007),
    # never silently built as something else.
    HEADER_ONLY = "header_only"      # no build actions: only propagates includes/defines
    PLUGIN = "plugin"                # a shared library meant to be loaded at run time
    SHADERS = "shaders"
    XR_APP = "xr_app"
    MOBILE_APP = "mobile_app"
    WEB_APP = "web_app"
    FIRMWARE = "firmware"


#: Kinds that produce a linkable library other targets can `uses()`.
LIBRARY_KINDS = (Kind.STATIC_LIBRARY, Kind.SHARED_LIBRARY, Kind.PLUGIN)


class Language(Enum):
    C = "c"
    CPP = "cpp"


#: Kinds that become an application bundle on mobile/XR platforms (APK, .app).
APP_KINDS = (Kind.MOBILE_APP, Kind.XR_APP)


class OS(Enum):
    """The operating system a build *targets* (usually the host's; different when cross-compiling)."""

    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    ANDROID = "android"
    IOS = "ios"
    VISIONOS = "visionos"
    OHOS = "ohos"
    WASM = "wasm"            # WebAssembly in a browser/Node, via Emscripten
    WASI = "wasi"            # WebAssembly outside a browser
    FREEBSD = "freebsd"
    OPENBSD = "openbsd"
    NETBSD = "netbsd"
    BAREMETAL = "baremetal"


@dataclass
class Overlay:
    """Settings that apply only when a condition holds, recorded by
    `t.on_config("Release")`, `t.on_platform("linux-*")`, `t.on_toolchain("msvc")`.

    `when` maps a dimension (`config`, `platform`, `toolchain`) to an fnmatch
    pattern; an overlay applies when every listed dimension matches."""

    when: Dict[str, str] = field(default_factory=dict)
    source_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    include_dirs: List[str] = field(default_factory=list)
    define_macros: List[str] = field(default_factory=list)
    link_libraries: List[str] = field(default_factory=list)
    extra_compile_flags: List[str] = field(default_factory=list)
    extra_link_flags: List[str] = field(default_factory=list)
    public_include_dirs: List[str] = field(default_factory=list)
    public_define_macros: List[str] = field(default_factory=list)
    public_compile_flags: List[str] = field(default_factory=list)
    public_link_libraries: List[str] = field(default_factory=list)
    uses: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    platform_settings: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class Rule:
    """A user-defined build step: a command with declared inputs and outputs, so
    the engine can cache it and re-run it exactly when something changes."""

    name: str
    argv: List[str] = field(default_factory=list)
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    description: str = ""


@dataclass(frozen=True)
class OptionSpec:
    """A workspace option declared with `ws.option(...)` (shown by Studio,
    overridable with `--opt name=value`)."""

    name: str
    default: Any
    help: str = ""
    choices: Optional[Tuple[Any, ...]] = None
    kind: str = "string"          # bool | string | enum | int


@dataclass
class Target:
    """One buildable unit (an executable, a library, a test binary)."""

    name: str
    kind: Kind = Kind.EXECUTABLE
    language: Language = Language.CPP
    standard: str = "c++17"

    source_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    include_dirs: List[str] = field(default_factory=list)
    define_macros: List[str] = field(default_factory=list)
    link_libraries: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)

    extra_compile_flags: List[str] = field(default_factory=list)
    extra_link_flags: List[str] = field(default_factory=list)
    #: Overrides for the output file name of libraries and plugins (Python extensions want `name.pyd`/`name.so`,
    #: no `lib` prefix): None keeps the platform's convention.
    output_prefix: Optional[str] = None
    output_extension: Optional[str] = None

    # ---- DSL v2 (all optional; a v0.1.0 target never sets any of them) -----
    #: `uses("dep")`: build order + link + the dependency's public settings, in one line.
    uses: List[str] = field(default_factory=list)
    #: `uses` that are also re-exported to whatever uses *this* target (CMake's PUBLIC).
    uses_public: List[str] = field(default_factory=list)
    #: Settings that propagate to dependents (public) or only to dependents (interface).
    public_include_dirs: List[str] = field(default_factory=list)
    interface_include_dirs: List[str] = field(default_factory=list)
    public_define_macros: List[str] = field(default_factory=list)
    interface_define_macros: List[str] = field(default_factory=list)
    public_compile_flags: List[str] = field(default_factory=list)
    public_link_libraries: List[str] = field(default_factory=list)
    #: Names of `Rule`s whose outputs this target consumes (generated sources/headers).
    rules: List[str] = field(default_factory=list)
    #: Conditional settings: `on_config` / `on_platform` / `on_toolchain` blocks.
    overlays: List["Overlay"] = field(default_factory=list)
    #: Restrict the target to these platform patterns (None = every platform).
    platforms: Optional[List[str]] = None
    #: Platform-specific settings recorded by `p.android(...)`, `p.harmony(...)`... (used by P4).
    platform_settings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    assets: List[str] = field(default_factory=list)
    shader_target: str = ""
    #: True for targets materialised from `ws.requires(...)` packages.
    external: bool = False

    # Filled in by the loader once the workspace's own directory is known;
    # never set directly from a .charpente file.
    location: Optional[Path] = None

    def __post_init__(self) -> None:
        # Validated here, at construction, rather than later wherever a
        # builder happens to concatenate `name` into an output path: a
        # target name that can't safely become a filename component should
        # never exist in the first place, not just be caught before it's
        # dangerous.
        _validate_name(self.name, "Target name")

    def dependencies(self) -> List[str]:
        """Every target this one may depend on in *any* configuration or platform:
        `depends_on`, `uses`, and those of every overlay. A superset on purpose:
        for ordering and closures, building slightly more is safe, too little is not."""
        deps: List[str] = [*self.depends_on, *self.uses, *self.uses_public]
        for overlay in self.overlays:
            deps += [*overlay.depends_on, *overlay.uses]
        return list(dict.fromkeys(deps))

    def source_files(self) -> List[str]:
        """Like `resolved_sources()` but as plain, sorted path strings: what hot
        paths (the no-op fast path) use, since building tens of thousands of
        `Path` objects is measurably slower than the comparison they feed."""
        if self.location is None:
            raise ChValueError("CH1017", name=self.name)
        root = str(self.location)
        matched = globber.expand(root, self.source_patterns)
        if self.exclude_patterns:
            matched -= globber.expand(root, self.exclude_patterns)
        return sorted(matched)

    def resolved_sources(self) -> List[Path]:
        """Expand source_patterns/exclude_patterns against `location` into a
        sorted, deduplicated list of real files. Pure and side-effect free
        so it can be unit tested without touching a real build."""
        if self.location is None:
            raise ChValueError("CH1017", name=self.name)
        return [Path(p) for p in self.source_files()]


@dataclass
class Workspace:
    """The root of a loaded .charpente file: one or more Targets, plus
    workspace-wide settings that apply to all of them."""

    name: str
    configurations: List[str] = field(default_factory=lambda: ["Debug", "Release"])
    targets: Dict[str, Target] = field(default_factory=dict)

    # Absolute directory containing the root .charpente file. Set by the
    # loader, not by DSL code.
    location: Optional[Path] = None

    # (Event, function) pairs registered with `@ws.on(Event.X)`. Callables, so
    # excluded from repr/compare: they never take part in build keys.
    hooks: List[Any] = field(default_factory=list, repr=False, compare=False)
    version: str = ""

    # ---- DSL v2 ------------------------------------------------------------
    rules: Dict[str, Rule] = field(default_factory=dict)
    options: Dict[str, OptionSpec] = field(default_factory=dict)
    option_values: Dict[str, Any] = field(default_factory=dict)
    #: platform names this workspace targets (`ws.platforms([...])`); empty = the host only.
    platforms: List[str] = field(default_factory=list)
    #: `ws.requires("fmt@^10", ...)`: external packages, resolved by `charpente pkg install`.
    requires: List[str] = field(default_factory=list)
    #: `ws.kit("kit-core")`: kit name -> the target names `uses("kit-core")` expands to.
    kits: Dict[str, List[str]] = field(default_factory=dict)
    #: `ws.package_settings("freertos", include_dirs=[...])`: per-workspace tuning of a package's own build
    #: (include dirs, defines, flags, extra `uses`); package name -> setting -> values.
    package_settings: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_name(self.name, "Workspace name")

    @property
    def root(self) -> Path:
        """The workspace directory. `location` is Optional only because the
        DSL attaches it after construction; anything that builds paths goes
        through here so a missing location is a clear error, not a
        `None / "build"` TypeError."""
        if self.location is None:
            raise ChError("CH9002", detail=f"workspace {self.name!r} has no location")
        return self.location

    def add_target(self, target: Target) -> None:
        if target.name in self.targets:
            raise ChValueError("CH1016", name=target.name, workspace=self.name)
        self.targets[target.name] = target

    def build_order(self) -> List[str]:
        """Topologically sorted target names (dependencies before
        dependents). Raises ValueError on an unknown dependency or a cycle,
        naming the target so the error is actionable.

        `path` is the chain of targets currently being visited, root first,
        NOT including `name` itself -- so `path + [name]` is always the
        full chain down to (and including) the node under inspection.
        """
        order: List[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str, path: List[str]) -> None:
            if name in visited:
                return
            if name not in self.targets:
                offender = path[-1] if path else name
                raise ChValueError("CH3005", target=offender, dependency=name)
            if name in visiting:
                cycle = " -> ".join(path + [name])
                raise ChValueError("CH3004", cycle=cycle)
            visiting.add(name)
            for dep in self.targets[name].dependencies():
                visit(dep, path + [name])
            visiting.discard(name)
            visited.add(name)
            order.append(name)

        for target_name in self.targets:
            visit(target_name, [])
        return order
