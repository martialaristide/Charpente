"""Compile/link command lines, per toolchain family. Pure functions: given a
Toolchain + Target + a few paths, return the argv list to run -- no
subprocess call here, which is what makes these trivial to unit test
without a real compiler installed.

Two families cover every toolchain toolchains.py can detect: MSVC-style
(msvc, clang-cl) and GNU-style (gcc, clang, apple-clang, mingw -- mingw's
gcc/g++ take the same flags as Linux gcc).
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import List, Optional, Sequence

from .dsl.model import OS, Kind, Language, Target
from .errors import ChValueError
from .toolchains import Toolchain

_MSVC_STYLE = {"msvc", "clang-cl"}
_SHARED = (Kind.SHARED_LIBRARY, Kind.PLUGIN)
_ASSEMBLY_SUFFIXES = (".s",)          # `.S` is the same suffix once lower-cased: the driver decides on the real name
_OBJC_SUFFIXES = (".m", ".mm")
_DEFAULT_STANDARD = {Language.C: "c11", Language.CPP: "c++17"}
_EXECUTABLE_SUFFIX = {OS.WINDOWS: ".exe", OS.WASI: ".wasm", OS.WASM: ".js", OS.BAREMETAL: ".elf"}
_NO_SHARED_LIBRARIES = (OS.WASM, OS.WASI, OS.BAREMETAL)


def family(toolchain: Toolchain) -> str:
    return "msvc" if toolchain.name in _MSVC_STYLE else "gnu"


def _driver_args(toolchain: Toolchain, target: Target) -> List[str]:
    """What follows the compiler executable for drivers that need it (`zig cc -target ...`)."""
    return list(toolchain.cxx_args if target.language.value == "cpp" else toolchain.c_args)


def _optimization_flags(family_name: str, debug: bool) -> List[str]:
    if family_name == "msvc":
        return ["/Zi", "/Od", "/MDd"] if debug else ["/O2", "/MD"]
    return ["-g", "-O0"] if debug else ["-O2"]


def is_shared(target: Target, toolchain: Toolchain) -> bool:
    """Built as a shared library: SHARED_LIBRARY and PLUGIN everywhere, and an Android app (NativeActivity
    loads it as a library)."""
    return target.kind in _SHARED or (target.kind == Kind.MOBILE_APP and toolchain.target.startswith("android"))


def _needs_pic(target: Target, toolchain: Toolchain) -> bool:
    """Shared objects must be position independent -- except on Windows, where all code is (and GCC warns)."""
    windows = toolchain.name == "mingw" or toolchain.target.startswith("windows")
    return is_shared(target, toolchain) and not windows


def compile_args(toolchain: Toolchain, target: Target, source: Path, obj: Path, *, debug: bool,
                 depfile: Optional[Path] = None, language: Optional[Language] = None) -> List[str]:
    """`depfile`, when given, makes the compiler report which headers it read: a
    Makefile-style file for GNU-style compilers (`-MMD -MF`), `/showIncludes`
    notes on stdout for MSVC-style ones. The engine uses that for exact
    incremental builds."""
    fam = family(toolchain)
    if language is not None and language != target.language:
        # One file of another language in this target (the NDK's C glue in a C++ app): its own driver and standard.
        target = replace(target, language=language, standard=_DEFAULT_STANDARD[language])
    suffix = source.suffix.lower()
    if suffix in _ASSEMBLY_SUFFIXES + _OBJC_SUFFIXES:
        return _other_language_args(toolchain, target, source, obj, suffix, debug, depfile)
    compiler = toolchain.cxx_compiler if target.language.value == "cpp" else toolchain.c_compiler

    if fam == "msvc":
        std_flag = f"/std:{target.standard}"
        args = [compiler, *_driver_args(toolchain, target), "/c", str(source), f"/Fo{obj}", std_flag, "/nologo", "/EHsc"]
        args += _optimization_flags(fam, debug)
        if depfile is not None:
            args.append("/showIncludes")
        args += [f"/I{d}" for d in target.include_dirs]
        args += [f"/D{d}" for d in target.define_macros]
        args += target.extra_compile_flags
        return args

    std_flag = f"-std={target.standard}"
    args = [compiler, *_driver_args(toolchain, target), "-c", str(source), "-o", str(obj), std_flag]
    args += _optimization_flags(fam, debug)
    if _needs_pic(target, toolchain):
        args.append("-fPIC")
    if depfile is not None:
        args += ["-MMD", "-MF", str(depfile)]
    args += [f"-I{d}" for d in target.include_dirs]
    args += [f"-D{d}" for d in target.define_macros]
    args += target.extra_compile_flags
    return args


def _other_language_args(toolchain: Toolchain, target: Target, source: Path, obj: Path, suffix: str,
                         debug: bool, depfile: Optional[Path]) -> List[str]:
    """Assembly (`.s`, `.S`) and Objective-C (`.m`, `.mm`) go through the GNU-style compiler driver, which
    picks the language from the suffix. MSVC-style toolchains have no such driver: refuse, do not guess."""
    if family(toolchain) == "msvc":
        raise ChValueError("CH3007", kind=f"{suffix} sources with {toolchain.name}")
    plus = suffix == ".mm"
    compiler = toolchain.cxx_compiler if plus else toolchain.c_compiler
    driver = toolchain.cxx_args if plus else toolchain.c_args
    args = [compiler, *driver, "-c", str(source), "-o", str(obj)]
    if plus and target.language.value == "cpp":
        args.append(f"-std={target.standard}")
    args += _optimization_flags("gnu", debug)
    if depfile is not None:
        args += ["-MMD", "-MF", str(depfile)]
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
    library_dirs: Sequence[Path] = (),
) -> List[str]:
    """`library_dirs` are extra `-L`/`/LIBPATH:` search paths -- the builder
    passes each dependency's own build directory here, so `t.links([dep])`
    finds `libdep.a`/`dep.lib` without the .charpente file having to know
    where the build system put it."""
    fam = family(toolchain)

    if target.kind == Kind.STATIC_LIBRARY:
        if fam == "msvc":
            return [toolchain.archiver, *toolchain.ar_args, f"/OUT:{output}", "/nologo", *[str(o) for o in objects]]
        return [toolchain.archiver, *toolchain.ar_args, "rcs", str(output), *[str(o) for o in objects]]

    if fam == "msvc":
        args = [toolchain.linker, *toolchain.ld_args, *[str(o) for o in objects], f"/Fe{output}", "/nologo"]
        if target.kind in _SHARED:
            args.append("/LD")
        # /LIBPATH: (and any other pure linker flag) must come after a
        # literal "/link" separator: cl.exe and clang-cl both compile-then-
        # link in one invocation, and only forward whatever follows "/link"
        # to the linker unmodified -- without it, clang-cl in particular
        # rejects "/LIBPATH:..." outright as an unrecognized input file
        # ("no such file or directory"), a real failure caught by this
        # project's own CI (windows-latest ships clang-cl, not cl.exe, on
        # PATH by default -- a toolchain this project hadn't been
        # exercised against until CI ran on a machine that has it).
        if library_dirs or target.extra_link_flags:
            args.append("/link")
            args += [f"/LIBPATH:{d}" for d in library_dirs]
            args += target.extra_link_flags
        args += [f"{lib}.lib" for lib in target.link_libraries]
        return args

    args = [toolchain.linker, *toolchain.ld_args, *[str(o) for o in objects], "-o", str(output)]
    if is_shared(target, toolchain):
        args.append("-shared")
    if toolchain.target.startswith("android") and target.platform_settings.get("android", {}).get("stl", "static") == "static":
        args.append("-static-libstdc++")           # else the app needs libc++_shared.so next to it
    args += [f"-L{d}" for d in library_dirs]
    args += [f"-l{lib}" for lib in target.link_libraries]
    args += target.extra_link_flags
    return args


def side_outputs(target: Target, target_os: OS, output: Path) -> List[Path]:
    """Files the link step writes next to its main output: Emscripten's `app.js` comes with `app.wasm`.
    They are declared so the cache stores and restores them with the rest."""
    if target_os == OS.WASM and target.kind in (Kind.EXECUTABLE, Kind.TEST):
        return [output.with_suffix(".wasm")]
    return []


def output_filename(target: Target, target_os: OS, toolchain: Toolchain) -> str:
    """The conventional output filename for this target on this OS/toolchain
    -- executable extension, static/shared library naming (lib*.a/.so/.dylib
    on GNU-style toolchains, *.lib/*.dll on MSVC-style)."""
    fam = family(toolchain)
    name = target.name

    if target.kind in (Kind.EXECUTABLE, Kind.TEST):
        return name + _EXECUTABLE_SUFFIX.get(target_os, "")

    if target.kind == Kind.STATIC_LIBRARY:
        return f"{name}.lib" if fam == "msvc" else f"lib{name}.a"

    if target.kind in _SHARED or (target.kind == Kind.MOBILE_APP and target_os == OS.ANDROID):
        if target_os in _NO_SHARED_LIBRARIES:
            raise ChValueError("CH3007", kind=f"{target.kind.value} (not available for {target_os.value})")
        if target_os == OS.WINDOWS:
            return f"{name}.dll"
        return f"lib{name}.dylib" if target_os in (OS.MACOS, OS.IOS, OS.VISIONOS) else f"lib{name}.so"

    raise ChValueError("CH3007", kind=target.kind.value)
