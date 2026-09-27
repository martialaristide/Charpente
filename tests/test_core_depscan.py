from pathlib import Path, PureWindowsPath

from charpente.core import depscan, diagnostics


# ============================================================ GNU depfiles
def test_simple_depfile():
    text = "main.o: main.cpp include/a.h include/b.h\n"
    assert depscan.parse_gnu_depfile(text) == [Path("main.cpp"), Path("include/a.h"), Path("include/b.h")]


def test_continuation_lines():
    text = "main.o: main.cpp \\\n include/a.h \\\n include/b.h\n"
    assert [p.name for p in depscan.parse_gnu_depfile(text)] == ["main.cpp", "a.h", "b.h"]


def test_windows_continuation_with_crlf():
    text = "main.o: main.cpp \\\r\n a.h\r\n"
    assert [p.name for p in depscan.parse_gnu_depfile(text)] == ["main.cpp", "a.h"]


def test_escaped_spaces_are_part_of_the_name():
    assert depscan.parse_gnu_depfile("m.o: m.cpp a\\ b.h\n") == [Path("m.cpp"), Path("a b.h")]


def test_escaped_hash_and_dollar():
    assert depscan.parse_gnu_depfile("m.o: a\\#b.h c$$d.h\n") == [Path("a#b.h"), Path("c$d.h")]


def test_windows_drive_letters_do_not_split_the_rule():
    text = "C:/build/main.o: C:/src/main.cpp C:/inc/a.h\n"
    assert depscan.parse_gnu_depfile(text) == [Path("C:/src/main.cpp"), Path("C:/inc/a.h")]


def test_backslash_paths_are_kept_verbatim():
    text = "C:\\build\\main.o: C:\\src\\main.cpp\n"
    assert depscan.parse_gnu_depfile(text) == [Path("C:\\src\\main.cpp")]


def test_relative_paths_resolve_against_cwd(tmp_path):
    absolute = tmp_path.parent / "x.h"
    out = depscan.parse_gnu_depfile(f"m.o: src/m.cpp {absolute.as_posix()}\n", cwd=tmp_path)
    assert out[0] == tmp_path / "src" / "m.cpp"
    assert out[1] == absolute


def test_duplicates_are_removed_keeping_order():
    assert depscan.parse_gnu_depfile("m.o: a.h b.h a.h\n") == [Path("a.h"), Path("b.h")]


def test_empty_or_ruleless_depfile():
    assert depscan.parse_gnu_depfile("") == []
    assert depscan.parse_gnu_depfile("nothing here") == []
    assert depscan.parse_gnu_depfile("m.o:\n") == []


# ============================================================ MSVC /showIncludes
def test_show_includes_extracts_paths_and_strips_the_notes():
    out = ("main.cpp\n"
           "Note: including file: C:\\proj\\include\\a.h\n"
           "Note: including file:  C:\\proj\\include\\sub\\b.h\n"
           "main.cpp(3): warning C4100: 'x': unreferenced formal parameter\n")
    paths, rest = depscan.parse_show_includes(out)
    assert [PureWindowsPath(str(p)).name for p in paths] == ["a.h", "b.h"]           # the notes carry Windows paths, whatever system the test runs on
    assert "Note: including" not in rest
    assert "warning C4100" in rest and "main.cpp" in rest


def test_show_includes_with_no_notes():
    paths, rest = depscan.parse_show_includes("main.cpp\n")
    assert paths == [] and rest == "main.cpp"


# ============================================================ diagnostics
def test_gcc_error_with_column_and_flag():
    d = diagnostics.parse_line("src/main.cpp:12:5: warning: unused variable 'x' [-Wunused-variable]")
    assert (d.file, d.line, d.column, d.severity, d.code) == ("src/main.cpp", 12, 5, "warning", "-Wunused-variable")
    assert d.message == "unused variable 'x'"


def test_gcc_fatal_error_is_an_error():
    d = diagnostics.parse_line("a.cpp:1:10: fatal error: nope.h: No such file or directory")
    assert d.severity == "error" and d.line == 1 and "nope.h" in d.message


def test_windows_drive_letter_is_not_the_line_separator():
    d = diagnostics.parse_line(r"C:\proj\src\main.cpp:7:3: error: expected ';'")
    assert d.file == r"C:\proj\src\main.cpp" and d.line == 7 and d.column == 3


def test_msvc_style():
    d = diagnostics.parse_line(r"C:\proj\main.cpp(42,7): error C2065: 'x': undeclared identifier")
    assert (d.file, d.line, d.column, d.severity, d.code) == (r"C:\proj\main.cpp", 42, 7, "error", "C2065")
    d2 = diagnostics.parse_line("main.cpp(9): warning C4996: 'f': deprecated")
    assert d2.line == 9 and d2.column is None and d2.severity == "warning"


def test_note_lines_and_location_free_errors():
    assert diagnostics.parse_line("a.cpp:3:1: note: candidate: void f()").severity == "note"
    d = diagnostics.parse_line("collect2.exe: error: ld returned 1 exit status")
    assert d.severity == "error" and d.file is None and "ld returned 1" in d.message


def test_unrelated_lines_are_ignored():
    assert diagnostics.parse_line("   12 |   int x = ;") is None
    assert diagnostics.parse_line("") is None


def test_parse_output_keeps_order():
    text = "a.cpp:1:1: error: one\nnoise\nb.cpp:2:2: warning: two\n"
    got = diagnostics.parse_output(text)
    assert [(d.file, d.severity) for d in got] == [("a.cpp", "error"), ("b.cpp", "warning")]
