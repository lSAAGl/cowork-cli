"""Rich terminal UI for the supervisor loop.

Falls back to plain print() if stdout is not a TTY or Rich is unavailable.
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Any, Generator

try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, TextColumn
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
except ImportError:
    HAS_RICH = False


# ── Worker status tracking ───────────────────────────────────────────────────


class WorkerStatus:
    """Mutable status of a single worker for the display table."""

    def __init__(self, worker_id: str) -> None:
        self.worker_id = worker_id
        self.status: str = "pending"  # pending | running | done | error
        self.cost_usd: float = 0.0
        self.started_at: float = 0.0
        self.finished_at: float = 0.0

    @property
    def duration(self) -> float:
        if self.started_at == 0:
            return 0.0
        end = self.finished_at if self.finished_at else time.time()
        return end - self.started_at

    def mark_running(self) -> None:
        self.status = "running"
        self.started_at = time.time()

    def mark_done(self, cost: float = 0.0) -> None:
        self.status = "done"
        self.cost_usd = cost
        self.finished_at = time.time()

    def mark_error(self, cost: float = 0.0) -> None:
        self.status = "error"
        self.cost_usd = cost
        self.finished_at = time.time()


# ── Display class ────────────────────────────────────────────────────────────


class Display:
    """Rich-based live dashboard, or plain fallback.

    Usage::

        display = Display(task="my task", max_budget=5.0)
        with display:
            display.set_phase("RESEARCH", iteration=0)
            ws = display.add_worker("researcher-0")
            ws.mark_running()
            ...
            ws.mark_done(cost=0.02)
            display.refresh()
    """

    def __init__(self, task: str, max_budget: float = 5.0) -> None:
        self.task = task
        self.max_budget = max_budget
        self.phase: str = ""
        self.iteration: int = 0
        self.max_iterations: int = 5
        self.workers: list[WorkerStatus] = []
        self.total_cost: float = 0.0
        self._live: Any = None
        self._use_rich = HAS_RICH and sys.stdout.isatty()

    def __enter__(self) -> Display:
        if self._use_rich:
            self._console = Console()
            self._live = Live(
                self._build_layout(),
                console=self._console,
                refresh_per_second=4,
            )
            self._live.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._live is not None:
            self._live.__exit__(*exc)

    # ── State setters ────────────────────────────────────────────────────

    def set_phase(self, phase: str, iteration: int = 0) -> None:
        self.phase = phase
        self.iteration = iteration
        self._log(f"── Phase: {phase}  Iteration: {iteration}/{self.max_iterations} ──")
        self.refresh()

    def add_worker(self, worker_id: str) -> WorkerStatus:
        ws = WorkerStatus(worker_id)
        self.workers.append(ws)
        return ws

    def set_cost(self, total: float) -> None:
        self.total_cost = total
        self.refresh()

    def log(self, msg: str) -> None:
        """Emit a log line (visible in plain mode; stored for rich)."""
        self._log(msg)

    def refresh(self) -> None:
        """Force a UI refresh."""
        if self._live is not None:
            self._live.update(self._build_layout())

    # ── Layout builder ───────────────────────────────────────────────────

    def _build_layout(self) -> Any:
        """Build the Rich renderable tree."""
        if not HAS_RICH:
            return ""

        # Header
        task_text = self.task[:80] + ("…" if len(self.task) > 80 else "")
        header = Panel(
            Text(task_text, style="bold cyan"),
            title="cowork",
            border_style="blue",
        )

        # Phase bar
        phase_text = Text(
            f"  Phase: {self.phase:<16s}  Iteration: {self.iteration}/{self.max_iterations}",
            style="bold",
        )

        # Worker table
        table = Table(show_header=True, header_style="bold", expand=True)
        table.add_column("Worker", min_width=20)
        table.add_column("Status", min_width=10)
        table.add_column("Cost", min_width=10, justify="right")
        table.add_column("Time", min_width=8, justify="right")

        status_styles = {
            "pending": ("⏳", "dim"),
            "running": ("⚡", "yellow"),
            "done": ("✓", "green"),
            "error": ("✗", "red"),
        }

        for ws in self.workers:
            icon, style = status_styles.get(ws.status, ("?", ""))
            table.add_row(
                ws.worker_id,
                Text(f"{icon} {ws.status}", style=style),
                f"${ws.cost_usd:.4f}",
                f"{ws.duration:.1f}s",
            )

        # Cost bar
        pct = (self.total_cost / self.max_budget * 100) if self.max_budget > 0 else 0
        cost_text = Text(
            f"  ${self.total_cost:.2f} / ${self.max_budget:.2f}  ({pct:.1f}%)",
            style="bold" if pct < 80 else "bold red",
        )

        from rich.console import Group
        return Group(header, phase_text, table, cost_text)

    # ── Fallback plain output ────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        if not self._use_rich:
            print(msg, flush=True)
