"""Tests for imail.agent — build_schema and guide_text."""

from __future__ import annotations

import json

from imail import __version__
from imail import agent


def test_build_schema_structure() -> None:
    schema = agent.build_schema()
    assert schema["version"] == __version__
    assert schema["tool"] == "imail"
    assert "work" in schema["walls"]
    assert "personal" in schema["walls"]
    assert isinstance(schema["commands"], list)
    names = {cmd["name"] for cmd in schema["commands"]}
    assert "list" in names
    assert "send" in names
    assert "agent schema" in names


def test_schema_json_is_valid_json() -> None:
    data = json.loads(agent.schema_json())
    assert data["tool"] == "imail"


def test_guide_text_includes_rules_and_commands() -> None:
    text = agent.guide_text()
    assert "imail — Apple Mail.app CLI" in text
    assert "imail doctor" in text
    assert "imail agent schema" in text
    assert "•" in text
