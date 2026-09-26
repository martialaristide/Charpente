"""HarmonyOS / OpenHarmony applications: native libraries, hvigor delegation, hdc deployment, the Node-API skeleton.

Charpente compiles the C/C++ (ohos.py). Everything else in a HarmonyOS app -- ArkTS/ArkUI, resources, the `.hap`
container, signing -- belongs to the ecosystem's own tools, so Charpente **delegates** to them, as the project rules
say: it puts the compiled `.so` files where hvigor expects them (`<project>/<module>/libs/<abi>/`), runs
`hvigorw assembleHap` and reports what came out. It never reimplements ArkCompiler, HAP signing or the store.

**Not verified here:** no DevEco Studio project, hvigor, hdc or device was available. The native libraries are built
and inspected with the real SDK; the hvigor/hdc command lines follow the tools' documentation and are tested through a
recording runner only.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .core import process
from .errors import ChError

ABI_DIRS = {"harmonyos-arm64": "arm64-v8a", "harmonyos-arm": "armeabi-v7a", "harmonyos-x64": "x86_64"}
PACKAGE_TYPES = ("hap", "har", "hsp")
_BUNDLE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
_KNOWN = {"project", "module", "package_type", "bundle_name", "product", "mode", "napi"}


@dataclass(frozen=True)
class HarmonySettings:
    project: str = "harmony"        # the DevEco/hvigor project folder, relative to the workspace
    module: str = "entry"           # the module that receives the native libraries
    package_type: str = "hap"       # hap (installable app), har (static library), hsp (shared library)
    bundle_name: str = ""           # needed to start the app after installing it
    product: str = "default"
    mode: str = "debug"             # hvigor build mode: debug | release


def settings_from(target_name: str, raw: Mapping[str, Any]) -> HarmonySettings:
    unknown = sorted(set(raw) - _KNOWN)
    if unknown:
        raise ChError("CH8006", platform="harmony",
                      detail=f"unknown setting(s) {', '.join(unknown)} (known: {', '.join(sorted(_KNOWN))})")
    package_type = str(raw.get("package_type", "hap"))
    if package_type not in PACKAGE_TYPES:
        raise ChError("CH8006", platform="harmony", detail=f"package_type must be one of {', '.join(PACKAGE_TYPES)}")
    bundle = str(raw.get("bundle_name", ""))
    if bundle and not _BUNDLE.match(bundle):
        raise ChError("CH8006", platform="harmony", detail=f"{bundle!r} is not a valid bundle name")
    mode = str(raw.get("mode", "debug"))
    if mode not in ("debug", "release"):
        raise ChError("CH8006", platform="harmony", detail="mode must be debug or release")
    for key in ("project", "module", "product"):
        value = str(raw.get(key, {"project": "harmony", "module": "entry", "product": "default"}[key]))
        if not value or value.startswith(("/", "\\")) or ".." in Path(value).parts or not re.fullmatch(r"[\w./-]+", value):
            raise ChError("CH8006", platform="harmony", detail=f"{key} {value!r} must be a plain relative name")
    return HarmonySettings(project=str(raw.get("project", "harmony")), module=str(raw.get("module", "entry")),
                           package_type=package_type, bundle_name=bundle, product=str(raw.get("product", "default")),
                           mode=mode)


def place_libraries(root: Path, settings: HarmonySettings, libraries: Mapping[str, Path]) -> List[Path]:
    """Copy `{platform: libX.so}` into `<project>/<module>/libs/<abi>/`; returns the destinations."""
    placed: List[Path] = []
    project = root / settings.project
    if not (project / "build-profile.json5").is_file():
        raise ChError("CH8006", platform="harmony",
                      detail=f"{settings.project!r} is not a hvigor project (no build-profile.json5): create it with "
                             "DevEco Studio or `charpente init --template app-harmonyos`")
    for platform, library in sorted(libraries.items()):
        destination = project / settings.module / "libs" / ABI_DIRS[platform] / library.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(library, destination)
        placed.append(destination)
    return placed


def hvigor_argv(settings: HarmonySettings, hvigorw: str) -> List[str]:
    task = {"hap": "assembleHap", "har": "assembleHar", "hsp": "assembleHsp"}[settings.package_type]
    return [hvigorw, "--mode", "module", "-p", f"module={settings.module}@{settings.product}",
            "-p", f"product={settings.product}", "-p", f"buildMode={settings.mode}", task, "--no-daemon"]


def find_hvigorw(project: Path, which: Callable[[str], Optional[str]] = shutil.which) -> str:
    for name in ("hvigorw.bat", "hvigorw"):
        if (project / name).is_file():
            return str(project / name)
    found = which("hvigorw")
    if found:
        return found
    raise ChError("CH8007", what="hvigorw (the project's wrapper or DevEco's command line tools)",
                  hint="open the project once in DevEco Studio, or install the HarmonyOS command line tools "
                       "(they need a Huawei developer account; Charpente cannot fetch them)")


def find_outputs(project: Path, settings: HarmonySettings) -> List[Path]:
    """The package files hvigor left behind."""
    extension = f"*.{settings.package_type}"
    return sorted((project / settings.module / "build").glob(f"**/outputs/**/{extension}"))


def build_package(root: Path, settings: HarmonySettings, libraries: Mapping[str, Path], *,
                  runner: Optional[process.Runner] = None, which: Callable[[str], Optional[str]] = shutil.which,
                  say: Callable[[str], None] = lambda text: None) -> List[Path]:
    """Place the libraries, run hvigor, return the produced packages. Raises CH8008 if hvigor fails."""
    project = root / settings.project
    place_libraries(root, settings, libraries)
    hvigorw = find_hvigorw(project, which)
    say(f"Running hvigor ({settings.package_type})")
    result = process.run(hvigor_argv(settings, hvigorw), cwd=str(project), runner=runner, timeout=1800)
    if result.returncode != 0:
        raise ChError("CH8008", step="hvigor", detail=result.output.strip()[-1500:] or "(no output)")
    outputs = find_outputs(project, settings)
    if not outputs:
        raise ChError("CH8008", step="hvigor", detail=f"it succeeded but left no .{settings.package_type} under "
                                                       f"{settings.module}/build")
    return outputs


# ------------------------------------------------------------------ hdc
def hdc_path(env_sdk: Optional[Path] = None, which: Callable[[str], Optional[str]] = shutil.which) -> str:
    found = which("hdc")
    if not found and env_sdk is not None:
        for candidate in sorted(env_sdk.glob("*/toolchains/hdc*"), reverse=True) + sorted(env_sdk.glob("toolchains/hdc*")):
            if candidate.is_file():
                found = str(candidate)
                break
    if not found:
        raise ChError("CH8007", what="hdc (the HarmonyOS device connector)",
                      hint="it ships with the SDK's `toolchains` component; add it to PATH")
    return found


def parse_targets(text: str) -> List[str]:
    """`hdc list targets` -> device serials (`[Empty]` means none)."""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("[")]


def install_and_launch(hdc: str, package: Path, bundle_name: str, ability: str = "EntryAbility", *,
                       serial: Optional[str] = None, launch: bool = True, runner: Optional[process.Runner] = None,
                       say: Callable[[str], None] = lambda text: None) -> None:
    base = [hdc] + (["-t", serial] if serial else [])
    say(f"Installing {package.name}")
    result = process.run([*base, "install", "-r", str(package)], runner=runner, timeout=600)
    if result.returncode != 0 or "fail" in result.output.lower():
        raise ChError("CH8008", step="hdc install", detail=result.output.strip()[-800:])
    if launch:
        if not bundle_name:
            raise ChError("CH8006", platform="harmony", detail='set p.harmony(bundle_name="com.example.app") to start the app')
        say(f"Starting {bundle_name}")
        result = process.run([*base, "shell", "aa", "start", "-a", ability, "-b", bundle_name], runner=runner, timeout=120)
        if result.returncode != 0 or "error" in result.output.lower():
            raise ChError("CH8008", step="starting the app", detail=result.output.strip()[-800:])


def hilog_argv(hdc: str, serial: Optional[str] = None) -> List[str]:
    return [hdc, *(["-t", serial] if serial else []), "shell", "hilog"]


# ------------------------------------------------------------------ Node-API (ArkTS <-> C++) skeleton
def napi_files(module: str = "entry", functions: Sequence[str] = ("add",)) -> Dict[str, str]:
    """The three files of a minimal Node-API module: the C++ registration, the ArkTS declaration and the package
    manifest. HarmonyOS's Node-API derives from Node.js's without being fully compatible: test on the real system."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", module):
        raise ChError("CH8006", platform="harmony", detail=f"module name {module!r} must be lower-case letters, digits, _")
    for name in functions:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ChError("CH8006", platform="harmony", detail=f"function name {name!r} is not an identifier")
    impls = "\n".join(f'''static napi_value {name}(napi_env env, napi_callback_info info) {{
    size_t argc = 2;
    napi_value args[2] = {{nullptr, nullptr}};
    napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
    double a = 0, b = 0;
    napi_get_value_double(env, args[0], &a);
    napi_get_value_double(env, args[1], &b);
    napi_value sum;
    napi_create_double(env, a + b, &sum);
    return sum;
}}
''' for name in functions)
    descriptors = ",\n        ".join(f'{{"{name}", nullptr, {name}, nullptr, nullptr, nullptr, napi_default, nullptr}}'
                                     for name in functions)
    cpp = f'''#include "napi/native_api.h"

{impls}
EXTERN_C_START
static napi_value Init(napi_env env, napi_value exports) {{
    napi_property_descriptor desc[] = {{
        {descriptors}
    }};
    napi_define_properties(env, exports, sizeof(desc) / sizeof(desc[0]), desc);
    return exports;
}}
EXTERN_C_END

static napi_module demoModule = {{
    .nm_version = 1,
    .nm_flags = 0,
    .nm_filename = nullptr,
    .nm_register_func = Init,
    .nm_modname = "{module}",
    .nm_priv = nullptr,
    .reserved = {{0}},
}};

extern "C" __attribute__((constructor)) void RegisterModule(void) {{
    napi_module_register(&demoModule);
}}
'''
    declarations = "\n".join(f"export const {name}: (a: number, b: number) => number;" for name in functions)
    package = (f'{{\n  "name": "lib{module}.so",\n  "types": "./Index.d.ts",\n  "version": "1.0.0",\n'
               f'  "description": "Native module built by Charpente"\n}}\n')
    return {f"src/{module}_napi.cpp": cpp, f"types/lib{module}/Index.d.ts": declarations + "\n",
            f"types/lib{module}/oh-package.json5": package}
