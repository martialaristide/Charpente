import os
from pathlib import Path

import pytest

from charpente.core import globber
from charpente.errors import ChValueError


@pytest.fixture
def tree(tmp_path):
    files = [
        "main.cpp", "util.cpp", "util.h", "README.md",
        "src/a.cpp", "src/b.cpp", "src/b.h", "src/deep/c.cpp", "src/deep/deeper/d.cpp",
        "src/.hidden.cpp", "include/x.h", "test/t1.cpp", "test/t2.cc",
    ]
    for rel in files:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    return tmp_path


def rel(root, paths):
    return sorted(Path(p).relative_to(root).as_posix() for p in paths)


def pathlib_answer(root, pattern):
    return sorted(p.relative_to(root).as_posix() for p in Path(root).glob(pattern) if p.is_file())


@pytest.mark.parametrize("pattern", [
    "*.cpp", "src/*.cpp", "src/**/*.cpp", "**/*.cpp", "**/*.h", "src/**/*", "*.md", "test/t?.c*",
    "src/[ab].cpp", "include/*.h", "nothing/*.cpp", "src/deep/**/*.cpp",
])
def test_matches_what_pathlib_glob_matches(tree, pattern):
    assert rel(tree, globber.expand(str(tree), [pattern])) == pathlib_answer(tree, pattern)


def test_literal_paths(tree):
    assert rel(tree, globber.expand(str(tree), ["src/a.cpp"])) == ["src/a.cpp"]
    assert rel(tree, globber.expand(str(tree), ["src/missing.cpp"])) == []
    assert rel(tree, globber.expand(str(tree), ["include"])) == []          # a directory is not a file


def test_multiple_patterns_are_a_union_without_duplicates(tree):
    got = rel(tree, globber.expand(str(tree), ["src/*.cpp", "src/a.cpp", "*.cpp"]))
    assert got == sorted(set(got)) and "src/a.cpp" in got and "main.cpp" in got


def test_backslash_separators_are_accepted(tree):
    assert rel(tree, globber.expand(str(tree), ["src\\*.cpp"])) == pathlib_answer(tree, "src/*.cpp")


def test_double_star_inside_a_component_is_rejected_with_a_helpful_error(tree):
    with pytest.raises(ChValueError) as exc:
        globber.expand(str(tree), ["src/**.cpp"])
    assert exc.value.code == "CH1019" and "src/**/*.cpp" in str(exc.value)


def test_absolute_patterns_are_rejected(tree):
    with pytest.raises(ChValueError) as exc:
        globber.expand(str(tree), [str(tree / "*.cpp")])
    assert exc.value.code == "CH1020"


def test_parent_relative_patterns_work(tree):
    inner = tree / "src" / "deep"
    assert rel(tree, globber.expand(str(inner), ["../*.cpp"])) == ["src/a.cpp", "src/b.cpp", "src/.hidden.cpp"] \
        or sorted(rel(tree, globber.expand(str(inner), ["../*.cpp"]))) == sorted(
            ["src/a.cpp", "src/b.cpp", "src/.hidden.cpp"])


def test_hidden_files_are_matched_like_pathlib_does(tree):
    assert "src/.hidden.cpp" in rel(tree, globber.expand(str(tree), ["src/*.cpp"]))


def test_missing_root_yields_nothing(tmp_path):
    assert globber.expand(str(tmp_path / "nope"), ["**/*.cpp"]) == set()


def test_expand_sorted_with_exclude(tree):
    got = globber.expand_sorted(str(tree), ["**/*.cpp"], exclude=["test/*.cpp", "src/deep/**/*"])
    names = rel(tree, got)
    assert "test/t1.cpp" not in names and "src/deep/c.cpp" not in names and "main.cpp" in names


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive file systems only")
def test_matching_is_case_insensitive_on_windows(tree):
    assert rel(tree, globber.expand(str(tree), ["*.CPP"])) == ["main.cpp", "util.cpp"]
