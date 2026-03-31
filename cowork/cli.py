"""Click CLI — entry point for ``cowork`` commands."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import click

from cowork import __version__
from cowork.config import CoworkConfig, load_config
from cowork.errors import BudgetExceeded, CoworkError, MaxIterationsExceeded


@click.group()
@click.version_option(__version__, prog_name="cowork")
def main() -> None:
    """cowork — AI-orchestrated multi-worker CLI."""


# ── run ──────────────────────────────────────────────────────────────────────


@main.command()
@click.argument("task")
@click.option("--config", "config_file", type=click.Path(exists=True), default=None, help="Config TOML file")
@click.option("--backend", type=click.Choice(["claude", "codex"]), default=None, help="AI backend")
@click.option("--budget", type=float, default=None, help="Max total budget in USD")
@click.option("--max-iterations", type=int, default=None, help="Max supervisor iterations")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging")
@click.option("--dry-run", is_flag=True, help="Print commands without executing")
def run(
    task: str,
    config_file: str | None,
    backend: str | None,
    budget: float | None,
    max_iterations: int | None,
    verbose: bool,
    dry_run: bool,
) -> None:
    """Run the full supervisor pipeline on TASK."""
    overrides: dict[str, Any] = {}
    if backend:
        overrides["supervisor.backend"] = backend
    if budget is not None:
        overrides["supervisor.max_total_cost_usd"] = budget
    if max_iterations is not None:
        overrides["supervisor.max_iterations"] = max_iterations
    if verbose:
        overrides["verbose"] = True
    if dry_run:
        overrides["dry_run"] = True

    cfg = load_config(
        config_file=Path(config_file) if config_file else None,
        cli_overrides=overrides,
    )

    if cfg.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        from cowork.supervisor import run_supervisor

        state = asyncio.run(run_supervisor(task, cfg, cwd=str(Path.cwd())))
        click.echo(f"\n✓ Task completed successfully. Total cost: ${state.current_phase}")
    except BudgetExceeded as exc:
        click.secho(f"\n✗ Budget exceeded: {exc}", fg="red", err=True)
        sys.exit(1)
    except MaxIterationsExceeded as exc:
        click.secho(f"\n✗ {exc}", fg="red", err=True)
        sys.exit(1)
    except CoworkError as exc:
        click.secho(f"\n✗ Error: {exc}", fg="red", err=True)
        sys.exit(1)


# ── solo ─────────────────────────────────────────────────────────────────────


@main.command()
@click.argument("task")
@click.option("--role", required=True, type=click.Choice(["researcher", "planner", "implementer", "reviewer", "tester", "fixer"]))
@click.option("--model", default=None, help="Override model for this role")
@click.option("--backend", type=click.Choice(["claude", "codex"]), default="claude")
@click.option("--verbose", "-v", is_flag=True)
def solo(task: str, role: str, model: str | None, backend: str, verbose: bool) -> None:
    """Run a single worker role for debugging."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")

    from cowork.backends import ClaudeBackend
    from cowork.backends.codex import CodexBackend
    from cowork.cost import CostTracker
    from cowork.roles import get_role
    from cowork.state import SharedState
    from cowork.worker import Worker

    be = CodexBackend() if backend == "codex" else ClaudeBackend()
    role_def = get_role(role)

    # Apply model override
    if model:
        from dataclasses import replace
        role_def = replace(role_def, default_model=model)

    state = SharedState(task=task)
    cost_tracker = CostTracker(max_total_usd=10.0)
    worker = Worker(role=role_def, backend=be, worker_id=f"{role}-solo", cwd=str(Path.cwd()))

    async def _run() -> None:
        result = await worker.run(state, cost_tracker)
        click.echo(json.dumps(result.parsed.model_dump(), indent=2))
        click.echo(f"\nCost: ${result.cost_usd:.4f}  Duration: {result.duration:.1f}s")

    try:
        asyncio.run(_run())
    except CoworkError as exc:
        click.secho(f"Error: {exc}", fg="red", err=True)
        sys.exit(1)


# ── init ─────────────────────────────────────────────────────────────────────


@main.command()
@click.option("--dir", "directory", type=click.Path(), default=".", help="Target directory")
def init(directory: str) -> None:
    """Create a cowork.toml config file in the target directory."""
    target = Path(directory) / "cowork.toml"
    if target.exists():
        click.secho(f"Already exists: {target}", fg="yellow")
        return

    import tomli_w

    default_config = {
        "supervisor": {
            "max_iterations": 5,
            "max_total_cost_usd": 5.0,
            "backend": "claude",
        },
        "roles": {
            "researcher": {"model": "haiku", "max_workers": 2, "budget_per_worker": 0.5},
            "planner": {"model": "opus", "budget_per_worker": 1.0},
            "implementer": {"model": "sonnet", "max_workers": 3, "budget_per_worker": 1.5},
            "reviewer": {"model": "opus", "budget_per_worker": 0.75},
            "tester": {"model": "sonnet", "budget_per_worker": 0.5},
            "fixer": {"model": "sonnet", "budget_per_worker": 1.0},
        },
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as f:
        tomli_w.dump(default_config, f)

    click.secho(f"Created {target}", fg="green")


# ── status ───────────────────────────────────────────────────────────────────


@main.command()
def status() -> None:
    """Show summary of last run (placeholder)."""
    click.echo("Status: no previous run data found.")
    click.echo("Run 'cowork run \"your task\"' to start.")
