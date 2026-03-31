"""Codex CLI backend — invokes ``codex exec`` as a subprocess.

This is a deferred/MVP stub.  The interface is implemented but will be
fleshed out after the Claude backend is proven.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from cowork.backends.base import Backend, BackendResult
from cowork.errors import BackendError, WorkerProcessError, WorkerTimeout


class CodexBackend(Backend):
    """Runs ``codex exec --json`` and parses JSONL output."""

    SANDBOX_DEFAULT = "full-auto"

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
        cmd = [
            "codex",
            "exec",
            "--json",
            "--ephemeral",
            "-s",
            self.SANDBOX_DEFAULT,
        ]
        if model:
            cmd.extend(["--model", model])
        if json_schema is not None:
            # codex uses --output-schema FILE, but we inline via temp approach
            cmd.extend(["--output-schema-inline", json.dumps(json_schema)])
        # Prompt goes as positional arg
        cmd.append(prompt)
        return cmd

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
        cmd = self.build_command(
            prompt,
            model=model,
            system_prompt=system_prompt,
            json_schema=json_schema,
        )

        t0 = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            raise WorkerTimeout(
                f"codex process timed out after {timeout_seconds}s",
            )
        except FileNotFoundError:
            raise BackendError(
                "codex CLI not found — is it installed and on PATH?",
                backend="codex",
            )

        duration = time.monotonic() - t0
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")

        if proc.returncode != 0:
            raise WorkerProcessError(
                f"codex exited with code {proc.returncode}: {stderr[:500]}",
                exit_code=proc.returncode,
                stderr=stderr,
            )

        return self._parse_jsonl(stdout, duration=duration)

    @staticmethod
    def _parse_jsonl(raw: str, *, duration: float = 0.0) -> BackendResult:
        """Parse JSONL output from codex exec --json."""
        lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
        last_data: dict[str, Any] = {}
        for line in lines:
            try:
                last_data = json.loads(line)
            except json.JSONDecodeError:
                continue

        if not last_data:
            return BackendResult(
                success=False,
                raw_result=raw[:2000],
                error="No valid JSON lines in codex output",
                duration_seconds=duration,
            )

        return BackendResult(
            success=True,
            structured_output=last_data.get("structured_output"),
            raw_result=last_data.get("result", ""),
            cost_usd=float(last_data.get("cost_usd", 0.0)),
            duration_seconds=duration,
            metadata=last_data,
        )
