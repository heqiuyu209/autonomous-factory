# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
