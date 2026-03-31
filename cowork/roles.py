"""Role definitions — system prompts, schemas, defaults per worker role."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from cowork.config import RoleConfig
from cowork.schemas import (
    ROLE_SCHEMAS,
    FixResult,
    ImplementationPlan,
    ImplementationResult,
    ResearchFinding,
    ReviewResult,
    TestResult,
)


@dataclass(frozen=True)
class RoleDefinition:
    """Everything the worker layer needs to know about a role."""

    name: str
    system_prompt: str
    output_schema: type[BaseModel]
    default_model: str
    default_tools: str          # comma-separated, or "default"
    disallowed_tools: str       # comma-separated
    max_workers: int
    budget_per_worker: float
    timeout_seconds: int = 300


# ── System prompt templates ──────────────────────────────────────────────────

_RESEARCHER_PROMPT = """\
You are a Research Analyst. Your job is to thoroughly explore and understand \
the codebase and task context before any changes are made.

Instructions:
- Read files, search for patterns, and run non-destructive commands to \
  understand the codebase structure, conventions, and relevant code.
- Identify key files, architectural patterns, dependencies, and potential risks.
- Do NOT modify any files.
- Provide your findings as structured JSON matching the required schema.
"""

_PLANNER_PROMPT = """\
You are a Software Architect and Planner. Given research findings about a \
codebase and a task description, create a detailed implementation plan.

Instructions:
- Break the task into concrete, ordered steps.
- Identify which files each step will touch.
- Group independent steps into parallel groups where possible.
- Define clear acceptance criteria and a test strategy.
- Consider edge cases, error handling, and backward compatibility.
- Provide your plan as structured JSON matching the required schema.
"""

_IMPLEMENTER_PROMPT = """\
You are a Software Engineer. Execute the assigned implementation steps from \
the plan precisely and thoroughly.

Instructions:
- Follow the plan steps assigned to you exactly.
- Write clean, well-documented code following the project's conventions.
- Create or modify files as needed.
- Report all changes made and any issues encountered.
- Provide your results as structured JSON matching the required schema.
"""

_REVIEWER_PROMPT = """\
You are a Senior Code Reviewer. Review the implementation against the plan \
and codebase standards. You have READ-ONLY access.

Instructions:
- Check that all plan steps were implemented correctly.
- Look for bugs, security issues, style violations, and missing edge cases.
- Verify naming conventions and code organization.
- Rate each issue by severity (critical/major/minor/suggestion).
- Set approved=true only if there are no critical or major issues.
- Provide your review as structured JSON matching the required schema.
"""

_TESTER_PROMPT = """\
You are a QA Engineer. Run tests to verify the implementation works correctly.

Instructions:
- Identify and run existing test suites relevant to the changes.
- If no tests exist, run the code and verify basic correctness.
- Check for regressions in related functionality.
- Report each test case with pass/fail status and output.
- Provide your results as structured JSON matching the required schema.
"""

_FIXER_PROMPT = """\
You are a Bug-Fix Engineer. Fix the issues identified by review and testing.

Instructions:
- Address each review issue and test failure systematically.
- Start with critical issues, then major, then minor.
- Make minimal, targeted changes — don't refactor unrelated code.
- Report what you fixed and what remains unresolved.
- Provide your results as structured JSON matching the required schema.
"""

# ── Default role registry ────────────────────────────────────────────────────

_DEFAULTS: dict[str, RoleDefinition] = {
    "researcher": RoleDefinition(
        name="researcher",
        system_prompt=_RESEARCHER_PROMPT,
        output_schema=ResearchFinding,
        default_model="haiku",
        default_tools="Read,Glob,Grep,Bash",
        disallowed_tools="Edit,Write",
        max_workers=2,
        budget_per_worker=0.50,
    ),
    "planner": RoleDefinition(
        name="planner",
        system_prompt=_PLANNER_PROMPT,
        output_schema=ImplementationPlan,
        default_model="opus",
        default_tools="Read,Glob,Grep",
        disallowed_tools="",
        max_workers=1,
        budget_per_worker=1.00,
    ),
    "implementer": RoleDefinition(
        name="implementer",
        system_prompt=_IMPLEMENTER_PROMPT,
        output_schema=ImplementationResult,
        default_model="sonnet",
        default_tools="default",
        disallowed_tools="",
        max_workers=3,
        budget_per_worker=1.50,
    ),
    "reviewer": RoleDefinition(
        name="reviewer",
        system_prompt=_REVIEWER_PROMPT,
        output_schema=ReviewResult,
        default_model="opus",
        default_tools="Read,Glob,Grep",
        disallowed_tools="Edit,Write,Bash",
        max_workers=1,
        budget_per_worker=0.75,
    ),
    "tester": RoleDefinition(
        name="tester",
        system_prompt=_TESTER_PROMPT,
        output_schema=TestResult,
        default_model="sonnet",
        default_tools="Bash,Read",
        disallowed_tools="",
        max_workers=1,
        budget_per_worker=0.50,
    ),
    "fixer": RoleDefinition(
        name="fixer",
        system_prompt=_FIXER_PROMPT,
        output_schema=FixResult,
        default_model="sonnet",
        default_tools="default",
        disallowed_tools="",
        max_workers=1,
        budget_per_worker=1.00,
    ),
}

# Public access

ROLES = dict(_DEFAULTS)


def get_role(name: str, config_override: RoleConfig | None = None) -> RoleDefinition:
    """Return a role definition, optionally applying config overrides.

    Parameters
    ----------
    name:
        Role name (researcher, planner, implementer, reviewer, tester, fixer).
    config_override:
        ``RoleConfig`` from the TOML/CLI layer — any non-empty field wins.
    """
    base = _DEFAULTS.get(name)
    if base is None:
        raise ValueError(f"Unknown role: {name!r}")
    if config_override is None:
        return base

    return RoleDefinition(
        name=base.name,
        system_prompt=base.system_prompt,
        output_schema=base.output_schema,
        default_model=config_override.model or base.default_model,
        default_tools=config_override.tools or base.default_tools,
        disallowed_tools=config_override.disallowed_tools or base.disallowed_tools,
        max_workers=config_override.max_workers or base.max_workers,
        budget_per_worker=config_override.budget_per_worker or base.budget_per_worker,
        timeout_seconds=config_override.timeout_seconds or base.timeout_seconds,
    )
