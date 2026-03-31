"""Tests for SharedState and context_for_role."""

import pytest

from cowork.schemas import (
    ImplementationPlan,
    ImplementationResult,
    FileChange,
    PlanStep,
    ResearchFinding,
    ReviewIssue,
    ReviewResult,
    Severity,
    TestCase,
    TestResult,
)
from cowork.state import SharedState


class TestContextForRole:
    def test_researcher_gets_task_only(self):
        state = SharedState(task="Do something")
        ctx = state.context_for_role("researcher")
        assert "Do something" in ctx
        # Should not contain plan or other phase data
        assert "IMPLEMENTATION PLAN" not in ctx

    def test_planner_gets_research(self):
        state = SharedState(task="Build feature")
        state.research_findings.append(
            ResearchFinding(summary="Found patterns", key_files=["a.py"])
        )
        ctx = state.context_for_role("planner")
        assert "Build feature" in ctx
        assert "Found patterns" in ctx

    def test_planner_gets_review_history(self):
        state = SharedState(task="Fix bug")
        state.review_history.append(
            ReviewResult(approved=False, summary="Bad code")
        )
        ctx = state.context_for_role("planner")
        assert "PREVIOUS REVIEW HISTORY" in ctx
        assert "Bad code" in ctx

    def test_implementer_gets_plan_and_steps(self):
        state = SharedState(task="Add pagination")
        state.implementation_plan = ImplementationPlan(
            goal="Add pagination",
            approach="SQL LIMIT/OFFSET",
            steps=[PlanStep(id="s1", title="Step 1", description="Do step 1")],
        )
        ctx = state.context_for_role("implementer", assigned_steps=["s1"])
        assert "IMPLEMENTATION PLAN" in ctx
        assert "YOUR ASSIGNED STEPS" in ctx
        assert "s1" in ctx

    def test_reviewer_gets_plan_and_results(self):
        state = SharedState(task="t")
        state.implementation_plan = ImplementationPlan(
            goal="g", approach="a", steps=[]
        )
        state.implementation_results.append(
            ImplementationResult(
                step_ids_completed=["s1"],
                summary="Done",
                changes=[FileChange(path="a.py", action="modified", summary="Changed")],
            )
        )
        ctx = state.context_for_role("reviewer")
        assert "IMPLEMENTATION PLAN" in ctx
        assert "IMPLEMENTATION RESULTS" in ctx

    def test_tester_gets_changed_files(self):
        state = SharedState(task="t")
        state.implementation_plan = ImplementationPlan(
            goal="g", approach="a", steps=[]
        )
        state.implementation_results.append(
            ImplementationResult(
                step_ids_completed=["s1"],
                summary="Done",
                changes=[FileChange(path="src/x.py", action="created", summary="New file")],
            )
        )
        ctx = state.context_for_role("tester")
        assert "CHANGED FILES" in ctx
        assert "src/x.py" in ctx

    def test_fixer_gets_issues_and_failures(self):
        state = SharedState(task="t")
        state.implementation_plan = ImplementationPlan(
            goal="g", approach="a", steps=[]
        )
        state.review_result = ReviewResult(
            approved=False,
            summary="Issues found",
            issues=[
                ReviewIssue(
                    file="a.py",
                    severity=Severity.critical,
                    description="Buffer overflow",
                )
            ],
        )
        state.test_result = TestResult(
            all_passed=False,
            tests_run=1,
            tests_failed=1,
            test_cases=[TestCase(name="t1", passed=False, output="FAIL")],
            summary="1 fail",
        )
        ctx = state.context_for_role("fixer")
        assert "REVIEW ISSUES" in ctx
        assert "FAILED TESTS" in ctx
        assert "Buffer overflow" in ctx

    def test_unknown_role_raises(self):
        state = SharedState(task="t")
        with pytest.raises(ValueError, match="Unknown role"):
            state.context_for_role("wizard")


class TestClearImplementation:
    def test_clears_results(self):
        state = SharedState(task="t")
        state.implementation_results.append(
            ImplementationResult(step_ids_completed=[], summary="x")
        )
        state.review_result = ReviewResult(approved=False, summary="bad")
        state.test_result = TestResult(all_passed=False, summary="fail")
        state.clear_implementation()
        assert state.implementation_results == []
        assert state.review_result is None
        assert state.test_result is None
