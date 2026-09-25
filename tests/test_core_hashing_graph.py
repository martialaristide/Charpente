from pathlib import Path

import pytest

from charpente.core import hashing
from charpente.core.actions import Action
from charpente.core.graph import ActionGraph, path_key
from charpente.errors import ChValueError


# ============================================================ hashing
def test_digest_has_algorithm_prefix_and_is_deterministic():
    d = hashing.digest_bytes(b"hello")
    assert d.startswith(("b3:", "b2:"))
    assert d == hashing.digest_bytes(b"hello")
    assert d != hashing.digest_bytes(b"hellO")


def test_parts_are_length_prefixed_so_boundaries_matter():
    assert hashing.digest_parts("ab", "c") != hashing.digest_parts("a", "bc")
    assert hashing.digest_parts("a", "") != hashing.digest_parts("a")
    assert hashing.digest_parts("x") == hashing.digest_parts(b"x")


def test_file_digest_equals_bytes_digest(tmp_path):
    f = tmp_path / "f.bin"
    data = bytes(range(256)) * 5000  # bigger than one read chunk
    f.write_bytes(data)
    assert hashing.digest_file(f, chunk=4096) == hashing.digest_bytes(data)


def test_fallback_algorithm_is_used_when_forced(monkeypatch):
    monkeypatch.setenv(hashing.HASH_ENV, "blake2")
    assert hashing.algorithm() == "b2"
    assert hashing.digest_bytes(b"x").startswith("b2:")
    monkeypatch.delenv(hashing.HASH_ENV)
    assert hashing.algorithm() in ("b2", "b3")


def test_digests_of_different_algorithms_never_collide(monkeypatch):
    monkeypatch.setenv(hashing.HASH_ENV, "blake2")
    b2 = hashing.digest_bytes(b"x")
    monkeypatch.delenv(hashing.HASH_ENV)
    if hashing.algorithm() == "b3":
        assert hashing.digest_bytes(b"x") != b2


def test_short_form():
    assert hashing.short("b3:" + "a" * 64, 8) == "b3:aaaaaaaa"


# ============================================================ graph
def A(id, out, inputs=(), after=(), kind="compile"):
    return Action(id=id, kind=kind, target="t", argv=("cc", id), outputs=(Path(out),),
                  inputs=tuple(Path(i) for i in inputs), after=tuple(after))


def test_edges_come_from_outputs_feeding_inputs():
    g = ActionGraph([A("c1", "a.o", ["a.c"]), A("c2", "b.o", ["b.c"]), A("l", "app", ["a.o", "b.o"])])
    assert g.deps["l"] == {"c1", "c2"}
    assert g.dependents["c1"] == {"l"}
    assert g.deps["c1"] == set()
    assert g.producer_of("a.o") == "c1"
    assert g.producer_of("a.c") is None


def test_topological_order_puts_dependencies_first_and_is_deterministic():
    actions = [A("l", "app", ["a.o", "b.o"]), A("c1", "a.o", ["a.c"]), A("c2", "b.o", ["b.c"])]
    order = ActionGraph(actions).topological_order()
    assert order.index("c1") < order.index("l") and order.index("c2") < order.index("l")
    assert order == ActionGraph(actions).topological_order()


def test_explicit_after_edges_are_honoured():
    g = ActionGraph([A("first", "x"), A("second", "y", after=["first"])])
    assert g.deps["second"] == {"first"}


def test_unknown_after_is_rejected():
    with pytest.raises(ChValueError) as exc:
        ActionGraph([A("a", "x", after=["ghost"])])
    assert exc.value.code == "CH3011"


def test_two_actions_writing_the_same_file_are_rejected():
    with pytest.raises(ChValueError) as exc:
        ActionGraph([A("a", "same.o"), A("b", "same.o")])
    assert exc.value.code == "CH3010"


def test_duplicate_ids_are_rejected():
    with pytest.raises(ChValueError) as exc:
        ActionGraph([A("a", "x"), A("a", "y")])
    assert exc.value.code == "CH3013"


def test_cycles_are_reported_with_the_actions_involved():
    with pytest.raises(ChValueError) as exc:
        ActionGraph([A("a", "a.out", ["b.out"]), A("b", "b.out", ["a.out"])])
    assert exc.value.code == "CH3012"
    assert "a" in str(exc.value) and "b" in str(exc.value)


def test_a_self_referencing_input_is_not_a_cycle():
    ActionGraph([A("a", "a.out", ["a.out"])])  # reads its own previous output: ignored


def test_closure_and_descendants():
    g = ActionGraph([A("c1", "a.o", ["a.c"]), A("c2", "b.o", ["b.c"]), A("l", "app", ["a.o", "b.o"]),
                     A("pkg", "app.zip", ["app"])])
    assert g.closure(["l"]) == {"l", "c1", "c2"}
    assert g.descendants(["c1"]) == {"l", "pkg"}
    assert g.closure(["nope"]) == set()


def test_subgraph_drops_ordering_edges_to_excluded_actions():
    g = ActionGraph([A("a", "x"), A("b", "y", after=["a"]), A("c", "z")])
    sub = g.subgraph(["b", "c"])
    assert set(sub.actions) == {"b", "c"} and sub.deps["b"] == set()


def test_critical_path_uses_the_longest_chain():
    g = ActionGraph([A("c1", "a.o", ["a.c"]), A("c2", "b.o", ["b.c"]), A("l", "app", ["a.o", "b.o"])])
    total, chain = g.critical_path({"c1": 5.0, "c2": 1.0, "l": 2.0})
    assert total == 7.0 and chain == ["c1", "l"]
    pr = g.priorities({"c1": 5.0, "c2": 1.0, "l": 2.0})
    assert pr["c1"] > pr["c2"]  # the slow chain is scheduled first


def test_empty_graph():
    g = ActionGraph([])
    assert g.critical_path() == (0.0, []) and g.topological_order() == []


def test_path_key_is_absolute_and_stable():
    assert path_key("a/../b") == path_key("b")
    assert Path(path_key("x")).is_absolute()


# ============================================================ Action validation
def test_action_validation():
    with pytest.raises(ValueError):
        Action(id="", kind="c", target="t", argv=("x",), outputs=(Path("o"),))
    with pytest.raises(ValueError):
        Action(id="a", kind="c", target="t", argv=(), outputs=(Path("o"),))
    with pytest.raises(ValueError):
        Action(id="a", kind="c", target="t", argv=("x",), outputs=())
    with pytest.raises(ValueError):
        Action(id="a", kind="c", target="t", argv=("x",), outputs=(Path("o"),), dep_format="gnu")
    with pytest.raises(ValueError):
        Action(id="a", kind="c", target="t", argv=("x",), outputs=(Path("o"),), dep_format="nope")
    assert Action(id="a", kind="c", target="t", argv=("x",), outputs=(Path("o"),)).label() == "a"
