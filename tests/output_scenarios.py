"""Replay a build session in-process with a scripted compiler and print its masked plain or JSON Lines output. Run as a script by tests/test_output_stability.py:

    python tests/output_scenarios.py SCENARIO MODE [verbose]        SCENARIO: cold | warm | failing      MODE: plain | jsonl

It runs in its own process with PYTHONHASHSEED=0 because the engine starts independent actions in an order that depends on Python's hash seed (harmless for a
build, but it would make a byte-for-byte comparison flaky). Nothing depends on the machine: no real compiler, no real toolchain, no clock (durations and paths are masked).
"""
import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("CHARPENTE_LANG", "en")

from helpers import GCC, FakeToolchain  # noqa: E402

from charpente import resources  # noqa: E402
from charpente.builder import build_workspace  # noqa: E402
from charpente.commands._session import Session  # noqa: E402
from charpente.commands.build import print_result_lines  # noqa: E402
from charpente.dsl.model import OS, Kind, Target, Workspace  # noqa: E402

VOLATILE_KEYS = ("timestamp", "wall_time", "id", "parent_id", "session_id")
VOLATILE_PAYLOAD = ("duration", "cwd", "path", "argv", "version", "free_bytes", "critical_path")


def make(root):
    for rel, text in {"core/core.cpp": "int core();", "app/main.cpp": "int main() { return 0; }", "tests/t.cpp": "int t();"}.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    ws = Workspace(name="Demo", location=root)
    ws.add_target(Target(name="core", kind=Kind.STATIC_LIBRARY, source_patterns=["core/*.cpp"], location=root))
    ws.add_target(Target(name="app", depends_on=["core"], source_patterns=["app/*.cpp"], location=root))
    ws.add_target(Target(name="tests", kind=Kind.TEST, depends_on=["core"], source_patterns=["tests/*.cpp"], location=root))
    return ws


def session(ws, mode, fake, verbose=False):
    """What `charpente build --output MODE` prints, as the build command does it (same Session, same result lines). Returns (stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        parsed = argparse.Namespace(output=mode, verbose=verbose)
        with Session("build", parsed, ws, toolchain="gcc", config="Debug") as s:
            s.say(f"Building {ws.name} (Debug, gcc)...")
            result = build_workspace(ws, GCC, OS.LINUX, config="Debug", run=fake, jobs=1, bus=s.bus, use_cache=False)
            print_result_lines(s, result, toolchain_name="gcc")
            s.finish(result.ok, 0 if result.ok else 1)
    return out.getvalue(), err.getvalue()


def mask(text, root):
    text = text.replace("\r\n", "\n").replace(str(root), "<ROOT>").replace(str(root).replace("\\", "/"), "<ROOT>").replace("\\\\", "/").replace("\\", "/")
    return re.sub(r"\d+\.\d+s\b", "<T>s", text)


def mask_value(value, root):
    if isinstance(value, str):
        return mask(value, root)
    if isinstance(value, list):
        return [mask_value(v, root) for v in value]
    if isinstance(value, dict):
        return {k: mask_value(v, root) for k, v in value.items()}
    return value


def mask_jsonl(text, root):
    lines = []
    for line in text.replace("\r\n", "\n").splitlines():
        event = json.loads(line)
        for key in VOLATILE_KEYS:
            event.pop(key, None)
        payload = event["payload"]
        for key in VOLATILE_PAYLOAD:
            if key in payload:
                payload[key] = "<X>"
        for key, value in list(payload.items()):
            payload[key] = mask_value(value, root)
        lines.append(json.dumps(event, sort_keys=True))
    return "\n".join(lines) + "\n"


def run(scenario, mode, verbose=False):
    healthy = resources.Sample(on_battery=False, free_memory=1 << 40, free_disk=1 << 40, temperature=40.0)
    resources.sample = lambda build_dir: healthy                      # what the machine has free must not change what a build says
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        ws = make(root)
        fake = FakeToolchain(fail_on=["main"] if scenario == "failing" else ())
        if scenario in ("warm", "failing"):
            session(ws, "plain", FakeToolchain())                     # a good build first, so this one is incremental
        if scenario == "failing":
            (root / "app" / "main.cpp").write_text("int main() { syntax error }")
        out, err = session(ws, mode, fake, verbose)
        if mode == "jsonl":
            return mask_jsonl(out, root) + ("--- stderr ---\n" + mask(err, root) if err else "")
        return mask(out, root) + ("--- stderr ---\n" + mask(err, root) if err else "")


if __name__ == "__main__":
    scenario, mode, *rest = sys.argv[1:]
    sys.stdout.buffer.write(run(scenario, mode, "verbose" in rest).encode("utf-8"))
