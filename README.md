# Autonomous Software Factory
**English** | [简体中文](README.zh-CN.md)

> Turn a **goal** into a **verified application** — an autonomous software venture factory (V1 core).

Autonomous Software Factory is a task-graph-driven coding factory with an **independent verification system**. It implements the V1 core of an "autonomous software company" blueprint: given a PRD and a task graph (DAG), it spawns isolated coding agents, validates every change with deterministic machine gates, runs an independent reviewer, repairs failures, and only merges to `main` what actually passes — no silent merges, no unlimited retries, no unaccounted spend.

The design philosophy: **Agent Organization + Durable Workflow + Independent Verification System**, not a monolithic "one agent to do everything". Each role (coder, verifier, reviewer, budget) is separated so that no single agent holds the final truth.

## Features

- **Task-graph driven orchestration** — DAG validation, cycle/dependency checks, topological ordering, and ready-task scheduling from a JSON/YAML task graph.
- **Git worktree isolation** — every task gets a fresh worktree snapshotted from `main`; the coder is *only* allowed to write inside its own worktree (enforced by policy, not convention).
- **Independent machine verification gates** — `syntax` → `test` → `lint` run in order; gates are **fail-closed** (an unknown gate name fails the build rather than being silently skipped).
- **Rule-isolated reviewer** — the reviewer inspects spec, diff, gates and tests independently; empty/failed coder output is rejected, never merged.
- **Repair loop with hard caps** — verify/review failures trigger automatic repair, capped by `FACTORY_MAX_RETRIES` (default 3); exhausted tasks end in `BLOCKED`, never hang.
- **Least-privilege permission engine** — role-based allow-list with **deny-by-default**; the coder has no network, no secrets, no production access.
- **Budget guardrails** — per-task token and wall-clock runtime budgets; a spent budget hard-blocks the task; a hung coder attempt is reclaimed via a per-attempt timeout (default 300s).
- **Crash recovery** — durable state in SQLite (or PostgreSQL); interrupted tasks are auto-reset to `READY` and resumed on the next run, never stuck as a permanent `BLOCKED`.
- **Audit ledger** — every coder attempt (tokens + runtime) is mirrored into a durable `BudgetLedger` with per-project accounts.
- **Milestone promotion** — `factory promote` walks a fully built, fully reviewed project through the state machine (… → `PRODUCTION`) with eligibility checks and audit rows; resumable after a crash.
- **CI-ready exit codes** — `factory run` returns `0` only when the task graph completes (`DONE`); any `BLOCKED`/partial outcome returns `1`.

## Architecture

```
PRD + task graph (DAG)
        │
        ▼
┌────────────────────── SOFTWARE FACTORY ──────────────────────┐
│                                                              │
│   ┌────────┐   ┌────────────┐   ┌──────────┐                 │
│   │ coder  │ → │  verifier  │ → │ reviewer │   repair loop   │
│   │(seeded │   │ machine    │   │ rule-    │   FAIL ──────┐  │
│   │ defects│   │ gates)     │   │ isolated │              │  │
│   └───┬────┘   └─────┬──────┘   └────┬─────┘              │  │
│       │  may only write worktree     │                    │  │
│       ▼                              │                    │  │
│  worktree (snapshot of main) ────────┘                    │  │
│        │                                                    │  │
│        └────────────── pass ──► merge into main ◄───────────┘  │
└──────────────────────────────────────────────────────────────┘
```

Every transition is guarded by **policy + evidence + gate**. The database (project/task/review/run/budget) is the source of truth; nothing important lives in chat history.

## Quick Start

Requirements: Python **3.11+**.

```bash
# 1) Install
pip install -e .

# 2) Initialize the database (default: local SQLite ./factory.db)
factory init-db

# 3) Inspect a role's permission boundary
factory policy coder

# 4) Run the bundled end-to-end demo
#    (T001 is deliberately seeded with a defect — the pipeline must
#     catch it via verification and repair it before merging)
factory demo

# 5) Query the durable state of a project
factory status p_demo_calc

# 6) Promote a fully built + fully reviewed project to PRODUCTION
factory promote p_demo_calc

# 7) Run your own project from a task graph
factory run <task_graph.json> --prd <prd.md>
```

> **Exit-code contract**: `factory run` returns `0` only when every task reaches `DONE`. Any `BLOCKED` or partial outcome returns `1` — wire it straight into CI.

## Example task graph

```jsonc
// examples/sample_project/task_graph.json
{
  "project_id": "p_demo_calc",
  "name": "Sample Calculator Service",
  "tasks": [
    { "id": "T001", "title": "implement sample_app package with tests",
      "dependencies": [], "meta": { "target": "all" } },
    { "id": "T002", "title": "harden test suite (regression guard)",
      "dependencies": ["T001"], "meta": { "target": "tests" } }
  ]
}
```

Each task can carry `acceptance` criteria and a `files` allow-list. The orchestrator resolves dependencies, schedules ready tasks, and only merges a task once its verification gates pass and the reviewer approves.

## Testing & Static Checks

```bash
python -m pytest tests -q          # 103 passed, 1 skipped (v0.1.0, Py3.11)
python -m ruff check factory tests # deterministic lint baseline: 0 warnings
```

Coverage: task-graph validation (incl. UTF-8 BOM tolerance), state machine, permission policy, budgets (token + runtime, exhaustion → hard `BLOCKED`), verification pipeline, crash recovery (interrupted tasks auto-reset & resume), audit ledger, execution wall-clock guardrail, fail-closed gates, milestone promotion (eligibility + resumability), and a full E2E (seeded defect → repair → merge → self-consistent `main`).

CI (`.github/workflows/ci.yml`) runs on Python 3.11 / 3.12: `ruff check` + `pytest --cov=factory`.

## Production Guardrails (CI contract)

- **Exit code is the result** — a build is green only if the whole graph is `DONE`; anything else is a non-zero exit.
- **Never silently merge** — unverified/unreviewed work never reaches `main`; the repair loop is capped by `FACTORY_MAX_RETRIES`.
- **Budget fallback** — `FACTORY_RUNTIME_BUDGET_S` is pre-checked before every coder attempt; exhausted budget → immediate `BLOCKED`, no idle spinning.
- **Empty-artifact safety** — empty or failed coder output is rejected by the reviewer ("declared files missing") and ends `BLOCKED`, never a half-baked artifact.
- **Wall-clock guardrail** — `FACTORY_ATTEMPT_TIMEOUT_S` caps a single coder attempt; a hung LLM call is reclaimed as a budget event.
- **Fail-closed verification** — an unknown gate name in `FACTORY_VERIFY_GATES` fails the pipeline (red light, never a fake "verified").
- **Crash-recoverable** — any task interrupted in `IN_PROGRESS`/`WAITING_VERIFY`/`VERIFY_FAILED`/`WAITING_REVIEW`/`REVIEW_REJECTED`/`BLOCKED` is reset to `READY` and re-run on the next `factory run`.
- **Spend is auditable** — every coder attempt (token + runtime) lands in `BudgetLedger` with per-project accounts.
- **Promotion has evidence** — `factory promote` only advances when the project exists, all tasks are `DONE`, and all reviews are `APPROVE`; every step writes a `kind=PROMOTE` audit row.
- **Reproducible baseline** — the ruff rule set (E4/E7/E9/F/I, line length 120) is pinned in `pyproject.toml`, so CI can re-verify with the same command.

## Project Layout

```
autonomous-factory/
├── factory/                 # core implementation
│   ├── cli.py               # typer CLI (init-db / run / demo / status / policy / promote)
│   ├── config.py            # environment-driven settings
│   ├── db.py                # SQLAlchemy engine & session management
│   ├── orchestrator.py      # worktree-isolated pipeline main loop
│   ├── state_machine.py     # project/task state machines + migration table
│   ├── verifier.py          # syntax / pytest / lint machine gates
│   ├── policy.py            # least-privilege permission engine
│   ├── budget.py            # token + runtime budget tracking
│   ├── safety.py            # id / path safety checks
│   ├── execution.py         # wall-clock attempt guardrail
│   ├── agents/              # base (contracts), coder, reviewer, registry
│   ├── models/              # Project / Task / Review / Run / Budget ORM
│   ├── schemas/             # Evidence / Risk / AgentOutput / TaskGraph
│   └── workflows/           # DevelopmentWorkflow (persistent, resumable, promote)
├── examples/sample_project/ # bundled PRD + task graph demo
├── tests/                   # unit + E2E test suite
├── factory_runtime/         # runtime workspace (worktrees & artifacts, git-ignored)
└── .github/workflows/       # CI pipeline
```

## Configuration

All settings are environment-driven; every variable is optional (sensible local defaults). Secrets belong in the environment — never in code.

| Variable | Default | Description |
|---|---|---|
| `FACTORY_DATABASE_URL` | `sqlite:///./factory.db` | Durable state store. Point at PostgreSQL for production: `postgresql+psycopg://user:pass@host:5432/factory` |
| `FACTORY_WORKSPACE` | `./factory_runtime` | Where project worktrees and run artifacts live |
| `FACTORY_MAX_RETRIES` | `3` | Max repair attempts per task before hard `BLOCKED` |
| `FACTORY_TOKEN_BUDGET` | `120000` | Per-task token budget |
| `FACTORY_RUNTIME_BUDGET_S` | `1800` | Per-task wall-clock runtime budget |
| `FACTORY_ATTEMPT_TIMEOUT_S` | `300` | Per-attempt wall-clock ceiling (hung LLM calls are reclaimed) |
| `FACTORY_VERIFY_GATES` | `syntax,test,lint` | Comma-separated gates run in order; unknown names fail closed |
| `FACTORY_ISOLATION` | `worktree` | Worktree isolation mode for per-project/task sandboxes |

See `.env.example` for a ready-to-copy template.

### Connecting a real LLM backend

By default the coder uses a deterministic in-process `RecipeBackend` — great for demos and CI, zero external dependencies. To drive the factory with a real model, install the `llm` extra and set the OpenAI-compatible variables:

```bash
pip install -e ".[llm]"

export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-4o-mini
```

Once `OPENAI_API_KEY` is present, the coder uses the OpenAI-compatible backend instead of the recipe backend. Only commit keys in your environment, never in the repository.

## Status

- **v0.1.0** — V1 core implemented and verified: task-graph factory, worktree isolation, machine verification gates, reviewer, budget guardrails, crash recovery, audit ledger, and milestone promotion.
- The roadmap beyond V1 (market scouting, validation engine, portfolio CEO, etc.) is intentionally **not** part of this repository yet — this repo ships the factory itself, not the venture-capital layer.

## License

Released under the [MIT License](LICENSE).
