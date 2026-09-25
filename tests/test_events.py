import dataclasses
import json
import threading
import time

import pytest

from charpente.events import EVENT_TYPES, EventBus
from charpente.events import schema as event_schema
from charpente.events.types import families, field_spec


@pytest.fixture
def bus():
    b = EventBus(session_id="s1", strict=True)
    yield b
    b.close()


def test_events_are_delivered_in_order_to_a_sync_subscriber(bus):
    seen = []
    bus.subscribe(lambda e: seen.append(e.id), sync=True)
    for i in range(5):
        bus.emit("target.started", target=f"t{i}", actions=1)
    assert seen == [1, 2, 3, 4, 5]


def test_event_envelope_fields(bus):
    ev = bus.emit("session.started", command="build", argv=["build"], cwd=".", version="1")
    assert ev.session_id == "s1" and ev.id == 1 and ev.parent_id is None
    assert ev.schema_version == 1 and ev.family == "session"
    child = bus.emit("workspace.loading", parent_id=ev.id, path="x")
    assert child.parent_id == ev.id and child.timestamp >= ev.timestamp


def test_event_payload_is_immutable(bus):
    ev = bus.emit("target.started", target="t", actions=1)
    with pytest.raises(TypeError):
        ev.payload["target"] = "other"  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.type = "x"  # type: ignore[misc]


def test_to_dict_is_json_serialisable(bus):
    ev = bus.emit("action.failed", action="a", target="t", kind="compile", returncode=1, duration=0.1, output="boom")
    text = json.dumps(ev.to_dict())
    assert json.loads(text)["payload"]["output"] == "boom"


def test_async_subscriber_receives_everything_after_close():
    b = EventBus(strict=True)
    seen = []
    b.subscribe(lambda e: seen.append(e.type), name="a")
    for _ in range(100):
        b.emit("target.started", target="t", actions=1)
    stats = b.close()
    assert len(seen) == 100 and stats.emitted == 100 and not stats.dropped


def test_slow_subscriber_never_blocks_the_emitter_and_drops_are_counted():
    b = EventBus(strict=True)
    gate = threading.Event()
    received = []

    def slow(e):
        gate.wait(5)
        received.append(e.id)

    b.subscribe(slow, name="slow", maxsize=3)
    start = time.monotonic()
    for _ in range(50):
        b.emit("target.started", target="t", actions=1)
    assert time.monotonic() - start < 1.0          # the emitter never waited
    gate.set()
    stats = b.close()
    assert stats.dropped["slow"] >= 40
    assert len(received) + stats.dropped["slow"] == 50
    assert received == sorted(received)            # order preserved for what was delivered


def test_failing_subscriber_is_isolated_and_recorded():
    b = EventBus(strict=True)
    good = []

    def bad(_):
        raise RuntimeError("nope")

    b.subscribe(bad, sync=True, name="bad")
    b.subscribe(good.append, sync=True, name="good")
    b.emit("target.started", target="t", actions=1)
    assert len(good) == 1
    assert "nope" in b.stats().errors["bad"][0]
    b.close()


def test_type_filters_use_patterns(bus):
    seen = []
    bus.subscribe(lambda e: seen.append(e.type), sync=True, types=["action.*", "session.finished"])
    bus.emit("target.started", target="t", actions=1)
    bus.emit("action.queued", action="a", target="t", kind="compile")
    bus.emit("session.finished", ok=True, duration=1.0)
    assert seen == ["action.queued", "session.finished"]


def test_unsubscribe_stops_delivery(bus):
    seen = []
    sub = bus.subscribe(seen.append, sync=True)
    bus.emit("target.started", target="t", actions=1)
    sub.unsubscribe()
    bus.emit("target.started", target="t", actions=1)
    assert len(seen) == 1


def test_a_sync_handler_may_emit_without_deadlock(bus):
    def relay(e):
        if e.type == "target.started":
            bus.emit("target.up_to_date", target="t")

    bus.subscribe(relay, sync=True)
    seen = []
    bus.subscribe(lambda e: seen.append(e.type), sync=True)
    bus.emit("target.started", target="t", actions=1)
    assert "target.up_to_date" in seen


def test_concurrent_emitters_keep_per_subscriber_order():
    b = EventBus(strict=True)
    seen = []
    b.subscribe(lambda e: seen.append(e.id), name="ordered")

    def work():
        for _ in range(200):
            b.emit("target.started", target="t", actions=1)

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    b.close()
    assert seen == sorted(seen) and len(seen) == 800


def test_emit_after_close_is_ignored_not_fatal():
    b = EventBus(strict=True)
    b.close()
    b.emit("target.started", target="t", actions=1)


# ------------------------------------------------------------- strict validation
def test_strict_mode_rejects_unknown_types_missing_and_mistyped_fields(bus):
    with pytest.raises(ValueError, match="unknown"):
        bus.emit("nope.nothing")
    with pytest.raises(ValueError, match="missing"):
        bus.emit("target.started", target="t")
    with pytest.raises(ValueError, match="expected int"):
        bus.emit("target.started", target="t", actions="3")
    with pytest.raises(ValueError, match="got bool"):
        bus.emit("target.started", target="t", actions=True)


def test_optional_fields_may_be_omitted_or_none(bus):
    bus.emit("target.finished", target="t", duration=0.1, executed=1, cached=0, up_to_date=0)
    bus.emit("target.finished", target="t", output=None, duration=0.1, executed=1, cached=0, up_to_date=0)


def test_non_strict_bus_accepts_anything():
    b = EventBus(strict=False)
    b.emit("whatever", x=1)
    b.close()


def test_every_type_belongs_to_a_known_family_and_has_valid_specs():
    assert set(families()) >= {"session", "workspace", "graph", "action", "target", "diagnostic",
                               "test", "gate", "pkg", "vcs", "deploy", "resource", "hint"}
    for name, spec in EVENT_TYPES.items():
        assert "." in name
        for raw in spec.values():
            field_spec(raw)


# ------------------------------------------------------------- JSON Schemas
def _sample(spec):
    samples = {"str": "x", "int": 1, "float": 1.5, "bool": True, "list": [], "dict": {}, "any": 1}
    return {n: samples[field_spec(r)[0]] for n, r in spec.items() if not field_spec(r)[1]}


def test_every_emitted_event_validates_against_its_published_schema():
    jsonschema = pytest.importorskip("jsonschema")
    b = EventBus(strict=True)
    events = []
    b.subscribe(events.append, sync=True)
    for name, spec in EVENT_TYPES.items():
        b.emit(name, **_sample(spec))
    b.close()
    assert len(events) == len(EVENT_TYPES)
    combined = jsonschema.Draft202012Validator(event_schema.any_event_schema())
    for ev in events:
        data = json.loads(json.dumps(ev.to_dict()))
        jsonschema.Draft202012Validator(event_schema.event_schema(ev.type)).validate(data)
        combined.validate(data)


def test_schema_rejects_a_malformed_event():
    jsonschema = pytest.importorskip("jsonschema")
    b = EventBus(strict=True)
    ev = b.emit("target.started", target="t", actions=1).to_dict()
    ev["payload"]["actions"] = "many"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(ev, event_schema.event_schema("target.started"))
    b.close()


def test_optional_fields_accept_null_in_the_schema():
    jsonschema = pytest.importorskip("jsonschema")
    b = EventBus(strict=True)
    ev = b.emit("target.finished", target="t", output=None, duration=0.0, executed=0, cached=0, up_to_date=1)
    jsonschema.validate(json.loads(json.dumps(ev.to_dict())), event_schema.event_schema("target.finished"))
    b.close()


def test_generated_event_docs_are_up_to_date():
    import importlib.util
    from pathlib import Path

    tool = Path(__file__).resolve().parent.parent / "tools" / "gen_event_docs.py"
    spec = importlib.util.spec_from_file_location("gen_event_docs", tool)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--check"]) == 0
