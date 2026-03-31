"""Tests for the Claude backend — command building and response parsing."""

import json

import pytest

from cowork.backends.claude import ClaudeBackend


@pytest.fixture
def backend():
    return ClaudeBackend()


class TestBuildCommand:
    def test_minimal(self, backend):
        cmd = backend.build_command("hello")
        assert cmd[:2] == ["claude", "-p"]
        assert "--bare" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd

    def test_with_model(self, backend):
        cmd = backend.build_command("hello", model="opus")
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "opus"

    def test_with_tools(self, backend):
        cmd = backend.build_command("hello", tools="Read,Glob,Grep")
        idx = cmd.index("--allowedTools")
        assert cmd[idx + 1] == "Read,Glob,Grep"

    def test_default_tools_not_added(self, backend):
        cmd = backend.build_command("hello", tools="default")
        assert "--allowedTools" not in cmd

    def test_with_disallowed_tools(self, backend):
        cmd = backend.build_command("hello", disallowed_tools="Edit,Write")
        idx = cmd.index("--disallowedTools")
        assert cmd[idx + 1] == "Edit,Write"

    def test_with_json_schema(self, backend):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        cmd = backend.build_command("hello", json_schema=schema)
        idx = cmd.index("--json-schema")
        parsed = json.loads(cmd[idx + 1])
        assert parsed == schema

    def test_with_budget(self, backend):
        cmd = backend.build_command("hello", max_budget_usd=0.50)
        idx = cmd.index("--max-budget-usd")
        assert cmd[idx + 1] == "0.5"

    def test_with_system_prompt(self, backend):
        cmd = backend.build_command("hello", system_prompt="You are helpful")
        idx = cmd.index("--system-prompt")
        assert cmd[idx + 1] == "You are helpful"

    def test_permission_mode(self, backend):
        cmd = backend.build_command("hello")
        idx = cmd.index("--permission-mode")
        assert cmd[idx + 1] == "bypassPermissions"


class TestParseResponse:
    def test_success_with_structured_output(self):
        raw = json.dumps({
            "type": "result",
            "subtype": "success",
            "result": "",
            "structured_output": {"summary": "hello"},
            "total_cost_usd": 0.05,
        })
        result = ClaudeBackend._parse_response(raw, duration=1.0)
        assert result.success
        assert result.structured_output == {"summary": "hello"}
        assert result.cost_usd == 0.05
        assert result.duration_seconds == 1.0

    def test_fallback_to_result_json(self):
        raw = json.dumps({
            "type": "result",
            "subtype": "success",
            "result": '{"summary": "from result"}',
            "structured_output": None,
            "total_cost_usd": 0.01,
        })
        result = ClaudeBackend._parse_response(raw)
        assert result.structured_output == {"summary": "from result"}

    def test_invalid_json(self):
        result = ClaudeBackend._parse_response("not json at all")
        assert not result.success
        assert "JSON decode error" in result.error

    def test_error_response(self):
        raw = json.dumps({
            "type": "result",
            "subtype": "error",
            "result": "Failed",
            "structured_output": None,
            "total_cost_usd": 0.001,
        })
        result = ClaudeBackend._parse_response(raw)
        assert not result.success
        assert result.structured_output is None
