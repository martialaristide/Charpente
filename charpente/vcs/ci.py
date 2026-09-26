"""`charpente ci init`: a GitHub Actions workflow that runs the same quality gate as your machine.

The workflow is built as plain data and written with a small YAML emitter (no YAML dependency). It uses the least
privilege that works (`contents: read`), a matrix over operating systems and configurations, the Charpente cache, and
extra jobs for the platforms the project declares: Android (the runner's own NDK), HarmonyOS (the open-source
OpenHarmony SDK, checksum-verified), WebAssembly (Emscripten) and FreeBSD (in a virtual machine).

Third-party actions are pinned to a major version tag; for stricter supply-chain hygiene pin them to full commit SHAs
(see docs/security.md). Charpente output is turned into annotations automatically when it detects GitHub Actions.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

WORKFLOW_PATH = ".github/workflows/charpente.yml"
CHECKOUT = "actions/checkout@v4"
SETUP_PYTHON = "actions/setup-python@v5"
CACHE = "actions/cache@v4"

_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "y", "n", "~"}
_PLAIN = re.compile(r"^[A-Za-z0-9_./@$][A-Za-z0-9_ ./@:=,+\-${}()*'\"]*$")


def _scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    numeric = re.fullmatch(r"[-+]?[0-9][0-9_.eE+-]*", text) is not None
    if (not text or text.lower() in _RESERVED or numeric or not _PLAIN.match(text) or text.endswith(":")
            or ": " in text or " #" in text or text[0] in "'\"{}[]&*!|>%@`"):
        return json.dumps(text)                     # JSON strings are valid YAML double-quoted scalars
    return text


def _key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key) and key.lower() not in _RESERVED - {"on"} else json.dumps(key)


def dump(data: Any, indent: int = 0) -> str:
    """A minimal YAML emitter for dicts, lists and scalars (multi-line strings become `|` blocks)."""
    pad = "  " * indent
    lines: List[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{pad}{_key(key)}:")
                lines.append(dump(value, indent + 1 if isinstance(value, dict) else indent + 1))
            elif isinstance(value, str) and "\n" in value:
                lines.append(f"{pad}{_key(key)}: |")
                lines += [f"{pad}  {line}" if line else "" for line in value.rstrip("\n").split("\n")]
            elif isinstance(value, (dict, list)):
                lines.append(f"{pad}{_key(key)}: {'{}' if isinstance(value, dict) else '[]'}")
            else:
                lines.append(f"{pad}{_key(key)}: {_scalar(value)}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item:
                inner = dump(item, indent + 1).split("\n")
                first = inner[0].lstrip()
                lines.append(f"{pad}- {first}")
                lines += inner[1:]
            elif isinstance(item, str) and "\n" in item:
                lines.append(f"{pad}- |")
                lines += [f"{pad}  {line}" if line else "" for line in item.rstrip("\n").split("\n")]
            else:
                lines.append(f"{pad}- {_scalar(item)}")
    else:
        lines.append(f"{pad}{_scalar(data)}")
    return "\n".join(lines)


def _step(name: str, *, uses: Optional[str] = None, run: Optional[str] = None, with_: Optional[Dict[str, Any]] = None,
          env: Optional[Dict[str, str]] = None, if_: Optional[str] = None, shell: Optional[str] = None) -> Dict[str, Any]:
    step: Dict[str, Any] = {"name": name}
    if if_:
        step["if"] = if_
    if uses:
        step["uses"] = uses
    if run:
        step["run"] = run
    if shell:
        step["shell"] = shell
    if with_:
        step["with"] = with_
    if env:
        step["env"] = env
    return step


def _setup(install: str) -> List[Dict[str, Any]]:
    return [
        _step("Check out", uses=CHECKOUT, with_={"fetch-depth": 0}),
        _step("Set up Python", uses=SETUP_PYTHON, with_={"python-version": "3.12"}),
        _step("Cache Charpente", uses=CACHE, with_={
            "path": "~/.charpente/cache\n~/.charpente/toolchains\nbuild/.charpente",
            "key": "charpente-${{ runner.os }}-${{ hashFiles('**/*.charpente', 'charpente.toml', 'charpente.lock') }}",
            "restore-keys": "charpente-${{ runner.os }}-"}),
        _step("Install Charpente", run=install),
    ]


def workflow(*, platforms: Sequence[str] = (), install: str = "python -m pip install charpente",
             configs: Sequence[str] = ("Debug", "Release"), oses: Sequence[str] = ("ubuntu-latest", "windows-latest", "macos-latest"),
             level: str = "standard", branch: str = "main") -> Dict[str, Any]:
    """The workflow as data. `platforms` are the project's declared target platforms (`linux-arm64`, `android-arm64`...)."""
    jobs: Dict[str, Any] = {
        "gate": {
            "name": "gate (${{ matrix.os }}, ${{ matrix.config }})",
            "runs-on": "${{ matrix.os }}",
            "strategy": {"fail-fast": False, "matrix": {"os": list(oses), "config": list(configs)}},
            "steps": [*_setup(install),
                      _step(f"Quality gate ({level})", run=f"charpente check --level {level}"),
                      _step("Build", run="charpente build --config ${{ matrix.config }}"),
                      _step("Test", run="charpente test --config ${{ matrix.config }}")],
        },
    }
    wants = set(platforms)
    if any(p.startswith("android") for p in wants):
        jobs["android"] = {
            "runs-on": "ubuntu-latest", "needs": "gate",
            "steps": [*_setup(install),
                      _step("Build for Android", run="charpente build --platform android-arm64 --config Release",
                            env={"ANDROID_NDK_HOME": "${{ env.ANDROID_NDK_LATEST_HOME }}"})],
        }
    if any(p.startswith("harmonyos") for p in wants):
        jobs["harmonyos"] = {
            "runs-on": "ubuntu-latest", "needs": "gate",
            "steps": [*_setup(install),
                      _step("Install the OpenHarmony native SDK (checksum-verified)", run="charpente toolchain install ohos"),
                      _step("Build for HarmonyOS", run="charpente build --platform harmonyos-arm64 --config Release")],
        }
    if any(p.startswith("wasm32-emscripten") for p in wants):
        jobs["wasm"] = {
            "runs-on": "ubuntu-latest", "needs": "gate",
            "steps": [*_setup(install),
                      _step("Set up Emscripten", uses="mymindstorm/setup-emsdk@v14"),
                      _step("Build for the web", run="charpente build --platform wasm32-emscripten --config Release")],
        }
    if any(p.startswith(("linux-arm", "linux-riscv", "windows-arm", "wasm32-wasi", "cortexm", "avr")) for p in wants):
        cross = [p for p in platforms if p.startswith(("linux-arm", "linux-riscv", "windows-arm", "wasm32-wasi", "cortexm", "avr"))]
        jobs["cross"] = {
            "runs-on": "ubuntu-latest", "needs": "gate",
            "strategy": {"fail-fast": False, "matrix": {"platform": cross}},
            "steps": [*_setup(install),
                      _step("Install zig (checksum-verified)", run="charpente toolchain install zig"),
                      _step("Cross-build", run="charpente build --platform ${{ matrix.platform }} --config Release")],
        }
    if any(p.startswith("freebsd") for p in wants):
        jobs["freebsd"] = {
            "runs-on": "ubuntu-latest", "needs": "gate",
            "steps": [_step("Check out", uses=CHECKOUT),
                      _step("Build and test on FreeBSD", uses="vmactions/freebsd-vm@v1", with_={
                          "prepare": "pkg install -y python3 py311-pip clang",
                          "run": "python3 -m pip install charpente\ncharpente build --config Release\ncharpente test --config Release"})],
        }
    return {
        "name": "charpente",
        "on": {"push": {"branches": [branch]}, "pull_request": {}},
        "permissions": {"contents": "read"},
        "concurrency": {"group": "charpente-${{ github.ref }}", "cancel-in-progress": True},
        "jobs": jobs,
    }


def render(**kwargs: Any) -> str:
    header = ("# Generated by `charpente ci init`. Edit freely; regenerate with `charpente ci init --force`.\n"
              "# It runs the same quality gate you run locally (`charpente check`); Charpente turns its diagnostics into\n"
              "# GitHub annotations automatically.\n")
    return header + dump(workflow(**kwargs)) + "\n"
