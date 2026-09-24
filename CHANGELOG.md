# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
