# Truth Engine V1 Implementation Plan

Date: 2026-03-10

## Purpose

Turn the current design corpus into an executable system without trying to build the entire 13-agent vision in one pass.

The right implementation strategy is:

1. Build the deterministic spine first.
2. Make the evidence ledger and gate logic executable before expanding agent breadth.
3. Stop MVP v0.1 at an operator-ready opportunity dossier, not at full autonomous outreach.
4. Add outbound automation only after the upstream scoring and wedge logic are stable on real runs.

## Repo Reality

This repository is still a design repository, not a software repository.

- There is no runtime scaffold.
- There is no package metadata, migrations, tests, or worker setup.
- There is no executable schema for the stage contracts defined in `truth_engine_v1_agent_workflow.md`.
- The source-of-truth docs are strong on workflow intent, but they still need translation into code-level interfaces, persistence boundaries, and test fixtures.

That means the first milestone is not "implement agents". The first milestone is "make the system shape executable."

Before code starts, implementation-specific ambiguities are frozen in `docs/implementation_contract.md`.

## Recommended MVP Boundary

### MVP v0.1 should include

- Stages 0-5 only:
  - Arena Discovery
  - Signal Mining
  - Normalization
  - Landscape + Scoring + Skeptic
  - Wedge Design
  - Buyer/Channel Validation
- A deterministic Temporal workflow for candidate progression through Gate B.
- A PostgreSQL-backed evidence ledger and audit trail.
- Typed agent contracts with Pydantic models.
- Budget accounting, circuit breakers, kill reasons, and replayable decision history.
- Lead sourcing and channel planning outputs.
- A generated candidate dossier in Markdown/JSON for human review and manual outbound execution.
- In phase terms: v0.1 = Phases 0-3 inclusive in this document.

### MVP v0.1 should not include

- Autonomous message sending.
- LinkedIn, Reddit, or X automation.
- Multi-turn autonomous conversation handling.
- Commitment closing automation.
- Auto-injected learnings that materially change prompts at runtime.
- Embedding-based arena dedup as a hard dependency.
- A polished web dashboard.
- Broad multi-candidate concurrency.

Why: the highest implementation risk is not "can an LLM draft outbound messages." It is "can the system produce a trustworthy, replayable, evidence-backed candidate recommendation that survives skeptical review." That has to work first.

## Target System Shape

Use a modular Python codebase with clear separation between deterministic orchestration, pure decision logic, and side-effecting adapters.

Suggested top-level layout:

```text
src/truth_engine/
  config/
  contracts/
  domain/
  services/
  tools/
  workflows/
  activities/
  adapters/
    db/
    llm/
    search/
    scraping/
    reddit/
  prompts/
  reporting/
  cli/
tests/
  unit/
  integration/
  workflow/
  fixtures/
migrations/
```

### Architectural rules

- `workflows/`: Temporal workflows only. No network, no DB writes outside approved activity calls, no prompt construction.
- `activities/`: side effects only. Search, fetch, parse, LLM calls, persistence writes, cost logging.
- `services/`: pure domain logic. Scoring, gating, clustering heuristics, budget math, dedup rules, report assembly.
- `contracts/`: Pydantic request/response models per agent and per workflow event.
- `tools/`: agent-visible tool contracts, registry, bundles, and policy.
- `adapters/`: provider-specific code behind narrow interfaces.

This keeps the system testable and protects the workflow layer from prompt and provider churn.

## Tool Architecture

I do think the plan needed an explicit tools section.

The current `activities/` and `adapters/` split is necessary, but it is not sufficient on its own, because tools are not just implementation details. In this system, tools are part of the agent contract surface.

What should exist:

- A tool contract layer: what the tool is, how agents see it, what schema it accepts, what schema it returns, what side effects it is allowed to have.
- A tool execution layer: the adapter or activity that actually performs the work.
- A tool access layer: which agents are allowed to call which tools, under what limits and readiness flags.

Recommended shape:

- `tools/specs.py`: `ToolSpec`, `ToolInput`, `ToolOutput`, `ToolCallPolicy`
- `tools/registry.py`: canonical tool registration and lookup
- `tools/bundles.py`: per-agent tool bundles
- `tools/runtime.py`: tool-call validation, rate limiting, and call logging

Recommended `ToolSpec` fields:

- `name`
- `description`
- `input_model`
- `output_model`
- `side_effect_level`
- `cost_class`
- `cache_policy`
- `retry_policy`
- `required_flags`
- `adapter_key`

Rules:

- Agents should receive tool manifests from the registry, not handwritten tool descriptions embedded ad hoc in prompts.
- Tools should be versioned and logged just like prompts and model calls.
- Rate limits, readiness checks, and budget guards should be enforced in code, not merely described in prompts.
- Do not turn the registry into a giant abstract framework. Start with the 8-12 real tools the system actually needs.

Concrete v0.1 tool categories:

- search tools
- fetch/extract tools
- Reddit ingestion tools
- persistence/reporting tools
- candidate CRUD tools for Arena Scout, Signal Scout, and Landscape Scout
- cost and policy guard tools

Concrete v0.1 tool manifest:

- `create_arena_proposal`
- `edit_arena_proposal`
- `remove_arena_proposal`
- `view_arena_proposals`
- `add_signal`
- `view_signal_summary`
- `add_landscape_entry`
- `view_landscape`
- `search_web`
- `fetch_page`
- `extract_content`
- `reddit_search`
- `reddit_fetch`

What I would not do:

- I would not add a giant top-level "all tools in the business" catalog before the first workflow exists.
- I would not mix raw provider clients with agent-visible tool contracts.
- I would not let every agent define its own tool schema.

## Prompt Architecture

A prompt factory is a good idea, but only if it is boring, layered, and testable.

The right mental model is not "one global prompt plus dozens of custom prompt hacks." The right mental model is "compiled prompt bundles from a small number of stable layers."

Recommended layers:

1. Global invariant layer:
   - evidence-backed claims only
   - budget discipline
   - compliance constraints
   - response formatting norms
2. Stage or domain layer:
   - Stage 0 discovery rules
   - Stage 3 scoring rules
   - Stage 4 wedge rules
3. Agent role layer:
   - Arena Scout behavior
   - Skeptic behavior
   - Buyer/Channel Validator behavior
4. Tool layer:
   - tool bundle injected from the tool registry
   - tool usage constraints and failure semantics
5. Model or tier overlay:
   - tiny deltas for cheap vs premium models
   - only when needed
6. Runtime context layer:
   - candidate state
   - evidence excerpts
   - learnings
   - budget state
   - explicit output contract
7. Optional few-shot examples:
   - versioned examples for tricky agents only

Recommended file layout:

```text
src/truth_engine/prompts/
  shared/
    invariants.md
    evidence_policy.md
    compliance_policy.md
    formatting.md
  tiers/
    tier1.md
    tier2.md
    tier3.md
  model_families/
    gpt.md
    glm.md
    kimi.md
  agents/
    arena_scout/
      manifest.yaml
      role.md
      examples/
    scorer/
      manifest.yaml
      role.md
      examples/
    skeptic/
      manifest.yaml
      role.md
      examples/
```

Recommended `manifest.yaml` fields:

- `agent_id`
- `inherits`
- `required_context_keys`
- `tool_bundle`
- `output_contract`
- `few_shot_set`
- `tier_overlay`
- `model_family_overrides`

How the prompt factory should work:

- Input: `agent_id`, `candidate_context`, `model_profile`, `tool_bundle`, `contract`
- Output: `CompiledPromptBundle`
- `CompiledPromptBundle` should contain:
  - `system_prompt`
  - `user_prompt`
  - `tool_manifest`
  - `output_contract`
  - `prompt_version`
  - `prompt_hash`

Important design constraints:

- Keep model-specific overrides tiny. Most behavior should be agent-level, not model-level.
- Do not fork full prompts per provider unless absolutely necessary.
- Never hide prompt strings inside activity code except for tiny repair prompts.
- Persist `prompt_hash`, `prompt_version`, and `output_contract_version` on every agent artifact.
- Test prompt compilation separately from workflow execution.

My challenge to the "global prompts" idea:

- Yes, you want shared invariants.
- No, you do not want huge global prompts that every agent inherits blindly.

If the global layer grows too large, it becomes hidden coupling. Keep the global layer limited to rules that are truly universal. Most behavior should live at the agent-role layer.

### Phase 0-1 prompt implementation boundary

In Phase 0-1, keep the prompt system intentionally simple:

- create the directory structure
- create shared invariant files
- create agent role files for the v0.1 agents
- implement a simple prompt builder
- persist `prompt_hash` and `prompt_version`

Do not build the full manifest composition engine, few-shot management, or provider-specific overlay system before the workflow spine exists.

## Runtime Evolution Beyond v0.1

For v0.1 and likely v0.2, keep the architecture as agent-as-activity.

That means:

- Temporal orchestrates.
- Activities call models and tools.
- Outputs are typed.
- State is stored in Postgres.

I would not build a fully general "agents talking to agents" runtime early. That is the fastest path to complexity without clarity.

For the full implementation, I do think there is room for a more session-based worker model, but only for the stages that genuinely need long-lived inner loops:

- Arena Scout
- Signal Scout
- Conversation Agent
- potentially Commitment Closer

The other agents should remain single-purpose contract workers for as long as possible:

- Arena Evaluator
- Normalizer
- Scorer
- Skeptic
- Wedge Designer
- Wedge Critic
- Buyer/Channel Validator

If you later add worker sessions, the shape should be:

- Temporal remains the parent orchestrator.
- A worker session is a subordinate durable runtime, not a peer orchestrator.
- Every session has:
  - a parent candidate or lead
  - allowed tool bundle
  - budget cap
  - stop conditions
  - event log
  - resumable state snapshot

That gives you the benefits of sub-agents without turning the whole system into an opaque autonomous mesh.

## Living State Document

Yes, I think this is needed.

The implementation plan is the target. The repo also needs a living operational document that answers: where are we now, what is frozen, what changed, what is blocked, and what is next.

Recommended file:

- `docs/build_state.md`

Recommended sections:

- current phase
- MVP boundary
- frozen contracts
- open decisions
- active tasks
- recently completed work
- tool registry status
- prompt-system status
- model routing status
- eval status
- external prerequisites
- current blockers

Rules for this document:

- Keep it short and operational.
- Update it when a phase closes, a contract changes, or a blocker appears.
- Do not turn it into a narrative diary.
- Use it as the human-facing source of truth for repo progress.

## Delivery Phases

## Phase 0: Foundation And Scaffolding

### Goal

Create a repo that can be developed, run, and tested predictably.

### Deliverables

- `pyproject.toml` with runtime and dev dependencies.
- `src/` package layout and `python -m truth_engine` entrypoint.
- Ruff, mypy, pytest, and pre-commit configuration.
- Local dev stack for PostgreSQL and Temporal.
- Environment settings via `pydantic-settings`.
- Structured logging baseline.
- Minimal CI for format, lint, typecheck, and unit tests.

### Exit criteria

- Fresh clone can boot the dev environment.
- `ruff format .`, `ruff check .`, `mypy .`, and `pytest -q` run cleanly.
- A no-op worker and workflow can start locally.

### Risks retired

- Repo chaos.
- Hidden environment drift.
- Delayed test adoption.

## Phase 1: Executable Contracts And Persistence

### Goal

Translate the workflow docs into stable, typed domain contracts and durable storage.

### Deliverables

- Pydantic models for:
  - `RawArena`
  - `EvaluatedArena`
  - `RawSignal`
  - `ProblemUnit`
  - `LandscapeEntry`
  - `ScoredCandidate`
  - `SkepticReport`
  - `WedgeHypothesis`
  - `ChannelPlan`
  - `DecisionEvent`
  - `CostRecord`
- Initial Postgres schema with Alembic migrations for:
  - `arena`
  - `candidate`
  - `candidate_stage_run`
  - `processed_source`
  - `raw_signal`
  - `problem_unit`
  - `problem_unit_evidence`
  - `landscape_entry`
  - `wedge_hypothesis`
  - `channel_plan`
  - `decision_event`
  - `cost_log`
  - `learning_entry`
- Repository interfaces and storage adapters.
- Versioned prompt spec files rather than prompt strings hidden in code.

### Implementation notes

- Keep raw page text and parsed evidence in Postgres initially. Do not add object storage in v0.1.
- Start arena dedup with deterministic fingerprints plus optional similarity placeholders. Add embeddings later.
- Treat `decision_event` as append-only.
- Every stage transition should have an auditable reason.

### Exit criteria

- All core entities are serializable, persisted, and reloadable.
- A candidate can be reconstructed from database state alone.
- Contract tests lock the serialized shape of the main agent outputs.

### Risks retired

- Schema churn breaking workflows.
- Prompt outputs not matching storage shape.
- Missing provenance.

## Phase 2: Deterministic Candidate Workflow Through Gate A

### Goal

Implement the minimum valuable execution path: arena -> evidence -> normalized problems -> landscape -> score -> skeptic -> Gate A decision.

### Deliverables

- Temporal workflow for a single candidate lifecycle through Gate A.
- Activity contracts for:
  - arena search
  - arena evaluation
  - source search
  - page fetch/extract
  - signal parsing
  - normalization
  - Landscape Scout tool bundle and landscape collection
  - scoring
  - skeptic review
  - targeted evidence pass
- Pure services for:
  - scoring rubric
  - gate thresholds
  - circuit breakers
  - budget policy
  - deterministic retry policy selection
- Cost tracking on every tool and model call.
- Markdown/JSON reporting for candidate evidence and Gate A outcome.

### Implementation notes

- Do not start with all source types. Support only:
  - Reddit via PRAW
  - job postings
  - low-friction public web pages
- Treat G2/Capterra-style extraction as feature-flagged in v0.1, not mandatory on day one.
- Do not optimize clustering first. Implement a simple, typed normalizer that can be improved later.
- Keep the targeted evidence loop bounded exactly as specified in the workflow doc.
- Make score explanations first-class outputs, not log-only text.
- Write the first pure-logic tests against Gate A, the targeted evidence loop, the wedge loop, and Gate B before broad adapter work.

### Exit criteria

- One candidate can run end-to-end through Gate A on saved fixtures.
- Workflow replay is deterministic.
- Budget breakers and kill logic are covered by tests.
- Failures at any activity boundary produce structured stage failure records.

### Risks retired

- The biggest architecture risk: nondeterministic orchestration coupled to mutable prompts.
- False confidence from untracked evidence transformations.
- Budget policy not actually enforced.

## Phase 3: Wedge And Reachability Engine

### Goal

Turn a passing candidate into an operator-ready wedge and channel plan.

### Deliverables

- Wedge Designer and Wedge Critic activities.
- Buyer/Channel Validator activity.
- Gate B logic.
- Lead-list estimation and channel strategy outputs.
- A compiled candidate dossier containing:
  - top evidence
  - scoring rationale
  - skeptic flags
  - selected wedge
  - ICP and buyer map
  - first-20 outreach plan

### Implementation notes

- Keep lead sourcing read-only in v0.1. Produce targets and message angles, not sends.
- Human review happens from the dossier, not a full web app.
- Treat Gate B as the MVP handoff boundary.

### Exit criteria

- A founder can review one dossier and manually run outbound from it without needing to inspect raw DB rows.
- Wedge refinement and Gate B retries are deterministic and tested.

### Risks retired

- Premature investment in sending infrastructure.
- Building outbound automation before the pitch is clear.

## Phase 4: Assisted Outreach, Not Full Autonomy

### Goal

Add just enough outbound support to validate the downstream workflow safely.

### Deliverables

- Email-only outbound support.
- Compliance policy engine:
  - business-email validation
  - suppression checks
  - opt-out link enforcement
  - sender identity requirements
- Reply classification and draft response generation.
- Human approval before send.
- Lead and conversation storage models.

### Explicitly defer

- LinkedIn automation.
- Reddit/X posting automation.
- autonomous send-without-review.
- autonomous negotiation.
- commitment closing without human involvement.

### Exit criteria

- Human can approve, send, and track compliant outreach from system-generated drafts.
- Incoming replies can be classified and summarized with evidence quotes.

## Phase 5: Controlled Autonomy Expansion

### Goal

Expand automation only after upstream quality is acceptable on real runs.

### Candidate additions

- selective autonomous reply handling
- commitment tracking
- learnings capture and later prompt injection
- embedding-based arena dedup
- minimal operator dashboard
- multi-candidate scheduling and queueing

This phase should be gated by real evidence that v0.1/v0.2 recommendations correlate with useful conversations.

## Major Risks And Mitigations

## Architectural risks

### 1. Overbuilding the 13-agent vision too early

Risk:
Trying to implement the full stage graph immediately will create brittle workflows, diffuse test effort, and unclear failure ownership.

Mitigation:
- Make Gate B the first serious product boundary.
- Implement only the agents required to produce an operator-ready dossier.
- Use stubs and fixed fixtures for downstream stages until upstream outputs stabilize.

### 2. Hidden coupling between prompts, persistence, and orchestration

Risk:
If agent prompts define fields implicitly, the database and workflow logic will drift.

Mitigation:
- Define Pydantic contracts before prompt text.
- Version prompt specs.
- Persist normalized outputs, not raw assistant prose.
- Add contract tests for every agent output schema.

### 3. Temporal nondeterminism

Risk:
It is easy to leak clocks, randomness, network calls, or mutable config into workflow code.

Mitigation:
- Keep all side effects in activities.
- Centralize workflow state transitions in pure functions.
- Add replay tests for every looped stage and kill path.

### 4. Evidence provenance loss

Risk:
If quotes, source URLs, and transformation steps are not durable, the system becomes persuasive but unverifiable.

Mitigation:
- Store raw evidence rows with provenance.
- Link every score explanation to evidence IDs.
- Make `decision_event` append-only and queryable.

## Product risks

### 5. Scraped signals being mistaken for validation

Risk:
The system may optimize for "interesting internet complaints" instead of markets that buy.

Mitigation:
- Keep reliability caps enforced in code.
- Penalize low source diversity and weak spend signals.
- Do not claim validation before direct buyer interaction.

### 6. False precision in scoring

Risk:
Weighted scores can look objective before calibration.

Mitigation:
- Keep dimension evidence visible.
- Track outcomes against first 10-20 real candidates.
- Defer auto-tuning and learned scoring until enough data exists.

### 7. Wedge design drifting away from evidence

Risk:
LLMs will happily invent a product thesis that sounds better than the observed pain.

Mitigation:
- Require wedge outputs to cite which problem-unit fields they are addressing.
- Keep Wedge Critic mandatory before Gate B.
- Add regression fixtures where a wedge should be rejected.

## Operational risks

### 8. Scraper fragility and provider churn

Risk:
The pipeline depends on several external services and some target sources are hostile to scraping.

Mitigation:
- Wrap each provider behind an adapter interface.
- Save fixture pages from representative sources.
- Start with three priority source types only.
- Treat scraper failure as a normal, structured outcome.

### 9. Outreach compliance and sender reputation

Risk:
Autonomous outbound can create legal, domain, and reputation issues before the core engine is even useful.

Mitigation:
- No autonomous sending in v0.1.
- Build the compliance policy engine before any send capability.
- Use a dedicated sending domain and suppression ledger when outbound begins.

### 10. Cost drift

Risk:
The system is designed around cost ceilings but the implementation could accidentally spend without discipline.

Mitigation:
- Log cost per call from day one.
- Enforce circuit breakers in workflow control flow, not in prompts.
- Add tests for degrade-mode and safety-cap transitions.

## Testing risks

### 11. Too much live-network testing

Risk:
If tests depend on live search, live pages, and live model outputs, the suite will be flaky and non-diagnostic.

Mitigation:
- Use frozen fixtures for search results, raw HTML, extracted text, and model outputs.
- Limit live integration tests to opt-in smoke runs.
- Build a replayable evaluation corpus before scaling feature work.

### 12. No quality bar for agent outputs

Risk:
Passing schema validation is not enough; the output can still be wrong or useless.

Mitigation:
- Add golden dossiers for representative candidates.
- Add rubric-level assertions for scoring and gate logic.
- Review actual dossier quality manually before automating downstream stages.

## Test Strategy

### Unit tests

- scoring math
- gate logic
- budget transitions
- reliability caps
- dedup rules
- prompt-to-contract parsing adapters
- lead qualification formulas

### Integration tests

- repository persistence
- migration application
- adapter behavior with recorded fixtures
- cost logging
- compliance engine behavior

### Workflow tests

- happy path through Gate A
- targeted evidence loop
- wedge refinement loop
- Gate B retry and kill path
- budget exhaustion mid-stage
- activity retry and skip semantics

### Live smoke tests

- one search provider request
- one scraper fetch per supported source class
- one LLM call per configured tier

These should be explicitly marked and never required for normal CI.

## What To Decide Before Phase 4

- Dedicated sending domain and brand identity.
- Which lead source will back buyer/channel validation first.
- Whether the first operator experience is CLI-only or a thin internal web view.
- Which real markets will be used as the first calibration set.
- Whether founder advantage will be a static config input or a scored artifact.

None of these should block Phase 0-3.

## Recommended First Build Order

1. Scaffold the Python project and local infra.
2. Implement contracts and migrations.
3. Build persistence and reporting.
4. Implement the candidate workflow through Gate A on frozen fixtures.
5. Run three replayable fixture candidates end-to-end.
6. Add live source adapters for the three priority source classes.
7. Implement wedge and Gate B.
8. Produce operator dossiers and use them manually.
9. Only then add assisted outbound.

## Success Criteria

The implementation is on track when the system can reliably do this:

1. Ingest evidence with provenance.
2. Produce a scored candidate with transparent rationale and skeptic flags.
3. Design a wedge and channel plan tied to the evidence.
4. Generate a dossier good enough for a human to run the first 20 conversations manually.
5. Stay inside budget and preserve a full audit trail.

If it cannot do those five things, adding autonomous outreach will amplify noise, not value.
