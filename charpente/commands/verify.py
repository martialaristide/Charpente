"""`charpente verify-reproducible` -- build the project twice, in two different folders, and compare the outputs byte for byte."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

from .. import repro
from ..core import process
from ..errors import ChError
from ._common import CommandError, load

IGNORED = ("build", ".git", ".hg", ".svn", "node_modules", "__pycache__", "*.pyc")


def _copy_project(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*IGNORED), symlinks=True)


def _build(folder: Path, config: str, platform: str, extra: List[str]) -> Dict[str, Path]:
    """Build `folder` in reproducible mode, without any cache, and return {target: output path}."""
    argv = [sys.executable, "-m", "charpente", "build", "--reproducible", "--no-cache", "--config", config, "--output", "jsonl", *extra]
    if platform:
        argv += ["--platform", platform]
    # The copy is byte-identical to the project the user already trusts: trusting it again here is not a new decision.
    env = dict(os.environ, CHARPENTE_TRUST_ALL="1")
    result = process.run(argv, cwd=str(folder), env=env, timeout=3600)
    if result.returncode != 0:
        raise CommandError("CH8025", detail=f"the build in {folder} failed:\n{result.output[-1500:]}")
    return {name: Path(path) for name, path in repro.outputs_from_events(result.stdout.splitlines()).items()}


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente verify-reproducible",
                                     description="Build twice in different folders (fixed clock, mapped paths, no timestamps) and compare the outputs.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--config", default="Release", choices=["Debug", "Release"])
    parser.add_argument("--platform", default="", help="Build for another platform")
    parser.add_argument("--keep", action="store_true", help="Keep the two build folders (to inspect the differences)")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON")
    parsed = parser.parse_args(args)

    workspace = load(parsed.file, None, materialize_packages=False)
    source = Path(workspace.root)
    scratch = Path(tempfile.mkdtemp(prefix="charpente-repro-"))
    first, second = scratch / "one" / "project", scratch / "second-build-with-a-longer-name" / "nested" / "project"
    try:
        for folder in (first, second):
            _copy_project(source, folder)
        extra = ["--file", Path(parsed.file).name] if parsed.file else []
        if not parsed.json:
            print(f"Building twice: {first}\n                {second}")
        built_a = _build(first, parsed.config, parsed.platform, extra)
        built_b = _build(second, parsed.config, parsed.platform, extra)
        report = repro.compare_builds(built_a, built_b, [str(first), str(second), str(first.parent), str(second.parent)])
    except ChError:
        raise
    finally:
        if parsed.keep:
            print(f"Kept {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)

    payload = {"reproducible": report.ok, "identical": report.identical, "missing": report.missing,
               "different": [{"target": d.name, "sizeA": d.size_a, "sizeB": d.size_b, "firstDifferentByte": d.first_offset, "hints": d.hints} for d in report.different]}
    if parsed.json:
        print(json.dumps(payload, indent=1))
    else:
        for name in report.identical:
            print(f"  [identical]   {name}")
        for name in report.missing:
            print(f"  [MISSING]     {name}: not produced by both builds")
        for d in report.different:
            print(f"  [DIFFERENT]   {d.name}: {d.size_a} vs {d.size_b} bytes, first difference at byte {d.first_offset}")
            for hint in d.hints:
                print(f"                - {hint}")
        print("Reproducible: the two builds are byte-identical." if report.ok else "NOT reproducible: see the differences above.")
    return 0 if report.ok else 1
