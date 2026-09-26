"""`charpente docs` -- documentation of the project's API and target graph, as Markdown (or through Doxygen when it is installed)."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Dict, List

from .. import docsgen
from ..core import process
from ._common import CommandError, load


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente docs", description="Generate the project's documentation: API from doc comments, and the target graph.")
    parser.add_argument("--file", help="Path to the .charpente workspace file")
    parser.add_argument("--out", help="Output folder (default: docs/api in the project)")
    parser.add_argument("--doxygen", action="store_true", help="Use Doxygen (if installed) instead of the built-in extractor")
    parsed = parser.parse_args(args)

    workspace = load(parsed.file, None, materialize_packages=False)
    out = Path(parsed.out).resolve() if parsed.out else Path(workspace.root) / "docs" / "api"
    out.mkdir(parents=True, exist_ok=True)
    if parsed.doxygen:
        exe = shutil.which("doxygen")
        if exe is None:
            raise CommandError("CH8007", what="doxygen", hint="install Doxygen (https://www.doxygen.nl), or run without --doxygen for the built-in extractor")
        config = out / "Doxyfile"
        config.write_text(docsgen.doxyfile(workspace, out), encoding="utf-8")
        result = process.run([exe, str(config)], cwd=str(workspace.root), timeout=1800)
        print(result.output or "Doxygen finished.")
        (out / "graph.svg").write_text(docsgen.svg(workspace), encoding="utf-8")
        return 0 if result.returncode == 0 else 1

    (out / "targets").mkdir(exist_ok=True)
    counts: Dict[str, int] = {}
    for name, target in workspace.targets.items():
        if target.external:
            continue
        page, count = docsgen.target_page(workspace, target)
        counts[name] = count
        (out / "targets" / f"{name}.md").write_text(page, encoding="utf-8")
    (out / "graph.svg").write_text(docsgen.svg(workspace), encoding="utf-8")
    (out / "index.md").write_text(docsgen.index_page(workspace, counts), encoding="utf-8")
    total = sum(counts.values())
    print(f"Wrote {out}: {len(counts)} target page(s), {total} documented declaration(s), the dependency graph (graph.svg and Mermaid).")
    if total == 0:
        print("No documentation comments were found in the public headers: write them with `///` or `/** ... */` above a declaration.")
    return 0
