"""Supervisor — the orchestration brain.

Runs the observe-plan-act-reflect loop with automatic fix cycles
and escalation (re-plan after N consecutive fix failures).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from cowork.backends import Backend, ClaudeBackend
from cowork.backends.codex import CodexBackend
from cowork.config import CoworkConfig
from cowork.cost import CostTracker
from cowork.display import Display
from cowork.errors import BudgetExceeded, MaxIterationsExceeded
from cowork.roles import RoleDefinition, get_role
from cowork.schemas import (
    FixResult,
    ImplementationPlan,
    ImplementationResult,
    ResearchFinding,
    ReviewResult,
    TestResult,
)
from cowork.state import SharedState
from cowork.worker import Worker, WorkerResult

log = logging.getLogger(__name__)


def _make_backend(name: str) -> Backend:
    if name == "codex":
        return CodexBackend()
    return ClaudeBackend()


async def run_supervisor(
    task: str,
    config: CoworkConfig,
    *,
    cwd: str | None = None,
) -> SharedState:
    """Execute the full supervisor pipeline.

    Returns the final ``SharedState`` on success.
    Raises ``BudgetExceeded`` or ``MaxIterationsExceeded`` on failure.
    """
    state = SharedState(task=task)
    cost_tracker = CostTracker(config.supervisor.max_total_cost_usd)
    backend = _make_backend(config.supervisor.backend)
    display = Display(task=task, max_budget=config.supervisor.max_total_cost_usd)
    display.max_iterations = config.supervisor.max_iterations
    dry_run = config.dry_run

    def _get_role(name: str) -> RoleDefinition:
        override = config.roles.get(name)
        return get_role(name, override)

    async def _spawn_worker(
        role_name: str,
        worker_id: str,
        extra_context: dict[str, Any] | None = None,
    ) -> WorkerResult:
        """Create and run a single worker, updating display."""
        role_def = _get_role(role_name)
        ws = display.add_worker(worker_id)
        ws.mark_running()
        display.refresh()

        worker = Worker(
            role=role_def,
            backend=backend,
            worker_id=worker_id,
            cwd=cwd,
        )
        try:
            result = await worker.run(
                state,
                cost_tracker,
                extra_context=extra_context,
                dry_run=dry_run,
            )
            ws.mark_done(cost=result.cost_usd)
        except Exception:
            ws.mark_error(cost=0.0)
            raise
        finally:
            display.set_cost(cost_tracker.total())
            display.refresh()

        return result

    with display:
        # ── PHASE 1: RESEARCH ────────────────────────────────────────────
        state.current_phase = "RESEARCH"
        display.set_phase("RESEARCH")

        researcher_role = _get_role("researcher")
        num_researchers = min(researcher_role.max_workers, 2)

        research_results = await asyncio.gather(
            *[
                _spawn_worker("researcher", f"researcher-{i}")
                for i in range(num_researchers)
            ]
        )

        for wr in research_results:
            assert isinstance(wr.parsed, ResearchFinding)
            state.research_findings.append(wr.parsed)

        cost_tracker.check_budget()

        # ── PHASE 2: PLAN ────────────────────────────────────────────────
        state.current_phase = "PLAN"
        display.set_phase("PLAN")

        plan_result = await _spawn_worker("planner", "planner-0")
        assert isinstance(plan_result.parsed, ImplementationPlan)
        state.implementation_plan = plan_result.parsed

        cost_tracker.check_budget()

        # ── ITERATION LOOP ───────────────────────────────────────────────
        consecutive_fix_failures = 0
        replan_threshold = config.supervisor.consecutive_fix_failures_before_replan

        for iteration in range(1, config.supervisor.max_iterations + 1):
            state.current_iteration = iteration

            # ── PHASE 3: IMPLEMENT ───────────────────────────────────────
            state.current_phase = "IMPLEMENT"
            display.set_phase("IMPLEMENT", iteration)

            plan = state.implementation_plan
            assert plan is not None

            # Build parallel groups from the plan
            groups = plan.parallel_groups
            if not groups:
                # Fall back: all steps in one group
                from cowork.schemas import ParallelGroup
                groups = [ParallelGroup(step_ids=[s.id for s in plan.steps])]

            impl_worker_idx = 0
            state.implementation_results.clear()

            for group in groups:
                # Each group can have up to max_workers implementers
                impl_role = _get_role("implementer")
                chunk_size = max(
                    1,
                    len(group.step_ids) // impl_role.max_workers,
                )
                chunks = _chunk_list(group.step_ids, chunk_size)

                coros = []
                for chunk in chunks:
                    wid = f"implementer-{impl_worker_idx}"
                    impl_worker_idx += 1
                    coros.append(
                        _spawn_worker(
                            "implementer",
                            wid,
                            extra_context={"assigned_steps": chunk},
                        )
                    )

                impl_results = await asyncio.gather(*coros)
                for wr in impl_results:
                    assert isinstance(wr.parsed, ImplementationResult)
                    state.implementation_results.append(wr.parsed)

            cost_tracker.check_budget()

            # ── PHASE 4: REVIEW ──────────────────────────────────────────
            state.current_phase = "REVIEW"
            display.set_phase("REVIEW", iteration)

            review_result = await _spawn_worker("reviewer", f"reviewer-{iteration}")
            assert isinstance(review_result.parsed, ReviewResult)
            state.review_result = review_result.parsed
            state.review_history.append(review_result.parsed)

            cost_tracker.check_budget()

            # ── PHASE 5: TEST ────────────────────────────────────────────
            state.current_phase = "TEST"
            display.set_phase("TEST", iteration)

            test_result = await _spawn_worker("tester", f"tester-{iteration}")
            assert isinstance(test_result.parsed, TestResult)
            state.test_result = test_result.parsed

            cost_tracker.check_budget()

            # ── DECISION ─────────────────────────────────────────────────
            if state.review_result.approved and state.test_result.all_passed:
                state.current_phase = "SUCCESS"
                display.set_phase("SUCCESS", iteration)
                display.log(
                    f"Task completed successfully on iteration {iteration}. "
                    f"Total cost: ${cost_tracker.total():.2f}"
                )
                return state

            # ── PHASE 6: FIX ─────────────────────────────────────────────
            state.current_phase = "FIX"
            display.set_phase("FIX", iteration)

            try:
                fix_result = await _spawn_worker("fixer", f"fixer-{iteration}")
                assert isinstance(fix_result.parsed, FixResult)
                state.fix_results.append(fix_result.parsed)

                if fix_result.parsed.remaining_issues:
                    consecutive_fix_failures += 1
                else:
                    consecutive_fix_failures = 0
            except Exception:
                consecutive_fix_failures += 1
                log.warning("Fix worker failed (consecutive: %d)", consecutive_fix_failures)

            cost_tracker.check_budget()

            # ── ESCALATION ───────────────────────────────────────────────
            if consecutive_fix_failures >= replan_threshold:
                display.log(
                    f"Escalating: {consecutive_fix_failures} consecutive fix failures. "
                    "Re-planning…"
                )
                state.clear_implementation()
                consecutive_fix_failures = 0

                # Re-plan with review history
                state.current_phase = "PLAN"
                display.set_phase("RE-PLAN", iteration)

                replan = await _spawn_worker("planner", f"planner-replan-{iteration}")
                assert isinstance(replan.parsed, ImplementationPlan)
                state.implementation_plan = replan.parsed

                cost_tracker.check_budget()

        # Exhausted iterations
        raise MaxIterationsExceeded(config.supervisor.max_iterations)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _chunk_list(items: list[str], chunk_size: int) -> list[list[str]]:
    """Split a list into chunks of at most *chunk_size*."""
    if chunk_size <= 0:
        return [items]
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]
