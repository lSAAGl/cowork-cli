# cowork_cli

**A reverse-engineered implementation of Anthropic's multi-agent orchestration pattern for autonomous software engineering.**

cowork is a CLI tool that decomposes complex coding tasks into a structured pipeline of specialized AI workers — each with defined roles, tool permissions, and output schemas — coordinated by a supervisor loop that handles planning, execution, review, testing, and iterative fixing.

> **Disclaimer:** This is an independent reverse-engineering effort for research and educational purposes. It is not affiliated with, endorsed by, or derived from proprietary source code of Anthropic or any other organization.

---

## How It Works

cowork models a software engineering team as a pipeline of six specialized agents, each backed by a Claude or Codex subprocess:

```
RESEARCH ──> PLAN ──> IMPLEMENT ──> REVIEW ──> TEST ──> FIX
   │                     │                        │       │
   │           parallel groups of workers          │       │
   │                                               │       │
   └───────────────────────────────────────────────┘       │
                    re-plan on repeated failures ◄─────────┘
```

### The Supervisor Loop

1. **Research** — Haiku-class workers explore the codebase in parallel (read-only, no file mutations).
2. **Plan** — An Opus-class worker synthesizes research into a step-by-step implementation plan with parallel groups and acceptance criteria.
3. **Implement** — Sonnet-class workers execute plan steps concurrently, each scoped to assigned step IDs.
4. **Review** — An Opus-class worker audits the implementation (read-only) and flags issues by severity.
5. **Test** — A Sonnet-class worker runs test suites and reports pass/fail per case.
6. **Fix** — If review or tests fail, a Sonnet-class worker addresses issues. After N consecutive fix failures, the supervisor escalates by re-planning with full review history.

The loop iterates up to `max_iterations` (default: 5). Budget enforcement halts execution if spend exceeds the configured ceiling.

---

## Architecture

```
cowork/
├── cli.py            # Click CLI: run, solo, init, status
├── supervisor.py     # Orchestration loop (observe-plan-act-reflect)
├── worker.py         # Prompt builder, backend caller, output validator
├── roles.py          # Role definitions: prompts, tools, models, budgets
├── schemas.py        # Pydantic v2 models for all structured I/O
├── state.py          # Shared blackboard with per-role context builders
├── cost.py           # Thread-safe cost tracking with budget enforcement
├── config.py         # 3-layer TOML config merge (defaults < project < CLI)
├── display.py        # Rich live terminal dashboard
├── errors.py         # Exception hierarchy
└── backends/
    ├── base.py       # Abstract backend interface
    ├── claude.py     # Claude CLI backend (claude -p --output-format json)
    └── codex.py      # Codex CLI backend (codex exec --json)
```

### Key Design Decisions

- **Subprocess isolation** — Each worker runs as an independent CLI subprocess with `--permission-mode bypassPermissions` and `--json-schema` for structured output enforcement.
- **Shared state as blackboard** — `SharedState` acts as a message bus; each phase writes results, downstream phases read what they need via `context_for_role()`.
- **Parallel execution** — Researchers and implementers run concurrently via `asyncio.gather`, bounded by `max_workers` per role.
- **Escalation** — After `consecutive_fix_failures_before_replan` failures (default: 3), the supervisor discards implementation state and re-plans with full review history as context.
- **Cost tracking** — Thread-safe accumulator with per-worker and per-role breakdowns. Hard budget ceiling raises `BudgetExceeded` before spawning the next worker.

---

## Installation

```bash
# Clone
git clone https://github.com/lSAAGl/cowork-cli.git
cd cowork-cli

# Create venv and install
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Prerequisites

- Python 3.10+
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated (`claude` on PATH)
- Or [Codex CLI](https://github.com/openai/codex) for the `--backend codex` option

---

## Usage

### Run the full pipeline

```bash
cowork run "Refactor the auth module to use JWT tokens" \
  --budget 10.0 \
  --max-iterations 3 \
  -v
```

### Run a single worker for debugging

```bash
cowork solo "Analyze the database schema" --role researcher
cowork solo "Write unit tests for utils.py" --role implementer --model sonnet
```

### Generate a config file

```bash
cowork init
```

This creates `cowork.toml` in the current directory with default settings.

---

## Configuration

Configuration merges three layers (lowest to highest priority):

```
configs/default.toml  <  ./cowork.toml  <  CLI flags
```

### Example `cowork.toml`

```toml
[supervisor]
max_iterations = 5
max_total_cost_usd = 20.0
consecutive_fix_failures_before_replan = 3
backend = "claude"

[roles.researcher]
model = "haiku"
max_workers = 2
budget_per_worker = 2.0
timeout_seconds = 600

[roles.planner]
model = "opus"
budget_per_worker = 5.0

[roles.implementer]
model = "sonnet"
max_workers = 3
budget_per_worker = 5.0

[roles.reviewer]
model = "opus"
budget_per_worker = 3.0
```

### Role Reference

| Role | Default Model | Tools | Workers | Purpose |
|------|--------------|-------|---------|---------|
| `researcher` | haiku | Read, Glob, Grep, Bash | 2 | Explore codebase (read-only) |
| `planner` | opus | Read, Glob, Grep | 1 | Create implementation plan |
| `implementer` | sonnet | default (all) | 3 | Execute plan steps |
| `reviewer` | opus | Read, Glob, Grep | 1 | Audit implementation (read-only) |
| `tester` | sonnet | Bash, Read | 1 | Run tests and verify |
| `fixer` | sonnet | default (all) | 1 | Fix review/test failures |

---

## Structured Output

Every worker produces validated Pydantic v2 output enforced via `--json-schema`:

| Role | Schema | Key Fields |
|------|--------|------------|
| Researcher | `ResearchFinding` | summary, key_files, patterns, dependencies, risks |
| Planner | `ImplementationPlan` | goal, steps, parallel_groups, test_strategy, acceptance_criteria |
| Implementer | `ImplementationResult` | step_ids_completed, changes (path/action/summary), issues_encountered |
| Reviewer | `ReviewResult` | approved, issues (file/line/severity/description), strengths |
| Tester | `TestResult` | all_passed, test_cases (name/passed/output/command), coverage_notes |
| Fixer | `FixResult` | issues_addressed, changes, remaining_issues, confidence |

---

## Development

```bash
# Run tests
pytest

# Run with verbose logging
cowork run "your task" -v

# Dry run (prints commands without executing)
cowork run "your task" --dry-run
```

---

## Known Limitations

- **Structured output constraint** — For very large tasks, workers may exhaust Claude's structured output retry limit before producing valid JSON. Best suited for focused, well-scoped tasks.
- **No streaming** — Workers run as batch subprocesses; no real-time output streaming.
- **Claude CLI dependency** — Requires the Claude CLI to be installed and authenticated. The Codex backend is a stub.
- **No persistence** — Run state is in-memory only; there is no resume-from-checkpoint capability.

---

## License

This project is provided as-is for research and educational purposes.
