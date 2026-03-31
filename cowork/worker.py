"""Worker — builds prompt, calls backend, validates output."""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from cowork.backends.base import Backend, BackendResult
from cowork.cost import CostTracker
from cowork.errors import WorkerParseError, WorkerTimeout
from cowork.roles import RoleDefinition
from cowork.state import SharedState

log = logging.getLogger(__name__)

MAX_RETRIES = 1  # one retry on parse / timeout errors


class WorkerResult:
    """Holds the parsed model + raw backend result."""

    def __init__(
        self,
        parsed: BaseModel,
        backend_result: BackendResult,
        worker_id: str,
        role: str,
    ) -> None:
        self.parsed = parsed
        self.backend_result = backend_result
        self.worker_id = worker_id
        self.role = role

    @property
    def cost_usd(self) -> float:
        return self.backend_result.cost_usd

    @property
    def duration(self) -> float:
        return self.backend_result.duration_seconds


class Worker:
    """A single worker invocation for a given role.

    Parameters
    ----------
    role:
        The ``RoleDefinition`` to use.
    backend:
        The AI backend (claude / codex).
    worker_id:
        Unique identifier like ``"researcher-0"``.
    cwd:
        Working directory for the subprocess.
    """

    def __init__(
        self,
        role: RoleDefinition,
        backend: Backend,
        worker_id: str,
        cwd: str | None = None,
    ) -> None:
        self.role = role
        self.backend = backend
        self.worker_id = worker_id
        self.cwd = cwd

    async def run(
        self,
        state: SharedState,
        cost_tracker: CostTracker,
        *,
        extra_context: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> WorkerResult:
        """Execute the worker end-to-end.

        1. Build prompt from ``state.context_for_role()``
        2. Generate JSON schema from the role's Pydantic model
        3. Call backend
        4. Record cost
        5. Validate structured output

        Retries once on parse / timeout errors.
        """
        prompt = state.context_for_role(self.role.name, **(extra_context or {}))
        schema = self.role.output_schema.model_json_schema()

        if dry_run:
            cmd = self.backend.build_command(
                prompt,
                model=self.role.default_model,
                system_prompt=self.role.system_prompt,
                tools=self.role.default_tools,
                disallowed_tools=self.role.disallowed_tools,
                json_schema=schema,
                max_budget_usd=self.role.budget_per_worker,
            )
            log.info("[DRY RUN] %s command: %s", self.worker_id, cmd)
            # Return a synthetic result with defaults for required fields
            defaults: dict[str, Any] = {}
            for name, field in self.role.output_schema.model_fields.items():
                if field.default is not None:
                    continue
                annotation = field.annotation
                if annotation is str:
                    defaults[name] = ""
                elif annotation is bool:
                    defaults[name] = False
                elif annotation is int:
                    defaults[name] = 0
                elif annotation is float:
                    defaults[name] = 0.0
                elif hasattr(annotation, "__origin__") and annotation.__origin__ is list:
                    defaults[name] = []
            dummy = self.role.output_schema.model_construct(**defaults)
            return WorkerResult(
                parsed=dummy,
                backend_result=BackendResult(success=True),
                worker_id=self.worker_id,
                role=self.role.name,
            )

        last_error: Exception | None = None
        for attempt in range(1 + MAX_RETRIES):
            try:
                result = await self.backend.execute(
                    prompt,
                    model=self.role.default_model,
                    system_prompt=self.role.system_prompt,
                    tools=self.role.default_tools,
                    disallowed_tools=self.role.disallowed_tools,
                    json_schema=schema,
                    max_budget_usd=self.role.budget_per_worker,
                    timeout_seconds=self.role.timeout_seconds,
                    cwd=self.cwd,
                )

                # Record cost regardless of parse success
                cost_tracker.record(
                    role=self.role.name,
                    worker_id=self.worker_id,
                    cost_usd=result.cost_usd,
                )

                parsed = self._validate_output(result)
                return WorkerResult(
                    parsed=parsed,
                    backend_result=result,
                    worker_id=self.worker_id,
                    role=self.role.name,
                )

            except (WorkerParseError, WorkerTimeout) as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    log.warning(
                        "%s attempt %d failed (%s), retrying…",
                        self.worker_id,
                        attempt + 1,
                        type(exc).__name__,
                    )
                    continue
                raise

        # Should not reach here, but satisfy type checker
        assert last_error is not None
        raise last_error

    # ── Validation ───────────────────────────────────────────────────────

    def _validate_output(self, result: BackendResult) -> BaseModel:
        """Validate and return the parsed Pydantic model."""
        data = result.structured_output
        if data is None:
            raise WorkerParseError(
                f"No structured_output from {self.worker_id}; "
                f"raw result: {result.raw_result[:300]}",
                role=self.role.name,
                worker_id=self.worker_id,
            )
        try:
            return self.role.output_schema.model_validate(data)
        except ValidationError as exc:
            raise WorkerParseError(
                f"Schema validation failed for {self.worker_id}: {exc}",
                role=self.role.name,
                worker_id=self.worker_id,
            ) from exc
