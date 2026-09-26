"""`charpente doctor` -- what this machine can do, and what is missing for what you want to build."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

from .. import _version, cross, platforms, toolchain_install, toolchains
from ..core import download
from ..dsl.trust import config_dir
from ..errors import ChError
from ..platform import host_os


def gather() -> Dict[str, Any]:
    """Everything `doctor` reports, as data (also what `--json` prints)."""
    report: Dict[str, Any] = {"charpente": _version.__version__, "python": sys.version.split()[0],
                              "config_dir": str(config_dir()), "offline": download.offline()}
    try:
        host = platforms.host()
        report["host"] = host.name
    except ChError as exc:
        host = None
        report["host"] = f"unsupported ({exc.params.get('os', '?')})"
    detected = toolchains.detect(host_os()) if host is not None else []
    report["toolchains"] = [{"name": t.name, "compiler": t.cxx_compiler, "cross_only": t.cross_only,
                             "targets": list(t.targets)} for t in detected]
    notes: List[str] = []
    for tc in detected:
        if tc.name == "ohos":
            from .. import ohos

            root = dict(tc.extras).get("native_root")
            if root:
                info = ohos.sdk_info(Path(root))
                drift = ohos.alignment(Path(root))
                notes.append(f"OpenHarmony native SDK {info.get('version', '?')} (API {info.get('api', '?')})"
                             + (f": Charpente's defaults differ from the SDK's toolchain file on {', '.join(drift)}" if drift else ""))
    report["notes"] = notes
    tools = {name: shutil.which(name) for name in ("git", "node", "wasmtime", "cmake", "ninja", "clangd", "clang-format", "clang-tidy")}
    report["tools"] = {name: path for name, path in tools.items()}
    from .. import debug as debug_mod

    report["debuggers"] = [f"{d['name']} {d['version']}".strip() for d in debug_mod.find_debuggers()]
    report["installed_by_charpente"] = [f"{n}@{v}" for n, v, _ in toolchain_install.installed()]
    buildable: List[str] = []
    missing: Dict[str, str] = {}
    for platform in platforms.all_platforms():
        if host is not None and platform.name == host.name:
            (buildable if detected else []).append(platform.name)
            if not detected:
                missing[platform.name] = "no C/C++ compiler found"
        elif any(cross.can_target(t, platform) for t in detected):
            buildable.append(platform.name)
        elif platform.needs:
            missing[platform.name] = platform.needs
    report["buildable"] = buildable
    report["missing"] = missing
    return report


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente doctor", description="Check this machine's build environment.")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parsed = parser.parse_args(args)
    report = gather()
    if parsed.json:
        print(json.dumps(report, indent=1))
        return 0 if report["buildable"] else 1

    print(f"Charpente {report['charpente']}, Python {report['python']}, host {report['host']}")
    print(f"Config directory: {report['config_dir']}" + ("   (OFFLINE mode: no downloads)" if report["offline"] else ""))
    print("\nCompilers:")
    if not report["toolchains"]:
        print("  none found. Install GCC/Clang/MSVC, or `charpente toolchain install zig` (works everywhere).")
    for tc in report["toolchains"]:
        extra = "  (cross-only)" if tc["cross_only"] else ""
        print(f"  {tc['name']:<12} {tc['compiler']}{extra}")
    print("\nOther tools:")
    for name, path in report["tools"].items():
        print(f"  {name:<12} {path or 'not found'}")
    print(f"  {'debugger':<12} {', '.join(report['debuggers']) or 'not found (gdb 14+ or lldb-dap: `charpente debug --list`)'}")
    print(f"\nCan build now ({len(report['buildable'])}): {', '.join(report['buildable']) or 'nothing'}")
    if report["missing"]:
        print("\nNot available yet:")
        for name, why in report["missing"].items():
            print(f"  {name:<20} {why}")
    return 0 if report["buildable"] else 1
