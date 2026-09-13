from __future__ import annotations

import argparse
import shutil
from typing import List

from ._common import load


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente clean", description="Remove build output.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parsed = parser.parse_args(args)

    workspace = load(parsed.file)
    build_dir = workspace.location / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print(f"Removed {build_dir}")
    else:
        print(f"Nothing to clean ({build_dir} does not exist).")
    return 0
