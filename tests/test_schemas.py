"""Tests for schemas — Pydantic models + JSON schema generation."""

import json

import pytest
from pydantic import ValidationError

from cowork.schemas import (
    ROLE_SCHEMAS,
    FileChange,
    FixResult,
    ImplementationPlan,
    ImplementationResult,
    ParallelGroup,
    PlanStep,
    ResearchFinding,
    ReviewIssue,
    ReviewResult,
    Severity,
    TestCase,
    TestResult,
    schema_for_role,
)


class TestResearchFinding:
    def test_minimal(self):
        f = ResearchFinding(summary="Found stuff")
        assert f.summary == "Found stuff"
        assert f.key_files == []

    def test_full(self):
        f = ResearchFinding(
            summary="s",
            key_files=["a.py"],
            patterns=["MVC"],
            dependencies=["flask"],
            risks=["none"],
            raw_notes="notes",
        )
        assert len(f.key_files) == 1

    def test_json_roundtrip(self):
        f = ResearchFinding(summary="test")
        data = json.loads(f.model_dump_json())
        f2 = ResearchFinding.model_validate(data)
        assert f2.summary == "test"


class TestImplementationPlan:
    def test_with_steps(self):
        plan = ImplementationPlan(
            goal="Add feature",
            approach="Incremental",
            steps=[
                PlanStep(id="s1", title="Do it", description="Just do it", files=["f.py"]),
            ],
            parallel_groups=[ParallelGroup(step_ids=["s1"])],
        )
        assert len(plan.steps) == 1
        assert plan.parallel_groups[0].step_ids == ["s1"]


class TestReviewResult:
    def test_approved(self):
        r = ReviewResult(approved=True, summary="LGTM")
        assert r.approved

    def test_with_issues(self):
        r = ReviewResult(
            approved=False,
            summary="Needs work",
            issues=[
                ReviewIssue(
                    file="a.py",
                    severity=Severity.major,
                    description="Bug here",
                )
            ],
        )
        assert not r.approved
        assert r.issues[0].severity == Severity.major


class TestTestResult:
    def test_all_passed(self):
        t = TestResult(all_passed=True, tests_run=3, tests_passed=3, summary="OK")
        assert t.tests_failed == 0

    def test_with_failures(self):
        t = TestResult(
            all_passed=False,
            tests_run=2,
            tests_passed=1,
            tests_failed=1,
            test_cases=[TestCase(name="t1", passed=False, output="AssertionError")],
            summary="1 failure",
        )
        assert not t.all_passed


class TestFixResult:
    def test_confidence_bounds(self):
        f = FixResult(issues_addressed=["bug"], summary="fixed", confidence=0.9)
        assert 0 <= f.confidence <= 1

    def test_invalid_confidence(self):
        with pytest.raises(ValidationError):
            FixResult(issues_addressed=[], summary="x", confidence=1.5)


class TestSchemaGeneration:
    def test_all_roles_have_schemas(self):
        for role in ["researcher", "planner", "implementer", "reviewer", "tester", "fixer"]:
            schema = schema_for_role(role)
            assert "properties" in schema
            assert isinstance(schema, dict)

    def test_schema_is_valid_json(self):
        for role in ROLE_SCHEMAS:
            schema = schema_for_role(role)
            dumped = json.dumps(schema)
            parsed = json.loads(dumped)
            assert parsed == schema

    def test_unknown_role_raises(self):
        with pytest.raises(KeyError):
            schema_for_role("nonexistent")
