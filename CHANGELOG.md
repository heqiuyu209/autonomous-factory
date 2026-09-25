# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [6.0.1] - 2026-09-25

### Security

- **P0 — verifier sandbox isolation**: LLM-generated code is no longer
  executed directly on the host. Every verifier gate runs through a
  `SandboxRunner` (`factory/sandbox.py`):
  - `DockerRunner`: one-shot container — `--network none`, read-only
    rootfs + read-only worktree mount, `--cap-drop ALL`,
    `no-new-privileges`, `--tmpfs /tmp` scratch, allow-listed env via
    `--env-file`, pinned `python:3.11-slim` image.
  - `SubprocessRunner`: degraded fallback with allow-listed env + hard
    timeout, used only when no container runtime is present.
  - `FACTORY_VERIFY_SANDBOX=auto|docker|subprocess`: `docker` mode fails
    closed when the engine is unavailable; `auto` degrades transparently.
  - Every `GateResult` / summary reports the sandbox backend + degraded
    flag so a fallback run is never mistaken for a containerized one.
  - Docker availability probe now checks the daemon actually answers
    (returncode), not just CLI presence; host `sys.executable` is
    translated to the image interpreter inside containers.
  - `factory/envsafe.py` extracts the shared env allow-list / secret
    markers used by both backends.
- **P1 — coder context injection**: task `description`, dependency task
  summaries/artifacts and project PRD (truncated) are now passed to the
  coder instead of a bare title.
- **P1 — real token billing**: `AgentOutput.usage_tokens` carries the
  provider-reported token count; budget charge/ledger prefer it over the
  `len(summary)` heuristic.
- **P1 — PostgreSQL driver alignment**: dependency switched to
  `psycopg[binary]>=3.1` to match the `postgresql+psycopg://` URL.

### Added

- `factory/sandbox.py` + `factory/envsafe.py` (P0 isolation layer).
- 13 new tests (`tests/test_sandbox.py`, `tests/test_security_fixes.py`):
  docker command shape, env-file scratch redirection, selection policy,
  fail-closed behaviour, interpreter translation, env isolation, real
  usage propagation, context injection. Full suite 204 passed, 1 skipped.

## [6.0.0] - 2026-09-24

### Added

- Portfolio CEO (blueprint V6/§1/§18): top-of-factory combination layer that
  owns N products instead of optimizing a single one — Darwinian portfolio:
  scale winners / experiment with maybes / kill losers, then re-allocate
  compute budget.
  - `factory/schemas/portfolio.py`: `PortfolioAction` (BUILD / SCALE /
    EXPERIMENT / HOLD / KILL + priority + budget_weight) and
    `PortfolioReport`.
  - `factory/agents/portfolio.py`: deterministic `PortfolioCEO` scanning each
    product directory's state files — `analytics.json` (strongest signal:
    Scale/Kill/Experiment recommendation or health good/degraded/critical),
    `deployments.json` (ROLLED_BACK → KILL, LIVE → EXPERIMENT),
    `validations.json` (BUILD / TEST / KILL verdicts) — with signal
    precedence, priority ordering and normalized budget allocation.
    Reads are UTF-8 BOM tolerant (PowerShell `Set-Content` output).
  - `factory portfolio <portfolio-dir>` CLI writing `portfolio.json` +
    `portfolio.md` (each subdirectory of the portfolio root is one product).
  - 15 new tests (decision rules, analytics-over-validation precedence,
    budget normalization, CLI contract), full suite 185 passed, 1 skipped.

## [5.0.0] - 2026-09-24

### Added

- Deployment Agent (blueprint V5/§16): staged release ladder with automatic
  rollback — `STAGING_SMOKE → SECURITY_GATE → PERF_GATE → CANARY_1 → CANARY_5 →
  CANARY_25 → CANARY_100 → LIVE`; any gate failure or canary metric regression
  (error rate up / latency up / conversion down) marks the release
  `ROLLED_BACK` with the failing stage and reason.
  - `factory/schemas/deployment.py`: `ReleaseStage`, `GateResult`,
    `CanaryMetrics`, `DeploymentDecision`.
  - `factory/agents/deployment.py`: deterministic `DeploymentEngine` reading
    `deployment_config.json` and writing `deployments.json` + `deployments.md`.
  - `factory deploy <config.json>` CLI (config paths tolerant to UTF-8 BOM).
- Analytics Agent (blueprint V5/§17): turns user telemetry into the next
  iteration loop — signals / issues / recommendations (`Bug`, `Feature`,
  `Experiment`, `Optimization`, `Scale`, `Kill`) that re-enter
  Planner → Coding Agents.
  - `factory/schemas/analytics.py`: `MetricSample`, `AnalyticsIssue`,
    `Recommendation`, `AnalyticsReport` (health: good / degraded / critical).
  - `factory/agents/analytics.py`: deterministic rule engine over
    traffic / signup / activation / retention / errors / support tickets /
    feature requests / revenue / infrastructure cost.
  - `factory analyze <metrics.json>` CLI writing `analytics.json` +
    `analytics.md`.
- 24 new tests (deployment gates + rollback + agent run + CLI subprocess;
  analytics rules + CLI), full suite 170 passed, 1 skipped.

## [4.0.0] - 2026-09-24

### Added

- Validation Engine (blueprint V4): Product Council gates between a scouted
  opportunity and a build decision.
  - `factory/schemas/validation.py`: `ValidationDecision` contract with
    evidence / conversion gates, decision (KILL / TEST / BUILD), confidence,
    objections and reasons.
  - `factory/agents/validation.py`: deterministic `ValidationEngine` with
    separated roles — `DevilAdvocate` (prove this should NOT be built:
    competitor / willingness-to-pay / distribution / AI / regulatory / build
    cost / synthetic-evidence objections) and `JudgeEngine` (evidence gate →
    cheap experiment → conversion gate; strong objections downgrade BUILD to
    TEST).
  - `factory validate` CLI: reads `opportunities.json` from `factory scout`,
    writes `validations.json` + `validations.md`; supports `--opp`,
    `--evidence-threshold`, `--conversion-threshold` and repeatable
    `--conversion opp_id=0.083` to feed simulated cheap-experiment results.
  - Evidence policy: synthetic recipe candidates (evidence_count=0) fail the
    evidence gate; real web-scouted candidates pass to TEST, and pass to
    BUILD once conversion clears the threshold.

## [3.0.0] - 2026-09-24

### Added

- Market Scout Agent: turns internet signals into opportunity candidates.
  - `factory/agents/scout.py`: RecipeBackend (deterministic, no API key) and
    OpenAIBackend (enabled via `OPENAI_API_KEY`), plus
    `factory/sources.py` WebBackend that fetches real signals from Reddit /
    GitHub public APIs with defensive timeout fallback to RecipeBackend.
  - `factory scout` CLI: writes `opportunities.json` + `opportunities.md`
    (recipe or web backend; unknown backend names rejected with exit code 1).
  - `factory scout --plan` / `--plan-opp` / `--plan-out-dir`: shared
    `_plan_pipeline` (PM → Architect) turns a chosen opportunity into
    `prd.md` + `task_graph.json`, closing the scout → plan loop.
- WebBackend real-data scraping: builds candidates from live Reddit/GitHub
  signals (pains carry source URLs, `evidence_count=1`); fully-empty results
  degrade to RecipeBackend and are labeled `recipe`.

### Changed

- Version aligned to `3.0.0` for the V3 release; README (EN/zh-CN) updated with
  V3 features, quick-start `factory scout` usage, and new test baseline.

### Notes

- V3 completes the "internet → opportunity candidates → plan" stage of the
  blueprint; V4 Validation Engine is the next roadmap stage.

## [2.0.0] - 2026-09-24

### Added

- PM agent: turns a natural-language problem statement into a structured PRD
  (with explicit constraints and acceptance criteria).
- Architect agent: turns a PRD into a ready-to-run task graph (DAG) with file
  allow-lists targeting real code packages.
- `factory plan` CLI: runs PM → Architect in one command, producing
  `prd.md` + `task_graph.json` that feed directly into `factory run`.

### Changed

- Budget ledger uniqueness is now scoped per account
  (`UNIQUE(account_id, ref_type, ref_id)`) instead of globally, so multiple
  projects / re-runs no longer collide; legacy databases are migrated
  idempotently on startup (`_migrate_legacy_budget_ledger`).
- Version aligned to `2.0.0` for the V2 release; README (EN/zh-CN) updated with
  V2 features, quick-start `factory plan` usage, and new test baseline.

### Notes

- V2 completes the "problem statement → automatic product" stage of the
  roadmap: PM + Architect + plan CLI, reusing the V1 coding/verification
  pipeline unchanged.
- Test baseline: 116 passed, 1 skipped (Python 3.11); ruff clean on `E4/E7/E9/F/I`.

## [1.0.0] - 2026-09-24

### Added

- V1 core release: task-graph driven autonomous software factory.
- Formal roadmap document (`docs/ROADMAP.md`) capturing the V1-V6 blueprint and per-version acceptance direction.

### Changed

- Version aligned to `1.0.0` for the first stable V1 release.
- README roadmap section now references `docs/ROADMAP.md` instead of declaring the roadmap out-of-repo.

### Notes

- V1 capabilities shipped since `v0.1.0`: task-graph orchestration (DAG validation, topological scheduling),
  git-worktree isolation, independent machine verification gates (syntax → test → lint, fail-closed),
  rule-isolated reviewer, repair loop with hard retry cap, least-privilege policy engine,
  token/wall-clock budget guardrails, crash recovery, audit ledger, milestone promotion (`factory promote`),
  deterministic CI exit-code contract, and pluggable LLM backends (deterministic RecipeBackend by default,
  OpenAI-compatible backend when `OPENAI_API_KEY` is set).
- Test baseline: 103 passed, 1 skipped (Python 3.11); ruff clean on `E4/E7/E9/F/I`.

## [0.1.0] - 2026-09-20

### Added

- V1 core implemented and verified: task-graph factory, worktree isolation, machine verification gates,
  reviewer, budget guardrails, crash recovery, audit ledger, and milestone promotion.
- GitHub Actions CI matrix (Python 3.11 / 3.12): ruff + pytest --cov.
- Public-release README rewrite; license statement (MIT).
