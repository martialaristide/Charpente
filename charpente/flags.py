"""Compile/link command lines, per toolchain family. Pure functions: given a
Toolchain + Target + a few paths, return the argv list to run -- no
subprocess call here, which is what makes these trivial to unit test
without a real compiler installed.

Two families cover every toolchain toolchains.py can detect: MSVC-style
(msvc, clang-cl) and GNU-style (gcc, clang, apple-clang, mingw -- mingw's
gcc/g++ take the same flags as Linux gcc).
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from .dsl.model import Kind, OS, Target
from .toolchains import Toolchain

_MSVC_STYLE = {"msvc", "clang-cl"}


def family(toolchain: Toolchain) -> str:
    return "msvc" if toolchain.name in _MSVC_STYLE else "gnu"


def _optimization_flags(family_name: str, debug: bool) -> List[str]:
    if family_name == "msvc":
        return ["/Zi", "/Od", "/MDd"] if debug else ["/O2", "/MD"]
    return ["-g", "-O0"] if debug else ["-O2"]


def compile_args(toolchain: Toolchain, target: Target, source: Path, obj: Path, *, debug: bool) -> List[str]:
    fam = family(toolchain)
    compiler = toolchain.cxx_compiler if target.language.value == "cpp" else toolchain.c_compiler

    if fam == "msvc":
        std_flag = f"/std:{target.standard}"
        args = [compiler, "/c", str(source), f"/Fo{obj}", std_flag, "/nologo", "/EHsc"]
        args += _optimization_flags(fam, debug)
        args += [f"/I{d}" for d in target.include_dirs]
        args += [f"/D{d}" for d in target.define_macros]
        args += target.extra_compile_flags
        return args

    std_flag = f"-std={target.standard}"
    args = [compiler, "-c", str(source), "-o", str(obj), std_flag]
    args += _optimization_flags(fam, debug)
    args += [f"-I{d}" for d in target.include_dirs]
    args += [f"-D{d}" for d in target.define_macros]
    args += target.extra_compile_flags
    return args


def link_args(
    toolchain: Toolchain,
    target: Target,
    objects: List[Path],
    output: Path,
    *,
    library_dirs: List[Path] = (),
) -> List[str]:
    """`library_dirs` are extra `-L`/`/LIBPATH:` search paths -- the builder
    passes each dependency's own build directory here, so `t.links([dep])`
    finds `libdep.a`/`dep.lib` without the .charpente file having to know
    where the build system put it."""
    fam = family(toolchain)

    if target.kind == Kind.STATIC_LIBRARY:
        if fam == "msvc":
            return [toolchain.archiver, f"/OUT:{output}", "/nologo", *[str(o) for o in objects]]
        return [toolchain.archiver, "rcs", str(output), *[str(o) for o in objects]]

    if fam == "msvc":
        args = [toolchain.linker, *[str(o) for o in objects], f"/Fe{output}", "/nologo"]
        if target.kind == Kind.SHARED_LIBRARY:
            args.append("/LD")
        args += [f"/LIBPATH:{d}" for d in library_dirs]
        args += [f"{lib}.lib" for lib in target.link_libraries]
        args += target.extra_link_flags
        return args

    args = [toolchain.linker, *[str(o) for o in objects], "-o", str(output)]
    if target.kind == Kind.SHARED_LIBRARY:
        args.append("-shared")
    args += [f"-L{d}" for d in library_dirs]
    args += [f"-l{lib}" for lib in target.link_libraries]
    args += target.extra_link_flags
    return args


def output_filename(target: Target, target_os: OS, toolchain: Toolchain) -> str:
    """The conventional output filename for this target on this OS/toolchain
    -- executable extension, static/shared library naming (lib*.a/.so/.dylib
    on GNU-style toolchains, *.lib/*.dll on MSVC-style)."""
    fam = family(toolchain)
    name = target.name

    if target.kind in (Kind.EXECUTABLE, Kind.TEST):
        return f"{name}.exe" if target_os == OS.WINDOWS else name

    if target.kind == Kind.STATIC_LIBRARY:
        return f"{name}.lib" if fam == "msvc" else f"lib{name}.a"

    if target.kind == Kind.SHARED_LIBRARY:
        if fam == "msvc":
            return f"{name}.dll"
        return f"lib{name}.dylib" if target_os == OS.MACOS else f"lib{name}.so"

    raise ValueError(f"Unhandled target kind: {target.kind}")
