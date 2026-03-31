"""Tests for the Worker class with mocked backend."""

import pytest
from unittest.mock import AsyncMock

from cowork.backends.base import BackendResult
from cowork.cost import CostTracker
from cowork.errors import WorkerParseError
from cowork.roles import get_role
from cowork.state import SharedState
from cowork.worker import Worker


@pytest.fixture
def mock_backend():
    backend = AsyncMock()
    backend.build_command.return_value = ["claude", "-p", "--bare"]
    return backend


@pytest.fixture
def researcher_worker(mock_backend):
    role = get_role("researcher")
    return Worker(role=role, backend=mock_backend, worker_id="researcher-0")


@pytest.fixture
def state():
    return SharedState(task="Test task")


@pytest.fixture
def cost_tracker():
    return CostTracker(max_total_usd=5.0)


class TestWorkerRun:
    @pytest.mark.asyncio
    async def test_successful_run(self, researcher_worker, mock_backend, state, cost_tracker):
        mock_backend.execute.return_value = BackendResult(
            success=True,
            structured_output={
                "summary": "Found stuff",
                "key_files": ["a.py"],
                "patterns": [],
                "dependencies": [],
                "risks": [],
                "raw_notes": "",
            },
            cost_usd=0.02,
            duration_seconds=1.5,
        )

        result = await researcher_worker.run(state, cost_tracker)
        assert result.parsed.summary == "Found stuff"
        assert result.cost_usd == 0.02
        assert cost_tracker.total() == 0.02

    @pytest.mark.asyncio
    async def test_parse_error_retries(self, researcher_worker, mock_backend, state, cost_tracker):
        # First call: no structured output → parse error → retry
        # Second call: success
        mock_backend.execute.side_effect = [
            BackendResult(success=True, structured_output=None, raw_result="garbage", cost_usd=0.01),
            BackendResult(
                success=True,
                structured_output={"summary": "OK", "key_files": [], "patterns": [], "dependencies": [], "risks": [], "raw_notes": ""},
                cost_usd=0.02,
            ),
        ]

        result = await researcher_worker.run(state, cost_tracker)
        assert result.parsed.summary == "OK"
        assert mock_backend.execute.call_count == 2
        # Both calls recorded cost
        assert cost_tracker.total() == pytest.approx(0.03)

    @pytest.mark.asyncio
    async def test_parse_error_exhausts_retries(self, researcher_worker, mock_backend, state, cost_tracker):
        mock_backend.execute.return_value = BackendResult(
            success=True, structured_output=None, raw_result="bad", cost_usd=0.01
        )

        with pytest.raises(WorkerParseError):
            await researcher_worker.run(state, cost_tracker)

        # 1 original + 1 retry = 2
        assert mock_backend.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_dry_run(self, researcher_worker, mock_backend, state, cost_tracker):
        result = await researcher_worker.run(state, cost_tracker, dry_run=True)
        assert result.backend_result.success is True
        mock_backend.execute.assert_not_called()


class TestWorkerContextPassing:
    @pytest.mark.asyncio
    async def test_implementer_gets_assigned_steps(self, mock_backend, state, cost_tracker):
        from cowork.schemas import ImplementationPlan, PlanStep

        state.implementation_plan = ImplementationPlan(
            goal="g", approach="a",
            steps=[PlanStep(id="s1", title="t", description="d")],
        )

        mock_backend.execute.return_value = BackendResult(
            success=True,
            structured_output={
                "step_ids_completed": ["s1"],
                "changes": [],
                "summary": "Done",
                "issues_encountered": [],
                "needs_follow_up": False,
            },
            cost_usd=0.05,
        )

        role = get_role("implementer")
        worker = Worker(role=role, backend=mock_backend, worker_id="impl-0")
        result = await worker.run(
            state, cost_tracker, extra_context={"assigned_steps": ["s1"]}
        )

        # Verify the prompt sent to the backend contains the assigned steps
        call_args = mock_backend.execute.call_args
        prompt = call_args[0][0]
        assert "s1" in prompt
