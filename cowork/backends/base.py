"""Abstract backend interface."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BackendResult:
    """Result returned from any backend execution."""

    success: bool
    structured_output: dict[str, Any] | None = None
    raw_result: str = ""
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    error: str = ""
    exit_code: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class Backend(abc.ABC):
    """ABC that all backends must implement."""

    @abc.abstractmethod
    async def execute(
        self,
        prompt: str,
        *,
        model: str = "",
        system_prompt: str = "",
        tools: str = "",
        disallowed_tools: str = "",
        json_schema: dict[str, Any] | None = None,
        max_budget_usd: float | None = None,
        timeout_seconds: int = 300,
        cwd: str | None = None,
    ) -> BackendResult:
        """Run a prompt and return structured output.

        Parameters
        ----------
        prompt:
            The user-level prompt to send.
        model:
            Model identifier (e.g. "sonnet", "opus", "haiku").
        system_prompt:
            System-level instructions.
        tools:
            Comma-separated allowed tool names, or "default".
        disallowed_tools:
            Comma-separated disallowed tool names.
        json_schema:
            JSON Schema dict to enforce structured output.
        max_budget_usd:
            Per-invocation budget cap.
        timeout_seconds:
            Hard timeout for the subprocess.
        cwd:
            Working directory for the subprocess.
        """

    @abc.abstractmethod
    def build_command(
        self,
        prompt: str,
        *,
        model: str = "",
        system_prompt: str = "",
        tools: str = "",
        disallowed_tools: str = "",
        json_schema: dict[str, Any] | None = None,
        max_budget_usd: float | None = None,
    ) -> list[str]:
        """Return the CLI command list (for dry-run / debugging)."""
