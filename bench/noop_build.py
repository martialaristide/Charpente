"""Benchmark: how fast is Charpente itself on a large project?

    python bench/noop_build.py [--files 10000] [--headers 200] [--repeat 5] [--profile]

The project is synthetic: N sources, each including two of M headers. The
compiler is an in-process fake that creates the objects and depfiles, so the
numbers measure Charpente (planning, freshness checks, scheduling, cache), not
gcc. The result feeds ADR 0010 (does the core need a native implementation?).
The roadmap target: a no-op build in under 300 ms for 10 000 files.

Scenarios: clean build, no-op build, one source edited, one header edited.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from charpente import builder  # noqa: E402
from charpente.core.cache import LocalCache  # noqa: E402
from charpente.dsl.model import OS, Target, Workspace  # noqa: E402
from charpente.toolchains import Toolchain  # noqa: E402

TOOLCHAIN = Toolchain(name="fake", c_compiler="fakecc", cxx_compiler="fakecxx", archiver="fakear", linker="fakecxx")


class FakeCompiler:
    def __init__(self, headers_of):
        self.headers_of = headers_of

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        if "-c" in argv:
            src = Path(argv[argv.index("-c") + 1])
            obj = Path(argv[argv.index("-o") + 1])
            obj.parent.mkdir(parents=True, exist_ok=True)
            obj.write_bytes(b"obj:" + src.read_bytes())   # content-dependent, like a real object
            dep = Path(argv[argv.index("-MF") + 1])
            deps = " ".join(self.headers_of(src))
            dep.write_text(f"{obj}: {src} {deps}\n")
        else:
            out = Path(argv[argv.index("rcs") + 1] if "rcs" in argv else argv[argv.index("-o") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"bin")
        return subprocess.CompletedProcess(argv, 0, "", "")


def make_project(root: Path, files: int, headers: int) -> Workspace:
    inc = root / "include"
    inc.mkdir(parents=True)
    for h in range(headers):
        (inc / f"h{h}.h").write_text(f"#pragma once\nint h{h}();\n")
    src = root / "src"
    for i in range(files):
        d = src / f"d{i % 50}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"f{i}.cpp").write_text(
            f'#include "h{i % headers}.h"\n#include "h{(i * 7) % headers}.h"\nint f{i}(){{return {i};}}\n')
    ws = Workspace(name="Bench", location=root)
    ws.add_target(Target(name="app", source_patterns=["src/**/*.cpp"], include_dirs=["include"], location=root))
    return ws


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=10000)
    ap.add_argument("--headers", type=int, default=200)
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--profile", action="store_true")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="charpente-bench-"))
    os.environ["CHARPENTE_HOME"] = str(tmp / "home")
    try:
        t0 = time.perf_counter()
        ws = make_project(tmp / "proj", args.files, args.headers)
        print(f"generated {args.files} sources + {args.headers} headers in {time.perf_counter() - t0:.1f}s")

        inc = tmp / "proj" / "include"

        def headers_of(src: Path):
            i = int(src.stem[1:])
            return [str(inc / f"h{i % args.headers}.h"), str(inc / f"h{(i * 7) % args.headers}.h")]

        fake = FakeCompiler(headers_of)
        cache = LocalCache(tmp / "cache")

        def build():
            t = time.perf_counter()
            r = builder.build_workspace(ws, TOOLCHAIN, OS.LINUX, run=fake, cache=cache, jobs=8)
            return r, (time.perf_counter() - t) * 1000

        r, ms = build()
        assert r.ok, r.targets[0].error
        print(f"clean build:                 {ms:9.0f} ms   ({args.files + 1} actions)")

        # A build within 2 s of the previous one cannot be stamped (racy timestamps);
        # wait, run once to write the stamp, then measure.
        time.sleep(2.2)
        build()
        timings = []
        for _ in range(args.repeat):
            r, ms = build()
            timings.append(ms)
            assert r.ok and r.targets[0].skipped
        best, med = min(timings), sorted(timings)[len(timings) // 2]
        verdict = "OK" if best < 300 else "ABOVE TARGET"
        print(f"no-op build (best / median): {best:5.0f} / {med:.0f} ms   target < 300 ms  [{verdict}]")

        victim = tmp / "proj" / "src" / "d1" / "f1.cpp"
        victim.write_text(victim.read_text() + "// edited\n")
        r, ms = build()
        assert r.ok and r.targets[0].executed == 2
        print(f"one source edited:           {ms:9.0f} ms   (1 compile + link)")

        time.sleep(2.2)
        build()
        (inc / "h3.h").write_text("#pragma once\nint h3(); // edited\n")
        r, ms = build()
        print(f"one header edited:           {ms:9.0f} ms   ({r.targets[0].executed - 1} compiles + link)")

        if args.profile:
            import cProfile
            import pstats
            time.sleep(2.2)
            build()
            prof = cProfile.Profile()
            prof.enable()
            build()
            prof.disable()
            pstats.Stats(prof).sort_stats("tottime").print_stats(12)
        return 0 if best < 300 else 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
