"""JSON Schema generation for events (published under docs/events/)."""
from __future__ import annotations

import json
from typing import Any, Dict

from .types import EVENT_TYPES, SCHEMA_VERSION, field_spec

_JSON_TYPES: Dict[str, Dict[str, Any]] = {
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "list": {"type": "array"},
    "dict": {"type": "object"},
    "any": {},
}

DIALECT = "https://json-schema.org/draft/2020-12/schema"


def payload_schema(event_type: str) -> Dict[str, Any]:
    spec = EVENT_TYPES[event_type]
    properties: Dict[str, Any] = {}
    required = []
    for name, raw in spec.items():
        type_name, optional = field_spec(raw)
        schema: Dict[str, Any] = dict(_JSON_TYPES[type_name])
        if optional and "type" in schema:
            schema = {"type": [schema["type"], "null"]}
        properties[name] = schema
        if not optional:
            required.append(name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        # New optional fields may be added without a schema_version bump.
        "additionalProperties": True,
    }


def event_schema(event_type: str) -> Dict[str, Any]:
    """Full schema of one event (envelope + payload)."""
    return {
        "$schema": DIALECT,
        "$id": f"https://charpente.dev/schemas/events/v{SCHEMA_VERSION}/{event_type}.json",
        "title": event_type,
        "type": "object",
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "id": {"type": "integer", "minimum": 1},
            "parent_id": {"type": ["integer", "null"]},
            "timestamp": {"type": "number"},
            "wall_time": {"type": "number"},
            "session_id": {"type": "string"},
            "type": {"const": event_type},
            "payload": payload_schema(event_type),
        },
        "required": ["schema_version", "id", "parent_id", "timestamp", "wall_time",
                     "session_id", "type", "payload"],
    }


def any_event_schema() -> Dict[str, Any]:
    """One schema accepting any known event: what a JSONL consumer validates lines against."""
    return {
        "$schema": DIALECT,
        "$id": f"https://charpente.dev/schemas/events/v{SCHEMA_VERSION}/event.json",
        "title": "Charpente event",
        "oneOf": [event_schema(t) for t in EVENT_TYPES],
    }


def dumps(schema: Dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"
