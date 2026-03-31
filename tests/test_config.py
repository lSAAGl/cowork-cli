"""Tests for configuration loading and merging."""

import pytest
from pathlib import Path

from cowork.config import (
    CoworkConfig,
    RoleConfig,
    SupervisorConfig,
    _deep_merge,
    load_config,
)
from cowork.errors import ConfigError


class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3}
        assert _deep_merge(base, override) == {"a": 1, "b": 3}

    def test_nested_merge(self):
        base = {"x": {"a": 1, "b": 2}}
        override = {"x": {"b": 3, "c": 4}}
        result = _deep_merge(base, override)
        assert result == {"x": {"a": 1, "b": 3, "c": 4}}

    def test_new_keys(self):
        base = {"a": 1}
        override = {"b": 2}
        assert _deep_merge(base, override) == {"a": 1, "b": 2}


class TestLoadConfig:
    def test_defaults_load(self):
        cfg = load_config(cli_overrides={})
        assert isinstance(cfg, CoworkConfig)
        assert cfg.supervisor.max_iterations == 5
        assert cfg.supervisor.backend == "claude"

    def test_cli_override_budget(self):
        cfg = load_config(cli_overrides={"supervisor.max_total_cost_usd": 2.0})
        assert cfg.supervisor.max_total_cost_usd == 2.0

    def test_cli_override_verbose(self):
        cfg = load_config(cli_overrides={"verbose": True})
        assert cfg.verbose is True

    def test_nonexistent_config_file_uses_defaults(self):
        cfg = load_config(config_file=Path("/nonexistent/cowork.toml"))
        assert cfg.supervisor.max_iterations == 5


class TestModels:
    def test_supervisor_config_defaults(self):
        sc = SupervisorConfig()
        assert sc.max_iterations == 5
        assert sc.backend == "claude"

    def test_role_config_defaults(self):
        rc = RoleConfig()
        assert rc.model == ""
        assert rc.max_workers == 1
