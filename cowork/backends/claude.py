"""Claude CLI backend — invokes ``claude -p`` as a subprocess."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from cowork.backends.base import Backend, BackendResult
from cowork.errors import BackendError, WorkerProcessError, WorkerTimeout


class ClaudeBackend(Backend):
    """Runs ``claude -p --output-format json`` and parses the response."""

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
            "claude",
            "-p",
            "--bare",
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "json",
        ]
        if model:
            cmd.extend(["--model", model])
        if tools and tools != "default":
            cmd.extend(["--allowedTools", tools])
        if disallowed_tools:
            cmd.extend(["--disallowedTools", disallowed_tools])
        if json_schema is not None:
            cmd.extend(["--json-schema", json.dumps(json_schema)])
        if max_budget_usd is not None:
            cmd.extend(["--max-budget-usd", str(max_budget_usd)])
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])
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
            tools=tools,
            disallowed_tools=disallowed_tools,
            json_schema=json_schema,
            max_budget_usd=max_budget_usd,
        )

        t0 = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=prompt.encode()),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            raise WorkerTimeout(
                f"claude process timed out after {timeout_seconds}s",
            )
        except FileNotFoundError:
            raise BackendError(
                "claude CLI not found — is it installed and on PATH?",
                backend="claude",
            )

        duration = time.monotonic() - t0
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")

        if proc.returncode != 0:
            raise WorkerProcessError(
                f"claude exited with code {proc.returncode}: "
                f"stderr={stderr[:500]} stdout={stdout[:500]}",
                exit_code=proc.returncode,
                stderr=stderr,
            )

        return self._parse_response(stdout, duration=duration)

    # ── Response parsing ─────────────────────────────────────────────────

    @staticmethod
    def _parse_response(raw: str, *, duration: float = 0.0) -> BackendResult:
        """Parse the JSON envelope from ``claude -p --output-format json``.

        The envelope looks like::

            {
              "type": "result",
              "subtype": "success",
              "result": "...",
              "structured_output": { ... },
              "total_cost_usd": 0.xx,
              ...
            }
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return BackendResult(
                success=False,
                raw_result=raw[:2000],
                error=f"JSON decode error: {exc}",
                duration_seconds=duration,
            )

        success = data.get("subtype") == "success"
        structured = data.get("structured_output")
        result_text = data.get("result", "")
        cost = float(data.get("total_cost_usd", 0.0))

        # Fallback: if structured_output is None, try parsing result as JSON
        if structured is None and result_text:
            try:
                structured = json.loads(result_text)
            except (json.JSONDecodeError, TypeError):
                pass

        return BackendResult(
            success=success,
            structured_output=structured,
            raw_result=result_text if isinstance(result_text, str) else str(result_text),
            cost_usd=cost,
            duration_seconds=duration,
            metadata=data,
        )
