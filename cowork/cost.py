"""Cost tracking and budget enforcement."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

from cowork.errors import BudgetExceeded, WorkerBudgetExceeded


@dataclass
class CostEntry:
    """Single cost record."""

    role: str
    worker_id: str
    cost_usd: float
    timestamp: float = field(default_factory=time.time)


class CostTracker:
    """Thread-safe cost accumulator with budget enforcement.

    Parameters
    ----------
    max_total_usd:
        Hard budget ceiling.  ``check_budget()`` raises ``BudgetExceeded``
        when cumulative spend reaches this value.
    """

    def __init__(self, max_total_usd: float = 5.0) -> None:
        self.max_total_usd = max_total_usd
        self._entries: list[CostEntry] = []
        self._lock = Lock()

    # ── Recording ────────────────────────────────────────────────────────

    def record(self, role: str, worker_id: str, cost_usd: float) -> None:
        """Append a cost entry (thread-safe)."""
        with self._lock:
            self._entries.append(
                CostEntry(role=role, worker_id=worker_id, cost_usd=cost_usd)
            )

    # ── Queries ──────────────────────────────────────────────────────────

    def total(self) -> float:
        """Total spend so far."""
        with self._lock:
            return sum(e.cost_usd for e in self._entries)

    def by_role(self) -> dict[str, float]:
        """Spend grouped by role name."""
        with self._lock:
            totals: dict[str, float] = {}
            for e in self._entries:
                totals[e.role] = totals.get(e.role, 0.0) + e.cost_usd
            return totals

    def by_worker(self) -> dict[str, float]:
        """Spend grouped by worker_id."""
        with self._lock:
            totals: dict[str, float] = {}
            for e in self._entries:
                totals[e.worker_id] = totals.get(e.worker_id, 0.0) + e.cost_usd
            return totals

    def budget_remaining(self) -> float:
        """Dollars remaining before budget ceiling."""
        return max(0.0, self.max_total_usd - self.total())

    @property
    def entries(self) -> list[CostEntry]:
        with self._lock:
            return list(self._entries)

    # ── Enforcement ──────────────────────────────────────────────────────

    def check_budget(self) -> None:
        """Raise ``BudgetExceeded`` if total spend >= ceiling."""
        spent = self.total()
        if spent >= self.max_total_usd:
            raise BudgetExceeded(spent=spent, budget=self.max_total_usd)

    @staticmethod
    def worker_budget(role: str, role_budget: float, already_spent: float) -> float:
        """Return the remaining budget for a single worker invocation.

        Raises ``WorkerBudgetExceeded`` if the role budget is already gone.
        """
        remaining = role_budget - already_spent
        if remaining <= 0:
            raise WorkerBudgetExceeded(
                f"Worker budget for {role} exhausted "
                f"(${already_spent:.2f} of ${role_budget:.2f})",
                role=role,
            )
        return remaining
