from pathlib import Path

from charpente import flags
from charpente.dsl.model import Kind, Language, OS, Target
from charpente.toolchains import Toolchain

GCC = Toolchain(name="gcc", c_compiler="gcc", cxx_compiler="g++", archiver="ar", linker="g++")
CLANG_CL = Toolchain(name="clang-cl", c_compiler="clang-cl", cxx_compiler="clang-cl",
                     archiver="llvm-lib", linker="clang-cl")
MSVC = Toolchain(name="msvc", c_compiler="cl", cxx_compiler="cl", archiver="lib", linker="cl")


def test_family_classification():
    assert flags.family(GCC) == "gnu"
    assert flags.family(MSVC) == "msvc"
    assert flags.family(CLANG_CL) == "msvc"


# =============================================================================
#  GNU-style compile
# =============================================================================
def test_gnu_compile_args_shape():
    t = Target(name="app", language=Language.CPP, standard="c++20",
               include_dirs=["include"], define_macros=["DEBUG=1"])
    args = flags.compile_args(GCC, t, Path("src/main.cpp"), Path("obj/main.o"), debug=True)
    assert args[0] == "g++"
    assert "-c" in args and str(Path("src/main.cpp")) in args
    assert "-o" in args and str(Path("obj/main.o")) in args
    assert "-std=c++20" in args
    assert "-Iinclude" in args
    assert "-DDEBUG=1" in args
    assert "-g" in args  # debug build


def test_gnu_release_uses_o2_not_debug_flags():
    t = Target(name="app")
    args = flags.compile_args(GCC, t, Path("a.cpp"), Path("a.o"), debug=False)
    assert "-O2" in args
    assert "-g" not in args


def test_gnu_uses_c_compiler_for_c_language():
    t = Target(name="app", language=Language.C, standard="c11")
    args = flags.compile_args(GCC, t, Path("a.c"), Path("a.o"), debug=False)
    assert args[0] == "gcc"
    assert "-std=c11" in args


# =============================================================================
#  MSVC-style compile
# =============================================================================
def test_msvc_compile_args_shape():
    t = Target(name="app", language=Language.CPP, standard="c++20",
               include_dirs=["include"], define_macros=["DEBUG=1"])
    args = flags.compile_args(MSVC, t, Path("src/main.cpp"), Path("obj/main.obj"), debug=True)
    assert args[0] == "cl"
    assert "/c" in args
    assert any(a.startswith("/Fo") for a in args)
    assert "/std:c++20" in args
    assert "/Iinclude" in args
    assert "/DDEBUG=1" in args
    assert "/Zi" in args


# =============================================================================
#  Linking
# =============================================================================
def test_gnu_link_executable():
    t = Target(name="app", kind=Kind.EXECUTABLE, link_libraries=["m"])
    args = flags.link_args(GCC, t, [Path("a.o"), Path("b.o")], Path("app"))
    assert args[0] == "g++"
    assert str(Path("a.o")) in args and str(Path("b.o")) in args
    assert "-o" in args
    assert "-lm" in args
    assert "-shared" not in args


def test_gnu_link_shared_library_adds_shared_flag():
    t = Target(name="mylib", kind=Kind.SHARED_LIBRARY)
    args = flags.link_args(GCC, t, [Path("a.o")], Path("libmylib.so"))
    assert "-shared" in args


def test_gnu_static_library_uses_archiver_not_linker():
    t = Target(name="mylib", kind=Kind.STATIC_LIBRARY)
    args = flags.link_args(GCC, t, [Path("a.o"), Path("b.o")], Path("libmylib.a"))
    assert args[0] == "ar"
    assert args[1] == "rcs"


def test_msvc_static_library_uses_lib_exe():
    t = Target(name="mylib", kind=Kind.STATIC_LIBRARY)
    args = flags.link_args(MSVC, t, [Path("a.obj")], Path("mylib.lib"))
    assert args[0] == "lib"
    assert any(a.startswith("/OUT:") for a in args)


def test_msvc_link_executable_uses_cl():
    t = Target(name="app", kind=Kind.EXECUTABLE, link_libraries=["ws2_32"])
    args = flags.link_args(MSVC, t, [Path("a.obj")], Path("app.exe"))
    assert args[0] == "cl"
    assert any(a.startswith("/Fe") for a in args)
    assert "ws2_32.lib" in args


# =============================================================================
#  output_filename()
# =============================================================================
def test_executable_name_on_windows_has_exe_extension():
    t = Target(name="app", kind=Kind.EXECUTABLE)
    assert flags.output_filename(t, OS.WINDOWS, MSVC) == "app.exe"


def test_executable_name_on_linux_has_no_extension():
    t = Target(name="app", kind=Kind.EXECUTABLE)
    assert flags.output_filename(t, OS.LINUX, GCC) == "app"


def test_gnu_static_library_naming():
    t = Target(name="core", kind=Kind.STATIC_LIBRARY)
    assert flags.output_filename(t, OS.LINUX, GCC) == "libcore.a"


def test_msvc_static_library_naming():
    t = Target(name="core", kind=Kind.STATIC_LIBRARY)
    assert flags.output_filename(t, OS.WINDOWS, MSVC) == "core.lib"


def test_shared_library_naming_per_os():
    t = Target(name="core", kind=Kind.SHARED_LIBRARY)
    assert flags.output_filename(t, OS.LINUX, GCC) == "libcore.so"
    assert flags.output_filename(t, OS.MACOS, GCC) == "libcore.dylib"
    assert flags.output_filename(t, OS.WINDOWS, MSVC) == "core.dll"
