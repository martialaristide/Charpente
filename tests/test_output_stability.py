"""The plain-text and JSON Lines output of a build must not change (byte for byte, once the volatile parts are masked).

A whole build session is replayed in a separate process (tests/output_scenarios.py) with a scripted compiler, through the real `Session`, renderers and result printing, so
nothing depends on the machine, the operating system or the toolchain. The output of each scenario is compared with a reference recorded from the code as it was *before*
the console-style work (tests/golden/output/). To re-record after an intended change of the plain or JSON output:  UPDATE_GOLDEN=1 python -m pytest tests/test_output_stability.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("output_scenarios.py")
GOLDEN = Path(__file__).parent / "golden" / "output"
SCENARIOS = ("cold", "warm", "failing")


def replay(scenario, mode, *extra):
    env = dict(os.environ, PYTHONHASHSEED="0", CHARPENTE_LANG="en", PYTHONIOENCODING="utf-8", NO_COLOR="1")
    env.pop("CHARPENTE_TRUST_ALL", None)
    result = subprocess.run([sys.executable, str(SCRIPT), scenario, mode, *extra], capture_output=True, env=env, timeout=300, stdin=subprocess.DEVNULL)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[-1500:]
    return result.stdout.decode("utf-8")


def check(name, text):
    path = GOLDEN / f"{name}.txt"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    assert path.is_file(), f"no reference for {name}: record it with UPDATE_GOLDEN=1"
    assert text == path.read_bytes().decode("utf-8"), f"the {name} output changed (masked text below)\n{text}"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_plain_output_is_unchanged(scenario):
    check(f"plain-{scenario}", replay(scenario, "plain"))


def test_verbose_plain_output_is_unchanged():
    check("plain-cold-verbose", replay("cold", "plain", "verbose"))


def check_jsonl(name, text):
    """The events must be the same set of lines as the reference. Their order is compared only where it is guaranteed: the engine checks what is up to date on several
    threads, so those events may arrive in any order (with a fixed hash seed too)."""
    path = GOLDEN / f"{name}.txt"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    assert path.is_file(), f"no reference for {name}: record it with UPDATE_GOLDEN=1"
    reference = path.read_bytes().decode("utf-8")
    assert sorted(text.splitlines()) == sorted(reference.splitlines()), f"the {name} events changed (masked text below)\n{text}"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_jsonl_output_is_unchanged(scenario):
    text = replay(scenario, "jsonl")
    check_jsonl(f"jsonl-{scenario}", text)
    types = [json.loads(line)["type"] for line in text.splitlines()]
    assert types[:2] == ["session.started", "workspace.loaded"] and types[-1] == "session.finished"      # the guaranteed order
    events = [json.loads(line) for line in text.splitlines()]
    for target in ("core", "app", "tests"):
        started = next((i for i, e in enumerate(events) if e["type"] == "target.started" and e["payload"].get("target") == target), None)
        ended = next((i for i, e in enumerate(events) if e["type"] in ("target.finished", "target.failed", "target.up_to_date") and e["payload"].get("target") == target), None)
        assert ended is not None and (started is None or started < ended)


def test_the_replay_itself_is_deterministic():
    assert replay("failing", "plain") == replay("failing", "plain")                      # the plain text is fully deterministic


def test_the_references_are_really_there_and_not_empty():
    names = [f"plain-{s}" for s in SCENARIOS] + [f"jsonl-{s}" for s in SCENARIOS] + ["plain-cold-verbose"]
    for name in names:
        assert (GOLDEN / f"{name}.txt").stat().st_size > 50, name
