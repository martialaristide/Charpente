import pytest

from charpente.errors import ChValueError
from charpente.semver import Constraint, Version


def V(text):
    return Version.parse(text)


@pytest.mark.parametrize("text,expected", [
    ("1.2.3", (1, 2, 3)), ("v1.2.3", (1, 2, 3)), ("1.2", (1, 2, 0)), ("1", (1, 0, 0)), ("0.0.1", (0, 0, 1)),
    ("1.2.3+build5", (1, 2, 3)),
])
def test_parse(text, expected):
    v = V(text)
    assert (v.major, v.minor, v.patch) == expected


@pytest.mark.parametrize("text", ["", "a.b.c", "1.2.3.4", "01.2.3", "1..2", "-1.0.0", "1.2.3-", "x"])
def test_invalid_versions_are_rejected_with_a_code(text):
    with pytest.raises(ChValueError) as exc:
        Version.parse(text)
    assert exc.value.code == "CH7001"


def test_ordering_follows_semver():
    ordered = ["0.9.0", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
               "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.1.0", "2.0.0"]
    versions = [V(t) for t in ordered]
    assert versions == sorted(versions)
    assert V("1.0.0-rc.1") < V("1.0.0")
    assert V("1.2.10") > V("1.2.9")               # numeric, not lexicographic


def test_str_round_trip():
    assert str(V("1.2")) == "1.2.0" and str(V("1.0.0-rc.1")) == "1.0.0-rc.1"


@pytest.mark.parametrize("constraint,version,ok", [
    ("^1.2.3", "1.2.3", True), ("^1.2.3", "1.9.9", True), ("^1.2.3", "2.0.0", False), ("^1.2.3", "1.2.2", False),
    ("^0.2.3", "0.2.9", True), ("^0.2.3", "0.3.0", False),
    ("^0.0.3", "0.0.3", True), ("^0.0.3", "0.0.4", False),
    ("^1.1", "1.1.0", True), ("^1.1", "1.5.0", True), ("^1.1", "2.0.0", False),
    ("1.2", "1.9.0", True),                                  # bare = caret
    ("~1.2.3", "1.2.9", True), ("~1.2.3", "1.3.0", False), ("~1.2", "1.2.7", True), ("~1", "1.9.0", True),
    ("~1", "2.0.0", False),
    (">=1.0,<2.0", "1.5.0", True), (">=1.0,<2.0", "2.0.0", False), (">1.0", "1.0.0", False),
    ("<=2.0.0", "2.0.0", True), ("!=1.5.0", "1.5.0", False), ("!=1.5.0", "1.5.1", True),
    ("=1.2.3", "1.2.3", True), ("=1.2.3", "1.2.4", False), ("=1.2", "1.2.9", True), ("=1", "1.9.9", True),
    ("*", "9.9.9", True), ("", "0.0.1", True),
])
def test_constraints(constraint, version, ok):
    assert Constraint.parse(constraint).matches(version) is ok


def test_prereleases_only_match_constraints_that_name_one():
    assert not Constraint.parse("^1.0").matches("1.1.0-beta")
    assert Constraint.parse(">=1.1.0-beta").matches("1.1.0-beta.2")


@pytest.mark.parametrize("bad", ["^", "~x", ">=", "^1.2.3.4", "1.0,,2.0", "@1"])
def test_invalid_constraints_are_rejected_with_a_code(bad):
    with pytest.raises(ChValueError) as exc:
        Constraint.parse(bad)
    assert exc.value.code == "CH7002"


def test_best_picks_the_highest_matching_version():
    c = Constraint.parse("^1.2")
    assert c.best(["1.1.0", "1.2.0", "1.10.0", "1.9.9", "2.0.0", "1.11.0-rc.1"]) == "1.10.0"
    assert c.best(["3.0.0"]) is None
    assert str(c) == "^1.2"
