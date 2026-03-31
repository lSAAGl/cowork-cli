"""Configuration loading with 3-layer merge.

Priority (lowest → highest):
    configs/default.toml  <  ./cowork.toml  <  CLI flags
"""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from cowork.errors import ConfigError

# ── Pydantic config models ───────────────────────────────────────────────────


class RoleConfig(BaseModel):
    """Per-role overrides."""

    model: str = ""
    tools: str = ""  # comma-separated allowed tools, or "default"
    disallowed_tools: str = ""  # comma-separated disallowed tools
    max_workers: int = 1
    budget_per_worker: float = 1.0
    timeout_seconds: int = 300


class SupervisorConfig(BaseModel):
    """Supervisor-level settings."""

    max_iterations: int = Field(default=5, ge=1)
    max_total_cost_usd: float = Field(default=5.0, gt=0)
    consecutive_fix_failures_before_replan: int = 3
    backend: str = "claude"


class CoworkConfig(BaseModel):
    """Top-level config combining supervisor + per-role settings."""

    supervisor: SupervisorConfig = Field(default_factory=SupervisorConfig)
    roles: dict[str, RoleConfig] = Field(default_factory=dict)

    # CLI-level overrides stored here for convenience
    verbose: bool = False
    dry_run: bool = False


# ── Defaults ─────────────────────────────────────────────────────────────────

_PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _PACKAGE_DIR / "configs" / "default.toml"


# ── Loading helpers ──────────────────────────────────────────────────────────


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file; return empty dict if missing."""
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except Exception as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base* (override wins)."""
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def load_config(
    config_file: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> CoworkConfig:
    """Build a ``CoworkConfig`` from the 3-layer merge.

    Parameters
    ----------
    config_file:
        Explicit config path (``--config`` flag).  Falls back to ``./cowork.toml``.
    cli_overrides:
        Flat dict of CLI flag overrides, e.g.
        ``{"supervisor.max_total_cost_usd": 2.0, "verbose": True}``.
    """
    # Layer 1: package defaults
    data = _load_toml(DEFAULT_CONFIG_PATH)

    # Layer 2: project-local config
    local_path = config_file or Path("cowork.toml")
    data = _deep_merge(data, _load_toml(local_path))

    # Layer 3: CLI flags
    if cli_overrides:
        for dotted_key, value in cli_overrides.items():
            _set_nested(data, dotted_key.split("."), value)

    try:
        return CoworkConfig.model_validate(data)
    except Exception as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc


def _set_nested(d: dict[str, Any], keys: list[str], value: Any) -> None:
    """Set a value in a nested dict using a list of keys."""
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value
