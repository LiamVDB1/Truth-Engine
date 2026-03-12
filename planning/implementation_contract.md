# Truth Engine V1 Implementation Contract

Date: 2026-03-10
Status: frozen for implementation start

## Purpose

This document freezes the ambiguous values required to start implementation.

Use this document as the canonical implementation contract whenever the planning docs disagree on:

- gate sequencing
- per-stage budgets
- agent tiers
- v0.1 scope boundaries
- v0.1 tool manifest
- v0.1 dedup behavior
- prompt-system implementation scope

It does not replace the product workflow. It resolves implementation ambiguities so code can start without inventing policy.

## v0.1 Boundary

v0.1 is Phases 0-3 inclusive in `implementation_plan.md`.

That means:

- stages implemented in v0.1: 0-5
- product boundary in v0.1: Gate B
- output in v0.1: operator-ready dossier
- excluded from v0.1: live autonomous outbound, autonomous conversations, commitment closing automation, prompt injection from learnings

## Canonical Gate Sequencing

For implementation:

- Gate A = Stage 3 research viability gate after Landscape Scout + Scorer + Skeptic
- Gate B = Stage 5 reachability gate after Wedge Design + Buyer/Channel Validation
- Gate C = Stage 7 commitment threshold gate

The earlier reachability language in `resolved_decisions.md` is treated as the decision rationale behind Gate B, not as the runtime definition of Gate A.

## Canonical v0.1 Agent Tier Decisions

These values are frozen for implementation:

| Agent | Canonical Tier | Notes |
|---|---|---|
| Arena Scout | Tier 1 | Tool-based |
| Arena Evaluator | Tier 2 | Convergent scoring |
| Signal Scout | Tier 1 | Tool-based |
| Normalizer | Tier 2 | Canonicalized here; roster/model-map drift is resolved in favor of the detailed Stage 2 section |
| Landscape Scout | Tier 1 | Tool-based |
| Scorer | Tier 2 | |
| Skeptic | Tier 3 | |
| Wedge Designer | Tier 2 | |
| Wedge Critic | Tier 3 | |
| Buyer/Channel Validator | Tier 2 | |
| Outreach Operator | Tier 2 | Post-v0.1 |
| Conversation Agent | Tier 3 | Post-v0.1 |
| Commitment Closer | Tier 3 | Post-v0.1 |
| Analyst | Tier 2 | Runtime learnings injection deferred from v0.1 |

## Canonical Budget Table

This is the implementation budget table.

| Stage | Budget | Notes |
|---|---|---|
| 0: Arena Discovery | €0.15 | Scout + Evaluator |
| 1: Signal Mining | €0.30 | |
| 2: Normalization | €0.15 | Single pass target |
| 3: Landscape + Scoring + Skeptic | €0.60 | €0.30 base + up to €0.30 investigation |
| 4: Wedge Design | €0.40 | |
| 5: Buyer/Channel | €0.15 | |
| 6: Outreach + Conversations | €1.00 | Post-v0.1 |
| 7: Commitment | €0.20 | Post-v0.1 |
| Cross-cutting Analyst | €0.05 | Post-v0.1 runtime |
| **Total planned** | **€3.00** | **Soft candidate budget remains €5.00** |

Clarifications:

- The `Maze Historian` label is retired. The intended Stage 3 agent is `Landscape Scout`.
- Stage 3 base budget is implemented as Landscape Scout + Scorer + Skeptic.
- The grouped bucket table in `resolved_decisions.md` is treated as a high-level envelope, not the canonical stage-level budget source.

## Canonical v0.1 Dedup Strategy

For v0.1:

- do not implement embedding-based arena dedup
- do implement deterministic fingerprint dedup

Arena fingerprint:

- normalized `domain`
- normalized `icp_user_role`

Behavior in v0.1:

- exact fingerprint match against killed arenas = block proposal
- no semantic similarity thresholds in v0.1
- store placeholder fields so embeddings can be added later without reshaping the table

## Canonical v0.1 Tool Manifest

### Agent-facing tools

| Agent | Tool | Purpose | Side effects |
|---|---|---|---|
| Arena Scout | `create_arena_proposal` | Save new raw arena proposal | DB write + dedup check |
| Arena Scout | `edit_arena_proposal` | Update raw arena proposal | DB update |
| Arena Scout | `remove_arena_proposal` | Remove weak proposal | DB delete |
| Arena Scout | `view_arena_proposals` | Inspect current proposal set | DB read |
| Signal Scout | `add_signal` | Persist raw signal | DB write + URL dedup |
| Signal Scout | `view_signal_summary` | Inspect signal coverage | DB read |
| Landscape Scout | `add_landscape_entry` | Persist landscape finding | DB write |
| Landscape Scout | `view_landscape` | Inspect landscape coverage | DB read |

### Shared infrastructure tools and adapters

| Name | Purpose | Visibility in v0.1 |
|---|---|---|
| `search_web` | Serper-backed search | available to Arena Scout, Signal Scout, Landscape Scout |
| `read_page` | page fetching + HTML-to-main-content extraction | available to Arena Scout, Signal Scout, Landscape Scout |
| `reddit_search` | Reddit discovery via PRAW | available to Arena Scout, Signal Scout |
| `reddit_fetch` | fetch Reddit thread/post content | available to Signal Scout |

### v0.1 source scope

Start with:

- Reddit via PRAW
- job postings
- low-friction public web pages

Treat these as optional in v0.1:

- G2/Capterra hard-source extraction
- embedding services
- LinkedIn or outbound channel APIs

## Canonical Prompt-System Implementation Scope

The long-term prompt architecture in `implementation_plan.md` remains valid, but the implementation scope for Phase 0-1 is intentionally smaller.

Phase 0-1 prompt work includes:

- prompt directory structure
- shared invariant markdown files
- agent role markdown files for the v0.1 agents
- a simple `build_prompt(agent_id, context) -> str | PromptBundle`
- persisted `prompt_hash` and `prompt_version`

Phase 0-1 explicitly does not include:

- full manifest composition engine
- provider-specific prompt forks
- few-shot injection framework
- learnings injection at runtime

Those can be added in Phase 2 after the basic workflow spine exists.

## Canonical Operator Interface Decision

For v0.1:

- operator interface = dossier-first
- review surface = CLI + Markdown/JSON dossier
- thin internal web surface = optional after v0.1

## Canonical Learnings Decision

For v0.1:

- keep the `learning_entry` schema in the database
- do not let learnings modify runtime prompts yet
- analyst retrospective runtime can be deferred to post-v0.1

## First Tests To Write

Write these first, before broad adapter work:

1. Gate A decision logic
2. Targeted evidence pass loop
3. Wedge refinement loop
4. Gate B decision logic
5. Budget circuit-breaker transitions

## Start Condition For Implementation

Implementation can begin once:

- this contract exists
- the implementation plan references it
- build state no longer lists unresolved spec contradictions as a blocker
