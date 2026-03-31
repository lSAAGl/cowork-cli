"""SharedState — the blackboard / message bus for the supervisor loop.

Every phase writes its results here; downstream phases read what they need
via ``context_for_role()``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from cowork.schemas import (
    FileChange,
    FixResult,
    ImplementationPlan,
    ImplementationResult,
    ResearchFinding,
    ReviewResult,
    TestResult,
)


@dataclass
class SharedState:
    """Central state object threaded through the supervisor pipeline."""

    task: str

    # Phase outputs
    research_findings: list[ResearchFinding] = field(default_factory=list)
    implementation_plan: ImplementationPlan | None = None
    implementation_results: list[ImplementationResult] = field(default_factory=list)
    review_result: ReviewResult | None = None
    test_result: TestResult | None = None
    fix_results: list[FixResult] = field(default_factory=list)

    # History (for escalation / re-planning)
    review_history: list[ReviewResult] = field(default_factory=list)

    # Tracking
    current_phase: str = ""
    current_iteration: int = 0

    # ── Context builders ─────────────────────────────────────────────────

    def context_for_role(self, role: str, **kwargs: Any) -> str:
        """Serialize relevant state into a prompt-friendly string.

        Parameters
        ----------
        role:
            One of researcher, planner, implementer, reviewer, tester, fixer.
        **kwargs:
            Extra context, e.g. ``assigned_steps=["step-1", "step-2"]`` for
            implementers.
        """
        builders = {
            "researcher": self._ctx_researcher,
            "planner": self._ctx_planner,
            "implementer": self._ctx_implementer,
            "reviewer": self._ctx_reviewer,
            "tester": self._ctx_tester,
            "fixer": self._ctx_fixer,
        }
        builder = builders.get(role)
        if builder is None:
            raise ValueError(f"Unknown role: {role}")
        return builder(**kwargs)

    # ── Private context builders ─────────────────────────────────────────

    def _ctx_researcher(self, **_: Any) -> str:
        return _section("TASK", self.task)

    def _ctx_planner(self, **_: Any) -> str:
        parts = [_section("TASK", self.task)]
        if self.research_findings:
            findings_text = "\n\n".join(
                f.model_dump_json(indent=2) for f in self.research_findings
            )
            parts.append(_section("RESEARCH FINDINGS", findings_text))
        if self.review_history:
            history_text = "\n\n---\n\n".join(
                r.model_dump_json(indent=2) for r in self.review_history
            )
            parts.append(_section("PREVIOUS REVIEW HISTORY", history_text))
        return "\n\n".join(parts)

    def _ctx_implementer(self, **kwargs: Any) -> str:
        parts = [_section("TASK", self.task)]
        if self.implementation_plan:
            plan_json = self.implementation_plan.model_dump_json(indent=2)
            parts.append(_section("IMPLEMENTATION PLAN", plan_json))
            assigned: list[str] = kwargs.get("assigned_steps", [])
            if assigned:
                parts.append(
                    _section(
                        "YOUR ASSIGNED STEPS",
                        "Complete these step IDs: " + ", ".join(assigned),
                    )
                )
        return "\n\n".join(parts)

    def _ctx_reviewer(self, **_: Any) -> str:
        parts = [_section("TASK", self.task)]
        if self.implementation_plan:
            parts.append(
                _section(
                    "IMPLEMENTATION PLAN",
                    self.implementation_plan.model_dump_json(indent=2),
                )
            )
        if self.implementation_results:
            results_text = "\n\n".join(
                r.model_dump_json(indent=2) for r in self.implementation_results
            )
            parts.append(_section("IMPLEMENTATION RESULTS", results_text))
        return "\n\n".join(parts)

    def _ctx_tester(self, **_: Any) -> str:
        parts = [_section("TASK", self.task)]
        if self.implementation_plan:
            parts.append(
                _section(
                    "IMPLEMENTATION PLAN",
                    self.implementation_plan.model_dump_json(indent=2),
                )
            )
        changed = self._changed_files()
        if changed:
            parts.append(_section("CHANGED FILES", "\n".join(changed)))
        return "\n\n".join(parts)

    def _ctx_fixer(self, **_: Any) -> str:
        parts = [_section("TASK", self.task)]
        if self.implementation_plan:
            parts.append(
                _section(
                    "IMPLEMENTATION PLAN",
                    self.implementation_plan.model_dump_json(indent=2),
                )
            )
        if self.review_result and self.review_result.issues:
            issues_text = "\n\n".join(
                i.model_dump_json(indent=2) for i in self.review_result.issues
            )
            parts.append(_section("REVIEW ISSUES", issues_text))
        if self.test_result and not self.test_result.all_passed:
            failed = [t for t in self.test_result.test_cases if not t.passed]
            if failed:
                fail_text = "\n\n".join(
                    t.model_dump_json(indent=2) for t in failed
                )
                parts.append(_section("FAILED TESTS", fail_text))
        if self.implementation_results:
            results_text = "\n\n".join(
                r.model_dump_json(indent=2) for r in self.implementation_results
            )
            parts.append(_section("IMPLEMENTATION RESULTS", results_text))
        return "\n\n".join(parts)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _changed_files(self) -> list[str]:
        """Collect unique changed file paths from implementation + fix results."""
        paths: set[str] = set()
        for result in self.implementation_results:
            for ch in result.changes:
                paths.add(ch.path)
        for fix in self.fix_results:
            for ch in fix.changes:
                paths.add(ch.path)
        return sorted(paths)

    def clear_implementation(self) -> None:
        """Reset implementation state for a re-plan cycle."""
        self.implementation_results.clear()
        self.review_result = None
        self.test_result = None


# ── Formatting helpers ───────────────────────────────────────────────────────


def _section(heading: str, body: str) -> str:
    return f"## {heading}\n\n{body}"
