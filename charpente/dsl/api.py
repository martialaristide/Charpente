"""The public DSL surface: what a .charpente file actually calls.

Design note: a .charpente file is executed as plain Python (see loader.py),
so `Workspace`/`Target`/`Rule` are ordinary context managers built around a bit
of module-level state -- there is no parser, no grammar, no magic beyond
`__enter__`/`__exit__` pushing and popping "the current thing" so nested
calls know what they're configuring.

Everything added in DSL v2 is additive: a v0.1.0 file uses none of it and
behaves exactly as before.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Union

from ..errors import ChError, ChRuntimeError, ChValueError
from ..hooks import Event, notify
from ..semver import Constraint
from . import model as _model
from .model import OS, Kind, Language

__all__ = ["Workspace", "Target", "Rule", "Kind", "Language", "OS", "Event", "notify", "current_workspace"]

_current_workspace: Optional[_model.Workspace] = None
_current_target: Optional[_model.Target] = None
_pending_location: Optional[Path] = None
_last_workspace: Optional[_model.Workspace] = None
_option_overrides: Dict[str, str] = {}
_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")

Strings = Union[str, Iterable[str]]


def _as_list(value: Strings) -> List[str]:
    """`"a"` and `["a", "b"]` both work. (A bare string used to be iterated
    character by character -- a silent trap, now a single item.)"""
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _flatten(args: "tuple[Strings, ...]") -> List[str]:
    out: List[str] = []
    for arg in args:
        out.extend(_as_list(arg))
    return out


def current_workspace() -> Optional[_model.Workspace]:
    """The Workspace currently open (inside its `with` block), or None. For
    the DSL's own use (e.g. a helper function that needs "the workspace
    being built right now")."""
    return _current_workspace


def last_loaded_workspace() -> Optional[_model.Workspace]:
    """The most recently *completed* `with Workspace(...)` block, even
    after its `with` has exited -- this is what the loader reads once
    exec() of the whole file has finished."""
    return _last_workspace


def set_pending_location(directory: Optional[Path]) -> None:
    """Called by the loader, before exec()'ing a .charpente file, with that
    file's parent directory -- the only way `Workspace()` can know where it
    lives, since the DSL file itself never states its own path."""
    global _pending_location
    _pending_location = directory


def set_option_overrides(overrides: Optional[Dict[str, str]]) -> None:
    """`--opt name=value` values for `ws.option(...)` to pick up (loader only)."""
    global _option_overrides
    _option_overrides = dict(overrides or {})


def _reset_state() -> None:
    """Clear module-level state between file loads (tests, and a loader
    that runs more than once in the same process)."""
    global _current_workspace, _current_target, _last_workspace
    _current_workspace = None
    _current_target = None
    _last_workspace = None


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def parse_option_value(spec: _model.OptionSpec, raw: str) -> Any:
    """Convert a command-line string to the option's type (CH1021 if it cannot)."""
    text = str(raw).strip()
    if spec.kind == "bool":
        if text.lower() in _TRUE:
            return True
        if text.lower() in _FALSE:
            return False
    elif spec.kind == "int":
        try:
            return int(text)
        except ValueError:
            pass
    elif spec.kind == "enum":
        if spec.choices and text in [str(c) for c in spec.choices]:
            return text
    else:
        return text
    expected = {"bool": "true or false", "int": "an integer",
                "enum": "one of " + ", ".join(str(c) for c in (spec.choices or ()))}[spec.kind]
    raise ChValueError("CH1021", name=spec.name, value=raw, expected=expected)


class Workspace:
    """`with Workspace("Name") as ws: ...` -- opens a new workspace and
    makes it the target of any `Target(...)` block declared inside."""

    def __init__(self, name: str, version: str = ""):
        self._model = _model.Workspace(name=name, location=_pending_location)
        self._model.version = version

    def __enter__(self) -> "Workspace":
        global _current_workspace
        if _current_workspace is not None:
            raise ChRuntimeError("CH1015", name=self._model.name, outer=_current_workspace.name)
        _current_workspace = self._model
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        global _current_workspace, _last_workspace
        if exc_type is None:
            _last_workspace = self._model
        _current_workspace = None

    def configurations(self, names: Iterable[str]) -> "Workspace":
        self._model.configurations = list(names)
        return self

    def platforms(self, names: Strings) -> "Workspace":
        """Platforms this workspace is meant to build for (`"windows-x64"`, `"android-arm64"`...)."""
        self._model.platforms = _as_list(names)
        return self

    def requires(self, *specs: Strings) -> "Workspace":
        """External packages: `ws.requires("fmt@^10", "glm")`. They are resolved and fetched by
        `charpente pkg install` (never silently during a build), pinned in `charpente.lock`."""
        for spec in _flatten(specs):
            name, _, constraint = spec.partition("@")
            if not _PACKAGE_RE.match(name):
                raise ChValueError("CH1023", spec=spec)
            Constraint.parse(constraint or "*")                 # raises CH7002 if malformed
            if spec not in self._model.requires:
                self._model.requires.append(spec)
        return self

    def kit(self, *names: Strings) -> "Workspace":
        """`ws.kit("kit-core")`: require every package of the kit; `t.uses("kit-core")` then uses them all."""
        from ..pkg import kits as kits_mod

        for name in _flatten(names):
            where = self._model.location
            kit = kits_mod.get(name, where / ".charpente" / "kits" if where is not None else None)
            self.requires(*kit.requires)
            self._model.kits[kit.name] = list(kit.uses)
        return self

    def package_settings(self, package: str, *, include_dirs: Strings = (), defines: Strings = (),
                         compile_flags: Strings = (), uses: Strings = (), link_libraries: Strings = ()) -> "Workspace":
        """Tune how one package is built *in this workspace*: FreeRTOS needs your `FreeRTOSConfig.h` on its include
        path, an embedded package needs `tinylibc`, etc. Paths are relative to the workspace. The recipe (and the lock
        file) are untouched; only this workspace's build of the package changes."""
        if not _PACKAGE_RE.match(package):
            raise ChValueError("CH1023", spec=package)
        table = self._model.package_settings.setdefault(package, {})
        for key, values in (("include_dirs", include_dirs), ("defines", defines), ("compile_flags", compile_flags),
                            ("uses", uses), ("link_libraries", link_libraries)):
            table.setdefault(key, []).extend(x for x in _flatten((values,)) if x not in table.get(key, []))
        return self

    def option(self, name: str, default: Any = None, *, help: str = "",
               choices: Optional[Iterable[Any]] = None) -> Any:
        """Declare a typed option and return its value (the default, or the one given with
        `--opt name=value`). Studio lists declared options and can change them."""
        if choices is not None:
            kind, choice_tuple = "enum", tuple(choices)
            if default is None and choice_tuple:
                default = choice_tuple[0]
        elif isinstance(default, bool):
            kind, choice_tuple = "bool", None
        elif isinstance(default, int):
            kind, choice_tuple = "int", None
        else:
            kind, choice_tuple = "string", None
        spec = _model.OptionSpec(name=name, default=default, help=help, choices=choice_tuple, kind=kind)
        self._model.options[name] = spec
        value = parse_option_value(spec, _option_overrides[name]) if name in _option_overrides else default
        self._model.option_values[name] = value
        return value

    def budget(self, *, build_time: Optional[Any] = None, total_size: Optional[Any] = None) -> "Workspace":
        """Limits for the whole build, checked after `charpente build`: `ws.budget(build_time="90s", total_size="40MB")`."""
        from ..budgets import parse_workspace_budget

        self._model.budgets.update(parse_workspace_budget({"build_time": build_time, "total_size": total_size}))
        return self

    def on(self, event: Event) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator: run a function when an event happens (see `charpente.hooks`)."""
        if not isinstance(event, Event):
            raise TypeError(f"ws.on() takes an Event (e.g. Event.BUILD_FINISHED), not {event!r}")

        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            self._model.hooks.append((event, function))
            return function

        return register

    @property
    def model(self) -> _model.Workspace:
        return self._model


class Rule:
    """`with Rule("gen") as r: r.command([...]); r.inputs([...]); r.outputs([...])`

    A build step of your own. Declaring its inputs and outputs lets Charpente cache
    it and run it exactly when an input changes. A target consumes it with
    `t.rules(["gen"])`: the outputs become inputs of the target's compilations,
    and outputs that are C/C++ files are compiled too. The command is a list of
    arguments (never a shell string) run from the workspace folder.
    """

    def __init__(self, name: str):
        if _current_workspace is None:
            raise ChRuntimeError("CH1014", name=name)
        from ..safe_name import validate

        validate(name, "Rule name")
        self._workspace = _current_workspace
        self._model = _model.Rule(name=name)

    def __enter__(self) -> "Rule":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            if not self._model.argv or not self._model.outputs:
                raise ChValueError("CH1024", name=self._model.name)
            self._workspace.rules[self._model.name] = self._model

    def command(self, argv: Iterable[str]) -> "Rule":
        if isinstance(argv, (str, bytes)):
            raise ChError("CH9001", command=str(argv))
        self._model.argv = [str(a) for a in argv]
        return self

    def inputs(self, paths: Strings) -> "Rule":
        self._model.inputs.extend(_as_list(paths))
        return self

    def outputs(self, paths: Strings) -> "Rule":
        self._model.outputs.extend(_as_list(paths))
        return self

    def description(self, text: str) -> "Rule":
        self._model.description = text
        return self


_PLATFORM_KEYS = ("android", "harmony", "ios", "wasm", "web", "xr", "embedded", "quest")


def _expand_kits(names: List[str]) -> List[str]:
    """`uses("kit-core")` means every target of the kit declared with `ws.kit("kit-core")`."""
    workspace = _current_workspace
    if workspace is None or not workspace.kits:
        return names
    out: List[str] = []
    for name in names:
        for item in workspace.kits.get(name, [name]):
            if item not in out:
                out.append(item)
    return out


class _Conditional:
    """`with t.on_platform("android-*") as p: p.defines([...])`: settings that
    only apply when the (config, platform, toolchain) condition holds."""

    def __init__(self, target: _model.Target, when: Dict[str, str]):
        self._target = target
        self._overlay = _model.Overlay(when=dict(when))

    def __enter__(self) -> "_Conditional":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            self._target.overlays.append(self._overlay)

    def sources(self, patterns: Strings) -> "_Conditional":
        self._overlay.source_patterns.extend(_as_list(patterns))
        return self

    def exclude(self, patterns: Strings) -> "_Conditional":
        self._overlay.exclude_patterns.extend(_as_list(patterns))
        return self

    def include_dirs(self, dirs: Strings) -> "_Conditional":
        self._overlay.include_dirs.extend(_as_list(dirs))
        return self

    def public_include_dirs(self, dirs: Strings) -> "_Conditional":
        self._overlay.public_include_dirs.extend(_as_list(dirs))
        return self

    def defines(self, macros: Strings) -> "_Conditional":
        self._overlay.define_macros.extend(_as_list(macros))
        return self

    def public_defines(self, macros: Strings) -> "_Conditional":
        self._overlay.public_define_macros.extend(_as_list(macros))
        return self

    def links(self, libraries: Strings) -> "_Conditional":
        self._overlay.link_libraries.extend(_as_list(libraries))
        return self

    def compile_flags(self, flags: Strings) -> "_Conditional":
        self._overlay.extra_compile_flags.extend(_as_list(flags))
        return self

    def link_flags(self, flags: Strings) -> "_Conditional":
        self._overlay.extra_link_flags.extend(_as_list(flags))
        return self

    def uses(self, *names: Strings) -> "_Conditional":
        self._overlay.uses.extend(_expand_kits(_flatten(names)))
        return self

    def depends_on(self, targets: Strings) -> "_Conditional":
        self._overlay.depends_on.extend(_as_list(targets))
        return self

    def platform_settings(self, name: str, /, **settings: Any) -> "_Conditional":
        self._overlay.platform_settings.setdefault(name, {}).update(settings)
        return self

    def __getattr__(self, name: str) -> Callable[..., "_Conditional"]:
        # p.android(...), p.harmony(...), p.ios(...): recorded as platform settings, read by
        # the platform modules (Android, HarmonyOS...).
        if name in _PLATFORM_KEYS:
            return lambda **settings: self.platform_settings(name, **settings)
        raise AttributeError(f"{name!r} is not something a condition block can set "
                             f"(platform settings: {', '.join(_PLATFORM_KEYS)})")


class Target:
    """`with Target("name") as t: t.kind(...)...` -- declares one buildable
    unit inside the currently-open Workspace."""

    def __init__(self, name: str):
        if _current_workspace is None:
            raise ChRuntimeError("CH1014", name=name)
        self._model = _model.Target(name=name, location=_current_workspace.location)

    def __enter__(self) -> "Target":
        global _current_target
        _current_target = self._model
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        global _current_target
        if _current_workspace is not None:
            _current_workspace.add_target(self._model)
        _current_target = None

    # ------------------------------------------------------------ v0.1.0 API
    def kind(self, value: Kind) -> "Target":
        self._model.kind = value
        return self

    def language(self, value: Language) -> "Target":
        self._model.language = value
        return self

    def standard(self, value: str) -> "Target":
        self._model.standard = value
        return self

    def sources(self, patterns: Strings) -> "Target":
        self._model.source_patterns.extend(_as_list(patterns))
        return self

    def exclude(self, patterns: Strings) -> "Target":
        self._model.exclude_patterns.extend(_as_list(patterns))
        return self

    def include_dirs(self, dirs: Strings) -> "Target":
        self._model.include_dirs.extend(_as_list(dirs))
        return self

    def defines(self, macros: Strings) -> "Target":
        self._model.define_macros.extend(_as_list(macros))
        return self

    def links(self, libraries: Strings) -> "Target":
        self._model.link_libraries.extend(_as_list(libraries))
        return self

    def depends_on(self, targets: Strings) -> "Target":
        """Build order only. (Prefer `uses`, which also links and shares includes.)"""
        self._model.depends_on.extend(_as_list(targets))
        return self

    def compile_flags(self, flags: Strings) -> "Target":
        self._model.extra_compile_flags.extend(_as_list(flags))
        return self

    def link_flags(self, flags: Strings) -> "Target":
        self._model.extra_link_flags.extend(_as_list(flags))
        return self

    def budget(self, *, size: Optional[Any] = None) -> "Target":
        """The output of this target must stay under `size` ("2MB", or bytes); checked after `charpente build`."""
        from ..budgets import parse_target_budget

        self._model.budgets.update(parse_target_budget({"size": size}))
        return self

    def output_prefix(self, prefix: str) -> "Target":
        """The file-name prefix of a library/plugin (`""` for a Python extension instead of `lib`)."""
        self._model.output_prefix = prefix
        return self

    def output_extension(self, extension: str) -> "Target":
        """The file extension of a library/plugin (`".pyd"` for a Python extension on Windows)."""
        if extension and not extension.startswith("."):
            raise ChValueError("CH1011", field="output_extension")
        self._model.output_extension = extension
        return self

    # ------------------------------------------------------------------ v2
    def uses(self, *names: Strings) -> "Target":
        """Build order, linking and the used targets' public settings, in one line:
        `t.uses("engine", "glm")`. Names are workspace targets or `ws.requires` packages."""
        self._model.uses.extend(_expand_kits(_flatten(names)))
        return self

    def uses_public(self, *names: Strings) -> "Target":
        """Like `uses`, and whatever uses *this* target inherits them too (CMake's PUBLIC)."""
        self._model.uses_public.extend(_expand_kits(_flatten(names)))
        return self

    def public_include_dirs(self, dirs: Strings) -> "Target":
        """Used by this target *and* propagated to every target that uses it."""
        self._model.public_include_dirs.extend(_as_list(dirs))
        return self

    def private_include_dirs(self, dirs: Strings) -> "Target":
        return self.include_dirs(dirs)

    def interface_include_dirs(self, dirs: Strings) -> "Target":
        """Propagated to users, but not used by this target itself."""
        self._model.interface_include_dirs.extend(_as_list(dirs))
        return self

    def public_defines(self, macros: Strings) -> "Target":
        self._model.public_define_macros.extend(_as_list(macros))
        return self

    def private_defines(self, macros: Strings) -> "Target":
        return self.defines(macros)

    def interface_defines(self, macros: Strings) -> "Target":
        self._model.interface_define_macros.extend(_as_list(macros))
        return self

    def public_compile_flags(self, flags: Strings) -> "Target":
        self._model.public_compile_flags.extend(_as_list(flags))
        return self

    def public_links(self, libraries: Strings) -> "Target":
        """System libraries every user of this target must also link (e.g. `ws2_32`)."""
        self._model.public_link_libraries.extend(_as_list(libraries))
        return self

    def rules(self, names: Strings) -> "Target":
        """Consume `Rule`s: their outputs feed this target's compilations."""
        self._model.rules.extend(_as_list(names))
        return self

    def platforms(self, patterns: Strings) -> "Target":
        """Only build this target for matching platforms (`"harmonyos-*"`)."""
        self._model.platforms = _as_list(patterns)
        return self

    def assets(self, patterns: Strings) -> "Target":
        self._model.assets.extend(_as_list(patterns))
        return self

    def shader_target(self, value: str) -> "Target":
        self._model.shader_target = value
        return self

    def platform_settings(self, name: str, /, **settings: Any) -> "Target":
        self._model.platform_settings.setdefault(name, {}).update(settings)
        return self

    def when(self, *, config: Optional[str] = None, platform: Optional[str] = None,
             toolchain: Optional[str] = None) -> _Conditional:
        """`with t.when(config="Release", platform="linux-*") as c: ...`"""
        cond = {k: v for k, v in (("config", config), ("platform", platform), ("toolchain", toolchain)) if v}
        return _Conditional(self._model, cond)

    def on_config(self, pattern: str) -> _Conditional:
        return _Conditional(self._model, {"config": pattern})

    def on_platform(self, pattern: str) -> _Conditional:
        return _Conditional(self._model, {"platform": pattern})

    def on_toolchain(self, pattern: str) -> _Conditional:
        return _Conditional(self._model, {"toolchain": pattern})
