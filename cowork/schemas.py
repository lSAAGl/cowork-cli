"""Pydantic v2 models for all structured worker I/O.

Each model serves dual purpose:
1. Python-side validation via model_validate()
2. JSON Schema generation via model_json_schema() for --json-schema flag
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Shared primitives ────────────────────────────────────────────────────────


class Severity(str, Enum):
    critical = "critical"
    major = "major"
    minor = "minor"
    suggestion = "suggestion"


class FileChange(BaseModel):
    """A single file that was created / modified / deleted."""

    path: str = Field(description="Relative file path")
    action: str = Field(description="created | modified | deleted")
    summary: str = Field(description="One-line description of the change")


# ── Phase 1: Research ────────────────────────────────────────────────────────


class ResearchFinding(BaseModel):
    """Output schema for the Researcher role."""

    summary: str = Field(description="High-level summary of findings")
    key_files: list[str] = Field(
        default_factory=list,
        description="Important files discovered in the codebase",
    )
    patterns: list[str] = Field(
        default_factory=list,
        description="Architectural / code patterns observed",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="External dependencies or constraints found",
    )
    risks: list[str] = Field(
        default_factory=list,
        description="Potential risks or blockers identified",
    )
    raw_notes: str = Field(
        default="",
        description="Free-form notes and context for downstream workers",
    )


# ── Phase 2: Plan ────────────────────────────────────────────────────────────


class PlanStep(BaseModel):
    """A single implementation step inside a plan."""

    id: str = Field(description="Unique step identifier, e.g. 'step-1'")
    title: str = Field(description="Short title for this step")
    description: str = Field(description="Detailed description of what to do")
    files: list[str] = Field(
        default_factory=list,
        description="Files expected to be touched",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="IDs of steps that must complete first",
    )


class ParallelGroup(BaseModel):
    """A group of steps that can run concurrently."""

    step_ids: list[str] = Field(description="Step IDs in this parallel group")


class ImplementationPlan(BaseModel):
    """Output schema for the Planner role."""

    goal: str = Field(description="Restated task goal")
    approach: str = Field(description="High-level approach description")
    steps: list[PlanStep] = Field(description="Ordered implementation steps")
    parallel_groups: list[ParallelGroup] = Field(
        default_factory=list,
        description="Groups of steps that can execute in parallel",
    )
    test_strategy: str = Field(
        default="",
        description="How the implementation should be tested",
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Criteria for considering the task complete",
    )


# ── Phase 3: Implement ──────────────────────────────────────────────────────


class ImplementationResult(BaseModel):
    """Output schema for the Implementer role."""

    step_ids_completed: list[str] = Field(
        description="Which plan step IDs were addressed"
    )
    changes: list[FileChange] = Field(
        default_factory=list,
        description="Files created or modified",
    )
    summary: str = Field(description="What was done and why")
    issues_encountered: list[str] = Field(
        default_factory=list,
        description="Problems hit during implementation",
    )
    needs_follow_up: bool = Field(
        default=False,
        description="Whether further work is needed on these steps",
    )


# ── Phase 4: Review ─────────────────────────────────────────────────────────


class ReviewIssue(BaseModel):
    """A single issue found during review."""

    file: str = Field(description="File path where the issue was found")
    line: int | None = Field(default=None, description="Line number, if applicable")
    severity: Severity = Field(description="Issue severity")
    description: str = Field(description="What the issue is")
    suggestion: str = Field(default="", description="How to fix it")


class ReviewResult(BaseModel):
    """Output schema for the Reviewer role."""

    approved: bool = Field(description="Whether the implementation passes review")
    summary: str = Field(description="Overall review summary")
    issues: list[ReviewIssue] = Field(
        default_factory=list,
        description="Specific issues found",
    )
    strengths: list[str] = Field(
        default_factory=list,
        description="Things done well",
    )


# ── Phase 5: Test ────────────────────────────────────────────────────────────


class TestCase(BaseModel):
    """A single test that was executed."""

    __test__ = False  # prevent pytest collection

    name: str = Field(description="Test name or description")
    passed: bool = Field(description="Whether the test passed")
    output: str = Field(default="", description="Test output or error message")
    command: str = Field(default="", description="Command used to run this test")


class TestResult(BaseModel):
    """Output schema for the Tester role."""

    __test__ = False  # prevent pytest collection

    all_passed: bool = Field(description="Whether all tests passed")
    tests_run: int = Field(default=0, description="Total tests executed")
    tests_passed: int = Field(default=0, description="Tests that passed")
    tests_failed: int = Field(default=0, description="Tests that failed")
    test_cases: list[TestCase] = Field(
        default_factory=list,
        description="Individual test results",
    )
    summary: str = Field(description="Overall test summary")
    coverage_notes: str = Field(
        default="",
        description="Notes on test coverage",
    )


# ── Phase 6: Fix ─────────────────────────────────────────────────────────────


class FixResult(BaseModel):
    """Output schema for the Fixer role."""

    issues_addressed: list[str] = Field(
        description="Descriptions of issues that were fixed"
    )
    changes: list[FileChange] = Field(
        default_factory=list,
        description="Files modified during the fix",
    )
    summary: str = Field(description="What was fixed and how")
    remaining_issues: list[str] = Field(
        default_factory=list,
        description="Issues that could not be resolved",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence that the fixes resolve the problems (0-1)",
    )


# ── Utility ──────────────────────────────────────────────────────────────────

# Map role name → output schema class
ROLE_SCHEMAS: dict[str, type[BaseModel]] = {
    "researcher": ResearchFinding,
    "planner": ImplementationPlan,
    "implementer": ImplementationResult,
    "reviewer": ReviewResult,
    "tester": TestResult,
    "fixer": FixResult,
}


def schema_for_role(role: str) -> dict[str, Any]:
    """Return the JSON Schema dict for a role's output model."""
    model_cls = ROLE_SCHEMAS[role]
    return model_cls.model_json_schema()
