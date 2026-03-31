"""Tests for cost tracking and budget enforcement."""

import pytest

from cowork.cost import CostTracker
from cowork.errors import BudgetExceeded, WorkerBudgetExceeded


class TestCostTracker:
    def test_empty(self):
        ct = CostTracker(max_total_usd=5.0)
        assert ct.total() == 0.0
        assert ct.budget_remaining() == 5.0

    def test_record_and_total(self):
        ct = CostTracker()
        ct.record("researcher", "r-0", 0.05)
        ct.record("researcher", "r-1", 0.03)
        assert abs(ct.total() - 0.08) < 1e-9

    def test_by_role(self):
        ct = CostTracker()
        ct.record("researcher", "r-0", 0.05)
        ct.record("planner", "p-0", 0.10)
        ct.record("researcher", "r-1", 0.03)
        by_role = ct.by_role()
        assert abs(by_role["researcher"] - 0.08) < 1e-9
        assert abs(by_role["planner"] - 0.10) < 1e-9

    def test_by_worker(self):
        ct = CostTracker()
        ct.record("researcher", "r-0", 0.05)
        ct.record("researcher", "r-0", 0.02)
        by_worker = ct.by_worker()
        assert abs(by_worker["r-0"] - 0.07) < 1e-9

    def test_budget_remaining(self):
        ct = CostTracker(max_total_usd=1.0)
        ct.record("r", "r-0", 0.40)
        assert abs(ct.budget_remaining() - 0.60) < 1e-9

    def test_check_budget_ok(self):
        ct = CostTracker(max_total_usd=1.0)
        ct.record("r", "r-0", 0.50)
        ct.check_budget()  # Should not raise

    def test_check_budget_exceeded(self):
        ct = CostTracker(max_total_usd=1.0)
        ct.record("r", "r-0", 1.00)
        with pytest.raises(BudgetExceeded) as exc_info:
            ct.check_budget()
        assert exc_info.value.spent >= 1.0

    def test_worker_budget_ok(self):
        remaining = CostTracker.worker_budget("researcher", 0.50, 0.20)
        assert abs(remaining - 0.30) < 1e-9

    def test_worker_budget_exceeded(self):
        with pytest.raises(WorkerBudgetExceeded):
            CostTracker.worker_budget("researcher", 0.50, 0.55)

    def test_entries_list(self):
        ct = CostTracker()
        ct.record("r", "r-0", 0.01)
        ct.record("p", "p-0", 0.02)
        entries = ct.entries
        assert len(entries) == 2
        assert entries[0].role == "r"
