"""Exception hierarchy for cowork."""

from __future__ import annotations


class CoworkError(Exception):
    """Base exception for all cowork errors."""


# ── Worker errors ────────────────────────────────────────────────────────────


class WorkerError(CoworkError):
    """Base for errors raised by or about a worker."""

    def __init__(self, message: str, role: str = "", worker_id: str = "") -> None:
        self.role = role
        self.worker_id = worker_id
        super().__init__(message)


class WorkerTimeout(WorkerError):
    """Worker process exceeded its time limit."""


class WorkerBudgetExceeded(WorkerError):
    """Worker exceeded its per-worker budget."""


class WorkerParseError(WorkerError):
    """Failed to parse structured output from worker."""


class WorkerProcessError(WorkerError):
    """Worker subprocess exited with non-zero status."""

    def __init__(
        self,
        message: str,
        role: str = "",
        worker_id: str = "",
        exit_code: int | None = None,
        stderr: str = "",
    ) -> None:
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(message, role=role, worker_id=worker_id)


# ── Supervisor / global errors ───────────────────────────────────────────────


class BudgetExceeded(CoworkError):
    """Total run budget exhausted."""

    def __init__(self, spent: float, budget: float) -> None:
        self.spent = spent
        self.budget = budget
        super().__init__(f"Budget exhausted: ${spent:.2f} spent of ${budget:.2f}")


class MaxIterationsExceeded(CoworkError):
    """Supervisor hit max iteration count without success."""

    def __init__(self, iterations: int) -> None:
        self.iterations = iterations
        super().__init__(f"Max iterations ({iterations}) reached without success")


class ConfigError(CoworkError):
    """Configuration loading or validation error."""


class BackendError(CoworkError):
    """Error from the AI backend (claude / codex)."""

    def __init__(self, message: str, backend: str = "") -> None:
        self.backend = backend
        super().__init__(message)
