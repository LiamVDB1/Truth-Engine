# Production-Ready V1: Stages 0-5

Make the existing codebase production-quality for stages 0-5 (through Gate B). No outreach.

## Current State

The codebase is **architecturally complete**. Codex built the full live path:

| Component | Status |
|---|---|
| Workflow runner (fixture + live) | ✅ Working, tested (549 lines) |
| Gate logic (A, B, Wedge) | ✅ Working, tested |
| Budget enforcement (€5/€7) | ✅ Working, tested |
| LiveActivityBundle (10 agents) | ✅ Working, **untested** |
| LiteLLMAgentRunner + tool loop | ✅ Working, tested |
| Serper / scraping / Reddit adapters | ✅ Working, **no resilience** |
| Tool schemas + permissions | ✅ Working, tested |
| Prompt builder + auto contracts | ✅ Working, tested |
| Production prompts (11 files) | ✅ Just rewritten |
| Repository (589 lines, 11 tables) | ✅ Working, tested |
| CLI (5 commands) | ✅ Working |
| Dossier (JSON + MD) | ✅ Working |
| **Tests: 40/40 pass** | ✅ Green |

## Gaps for Production

| Gap | Impact | Phase |
|---|---|---|
| No structured logging | Runs silently — can't debug live runs | 1 |
| Adapter failures crash entire run | One timeout kills everything | 1 |
| `ActivityBundle` protocol uses fixture types | Misleading naming, protocol confusion | 1 |
| No budget context in prompts | Agents can't respond to budget pressure | 2 |
| No past learnings in Scout prompts | No inter-run learning | 2 |
| Learnings system not implemented | Workflow spec requires it, `learning_entry_table` exists but unused | 3 |
| Dossier markdown is sparse | Missing scoring breakdown, cost summary, landscape | 4 |
| No live-path integration test | Live bundle untested end-to-end | 5 |
| Docs are stale | Old plan/build_state don't match code | 6 |

---

## Phase 1: Foundation Hardening

> Most critical phase — without resilience and logging, live runs are fragile and opaque.

### [MODIFY] `litellm_runner.py`

Add structured logging throughout the agent execution loop:
- Log each LLM call: `agent`, `model`, `round`, `input_tokens`, `output_tokens`, `cost_eur`
- Log tool executions: `agent`, `tool_name`, `status`
- Log JSON repair attempts: `agent`, `attempt`, `error_type`
- Log final execution summary: `agent`, `total_rounds`, `total_tokens`, `total_cost`

### [MODIFY] `serper.py`

Add resilience:
- Retry with exponential backoff (max 2 retries, 1s base) for transient failures
- Catch `httpx.TimeoutException`, `httpx.HTTPStatusError`
- Return `{"status": "error", "tool": "search_web", "reason": "..."}` instead of raising
- Structured log: `query`, `result_count`, `latency_ms`, `status`

### [MODIFY] `web.py`

Same resilience pattern for `fetch_page` and `extract_content`:
- Retry with backoff for transient HTTP errors
- Catch and return structured errors instead of raising
- Structured log: `url`, `status_code`, `latency_ms`

### [MODIFY] `praw_client.py`

Same resilience pattern:
- Catch PRAW exceptions, return structured errors
- Structured log: `query/url`, `result_count`, `status`

### [MODIFY] `candidate.py`

Add structured logging for workflow orchestration:
- Stage transitions: `candidate_id`, `stage`, `agent`, `attempt_index`, `budget_mode`
- Gate decisions: `candidate_id`, `gate`, `action`, `reason`, `score`
- Cost accumulation: `candidate_id`, `stage_cost_eur`, `total_cost_eur`, `budget_mode`
- Workflow completion: `candidate_id`, `status`, `total_cost_eur`

### [MODIFY] `base.py`

Clean up `ActivityBundle` protocol:
- Rename fixture container types to neutral names (`ArenaDiscoveryResult`, `SignalMiningRun`, etc.)
- Both `FixtureActivityBundle` and `LiveActivityBundle` satisfy the same protocol cleanly

---

## Phase 2: Prompt Builder and Context Enrichment

### [MODIFY] `builder.py`

Add budget pressure section to user prompt when `budget_mode` is in context:
- `"normal"`: no injection
- `"degrade"`: inject warning — produce tighter output, skip marginal searches
- `"safety_cap"`: inject critical warning — absolute minimum output

### [MODIFY] `live.py`

Inject enriched context into each agent call:
- Add `budget_mode` and `remaining_budget_eur` to every activity method's context
- Add `past_learnings` to Arena Scout and Signal Scout contexts (load from repository)

---

## Phase 3: Learnings System

### [NEW] `services/learnings.py`

Pure functions that extract structured learnings:

```python
def extract_kill_learnings(
    candidate_id, kill_reason, arena, scoring, skeptic
) -> list[LearningEntry]: ...

def extract_pass_learnings(
    candidate_id, dossier
) -> list[LearningEntry]: ...
```

Each produces 2-4 terse, actionable insights.

### [MODIFY] `repositories.py`

Add learnings CRUD (uses existing `learning_entry_table`):
- `store_learnings(candidate_id, entries)`
- `list_recent_learnings(limit=10)`

### [MODIFY] `candidate.py`

Wire learnings into workflow:
- On kill: extract + store kill learnings
- On pass: extract + store pass learnings

---

## Phase 4: Dossier and Reporting

### [MODIFY] `dossier.py`

Enrich markdown output:
- **Scoring Breakdown** table: all 9 dimensions with score, evidence, rationale
- **Landscape Summary**: competitor/dead-attempt counts, market density, key lessons
- **Skeptic Assessment**: evidence integrity, risk, primary weakness, recommendation
- **Cost Summary**: per-stage cost table + total
- **Caution Flags**: list (if any)

### [MODIFY] `stages.py`

Add cost fields to `CandidateDossier`:
- `cost_breakdown: dict[str, float]` (stage → EUR)
- `total_cost_eur: float`

### [MODIFY] `candidate.py`

Pass cost breakdown into `_build_dossier()`:
- Query cost records from repository, aggregate by stage

---

## Phase 5: Testing

### [NEW] `tests/integration/test_live_activity_bundle.py`

Live-path integration test:
- Mock `completion_fn` with canned LLM responses
- Real SQLite DB + real repository
- Verify: all agents execute, tool calls dispatch, state persists, dossier generated

### [NEW] `tests/unit/test_adapter_resilience.py`

Adapter error handling:
- Serper: timeout → structured error (not exception)
- Serper: HTTP 429 → structured error
- Web: timeout → structured error
- Reddit: PRAW exception → structured error

### [NEW] `tests/unit/test_learnings.py`

Learnings system:
- Kill learnings produce 2-4 entries
- Pass learnings produce 2-4 entries
- Repository store + retrieve works

---

## Phase 6: Documentation Refresh

### [DELETE] `planning/implementation_plan.md`

Old plan — replaced by `planning/implementation_contract.md`.

### [DELETE] `planning/build_state.md`

Old state — no longer accurate.

### [MODIFY] `planning/implementation_contract.md`

Update to reflect production state.

### [MODIFY] `AGENTS.md`

Update project snapshot.

### [MODIFY] `README.md`

Add logging, learnings, updated verification.

---

## Verification Plan

### Automated

```bash
ruff format .
ruff check .
mypy .
pytest -v
```

Expected: ~55-60 tests, all green.

### Manual (requires API keys)

```bash
cp .env.example .env
# Fill: TRUTH_ENGINE_OPENAI_API_KEY, TRUTH_ENGINE_SERPER_API_KEY

python -m truth_engine init-db --database-url sqlite:///./truth_engine_live.db
python -m truth_engine run-live \
  --request-file examples/live_request.json \
  --database-url sqlite:///./truth_engine_live.db \
  --output-dir ./out/live \
  --prompt-version live-v1
```

Verify:
1. Structured log lines show stage transitions, gate decisions, cost tracking
2. If passed: dossier has scoring breakdown, channel map, cost summary
3. If killed: logs show kill reason and learnings extraction
4. No unhandled exceptions from adapter failures
