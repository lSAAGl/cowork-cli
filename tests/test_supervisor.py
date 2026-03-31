"""Tests for the supervisor orchestration loop (mocked workers)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from cowork.backends.base import BackendResult
from cowork.config import CoworkConfig, SupervisorConfig
from cowork.errors import MaxIterationsExceeded, BudgetExceeded
from cowork.schemas import (
    ImplementationPlan,
    ImplementationResult,
    ParallelGroup,
    PlanStep,
    ResearchFinding,
    ReviewResult,
    TestResult,
)
from cowork.supervisor import run_supervisor, _chunk_list


class TestChunkList:
    def test_even_split(self):
        assert _chunk_list(["a", "b", "c", "d"], 2) == [["a", "b"], ["c", "d"]]

    def test_uneven_split(self):
        assert _chunk_list(["a", "b", "c"], 2) == [["a", "b"], ["c"]]

    def test_single_chunk(self):
        assert _chunk_list(["a", "b"], 5) == [["a", "b"]]

    def test_zero_chunk_size(self):
        assert _chunk_list(["a", "b"], 0) == [["a", "b"]]

    def test_empty(self):
        assert _chunk_list([], 3) == []


class TestSupervisorSuccess:
    """Test the happy path: research → plan → implement → review(approved) → test(pass)."""

    @pytest.mark.asyncio
    async def test_success_in_one_iteration(self):
        """Mock all workers to succeed on first iteration."""

        research = ResearchFinding(summary="Explored codebase", key_files=["main.py"])
        plan = ImplementationPlan(
            goal="Do thing",
            approach="Simple",
            steps=[PlanStep(id="s1", title="Step 1", description="Desc")],
            parallel_groups=[ParallelGroup(step_ids=["s1"])],
        )
        impl = ImplementationResult(step_ids_completed=["s1"], summary="Done")
        review = ReviewResult(approved=True, summary="LGTM")
        test = TestResult(all_passed=True, tests_run=1, tests_passed=1, summary="OK")

        call_count = 0

        async def mock_worker_run(self, state, cost_tracker, *, extra_context=None, dry_run=False):
            nonlocal call_count
            call_count += 1

            from cowork.worker import WorkerResult
            role_name = self.role.name
            parsed_map = {
                "researcher": research,
                "planner": plan,
                "implementer": impl,
                "reviewer": review,
                "tester": test,
            }
            parsed = parsed_map.get(role_name)
            if parsed is None:
                raise ValueError(f"Unexpected role: {role_name}")

            return WorkerResult(
                parsed=parsed,
                backend_result=BackendResult(success=True, cost_usd=0.01),
                worker_id=self.worker_id,
                role=role_name,
            )

        config = CoworkConfig(
            supervisor=SupervisorConfig(
                max_iterations=5,
                max_total_cost_usd=5.0,
            ),
        )

        with patch("cowork.worker.Worker.run", mock_worker_run):
            state = await run_supervisor("Do the thing", config)

        assert state.current_phase == "SUCCESS"
        assert len(state.research_findings) >= 1
        assert state.implementation_plan is not None
        assert state.review_result is not None
        assert state.review_result.approved
        assert state.test_result is not None
        assert state.test_result.all_passed
