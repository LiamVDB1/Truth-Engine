# Build State

Last updated: 2026-03-10

## Current Phase

- Current implementation phase: Phases 0-3 complete
- Repo state: executable v0.1 core
- Workflow runtime: fixture-backed candidate runner through Gate B

## MVP Boundary

- v0.1 boundary: Phases 0-3 inclusive
- Product boundary: Gate B
- Output boundary: operator-ready dossier, not autonomous outbound

## Frozen Contracts

- Stack direction: Temporal + PostgreSQL + LiteLLM + Instructor/Pydantic
- High-level v0.1 boundary: Gate B
- Live autonomous outbound in v0.1: no
- Canonical implementation freeze: `docs/implementation_contract.md`
- Canonical Normalizer tier: Tier 2
- Canonical v0.1 dedup: deterministic fingerprint, not embeddings

## Open Decisions

- No blocking implementation-contract decisions remain
- Provider/API credential setup remains external
- Brand and sending-domain choices still matter before outbound phases

## Active Tasks

- Harden live provider adapters behind the existing activity contracts
- Add Temporal worker wiring around the deterministic workflow core
- Add prompt evals and richer fixture coverage

## Recently Completed

- Full repo audit completed
- Implementation plan created in `docs/implementation_plan.md`
- v0.1 boundary clarified as Gate B / Phases 0-3 inclusive
- `docs/implementation_contract.md` created and frozen
- Gate sequencing, budgets, dedup strategy, and Normalizer tier frozen for implementation
- Python project scaffold created (`pyproject.toml`, `src/`, `tests/`, `.env.example`, `docker-compose.yml`)
- Initial config layer implemented
- v0.1 stage contracts implemented for arena, signal, normalization, landscape, scoring, skeptic, wedge, buyer/channel, and dossier artifacts
- Repository-backed persistence implemented for candidates, stage runs, arenas, signals, problem units, landscape entries, wedges, channel plans, decisions, and cost logs
- Initial Alembic migration scaffold implemented and verified against SQLite
- Fixture activity bundle implemented for deterministic end-to-end runs
- Deterministic candidate workflow implemented through Gate B with:
  - targeted evidence loop
  - wedge refinement loop
  - Gate B retry logic
  - degrade-mode loop suppression
- Tool runtime enforcement implemented for the v0.1 CRUD/read tools
- Prompt builder upgraded to persist configured prompt version + prompt hash on stage runs
- Dossier generation implemented in Markdown + JSON
- CLI commands implemented for schema init, fixture execution, and dossier export
- Integration tests added for:
  - Gate B happy path with investigate/revise/retry loops
  - Gate B retry kill path
  - degrade-mode retry suppression
- Local verification passing: `pytest`, `ruff check`, `mypy`, `alembic upgrade head`
- Tools architecture added to `docs/implementation_plan.md`
- Prompt architecture added to `docs/implementation_plan.md`
- Living repo-state tracking initialized in `docs/build_state.md`
- External consultation attempted:
  - Gemini consult succeeded
  - GLM-5 consult failed due provider/tooling error
  - Kimi K2.5 consult failed due tooling validation error

## Tool Registry Status

- Explicit tools architecture: defined in docs
- Tool registry code: implemented
- Per-agent tool bundles: implemented
- Tool runtime enforcement: implemented for v0.1 persistence tools

## Prompt System Status

- Prompt architecture: defined in docs
- Prompt manifest format: not finalized
- Prompt builder: implemented for v0.1
- Prompt hash/version persistence: implemented on stage runs
- Prompt eval harness: not started

## Model Routing Status

- Tiering exists in docs
- Runtime aliases/config implemented
- Model-family overlays not implemented

## Eval Status

- Unit tests: implemented
- Integration tests: implemented
- Workflow replay tests: covered via deterministic fixture runs
- Prompt evals: not started

## External Prerequisites

- Brand/company name
- Sending domain
- SPF/DKIM/DMARC setup
- Provider API keys
- Suppression-list and unsubscribe approach

## Current Blockers

- No v0.1 blockers remain inside the frozen scope
- Live provider credentials are still required before replacing fixtures with real adapters
- Temporal worker bootstrap is still an integration task, not a product-scope blocker

## Next Recommended Tasks

1. Add live search/fetch/reddit adapters behind the existing activity interfaces
2. Add Temporal worker/bootstrap wiring for the existing deterministic workflow core
3. Expand fixture coverage to additional kill paths and safety-cap scenarios
4. Add prompt evaluation harness and golden dossier checks
5. Begin post-v0.1 Phase 4 planning only after dossier quality is manually reviewed
