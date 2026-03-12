# Runtime

This page describes how the repo is executed today.

## CLI Commands

| Command | Purpose |
|---|---|
| `python -m truth_engine init-db` | apply Alembic migrations |
| `python -m truth_engine db-stats` | print candidate / arena / signal counts and status breakdowns |
| `python -m truth_engine db-clear-unexplored-arenas` | remove queued arenas that were never explored |
| `python -m truth_engine db-reset --yes` | wipe all runtime tables |
| `python -m truth_engine run-fixture --fixture <file>` | submit a Temporal fixture workflow through Gate B |
| `python -m truth_engine run-live` | submit a Temporal live workflow for stages `0-5` |
| `python -m truth_engine run-worker` | run a dedicated Temporal worker for Truth Engine workflows |
| `python -m truth_engine export-dossier --candidate-id <id>` | write stored dossier artifacts to disk |
| `python -m truth_engine preview-prompt --agent <name> --context-file <json>` | print compiled prompt text |

Defaults come from `Settings`, so `--database-url` and `--output-dir` are optional for the main commands.
`run-fixture` and `run-live` start an inline worker by default; use `--no-inline-worker` when a
separate `run-worker` process is already running.

Important safety default:
- `run-fixture` now defaults to `sqlite:///./truth_engine.fixture.db` instead of the live/default database URL.
- `run-live` still defaults to `TRUTH_ENGINE_DATABASE_URL` / `Settings.database_url`.

## Configuration

Environment variables are loaded through `pydantic-settings` with the `TRUTH_ENGINE_` prefix.

### Common settings

| Variable | Meaning |
|---|---|
| `TRUTH_ENGINE_DATABASE_URL` | database URL, defaulting to local PostgreSQL in settings |
| `TRUTH_ENGINE_TEMPORAL_HOST` | Temporal frontend host, default `localhost:7233` |
| `TRUTH_ENGINE_TEMPORAL_NAMESPACE` | Temporal namespace, default `default` |
| `TRUTH_ENGINE_TEMPORAL_TASK_QUEUE` | Temporal task queue, default `truth-engine` |
| `TRUTH_ENGINE_PROMPT_VERSION` | version string stamped onto compiled prompts and stage runs |
| `TRUTH_ENGINE_LOG_LEVEL` | not read by `Settings`; the CLI takes `--log-level` instead |
| `TRUTH_ENGINE_AGENT_MAX_TOOL_ROUNDS` | max tool-using LLM rounds per agent |
| `TRUTH_ENGINE_TIER1_MODEL` / `TIER2_MODEL` / `TIER3_MODEL` | default models for agent tiers |
| `TRUTH_ENGINE_AGENT_MODEL_OVERRIDES` | JSON object keyed by agent name |
| `TRUTH_ENGINE_LITELLM_API_KEY` | direct/provider or proxy auth key |
| `TRUTH_ENGINE_LITELLM_API_BASE` | optional LiteLLM proxy base URL |
| `TRUTH_ENGINE_LLM_REASONING_EFFORT` | default reasoning effort for compatible models, default `medium` |

Important default mismatch:
- `Settings` defaults to local PostgreSQL plus `minimax-m2.5`, `kimi-k2.5`, and `gpt-5.4`
- `.env.example` demonstrates a SQLite database and `openai/gpt-4.1*` routes
- whichever source loads last in your environment wins
- fixture runs are intentionally exempt from the shared DB default and use their own SQLite file unless overridden

### Live adapter settings

| Variable | Meaning |
|---|---|
| `TRUTH_ENGINE_SERPER_API_KEY` | enables `search_web` |
| `TRUTH_ENGINE_REDDIT_CLIENT_ID` | enables Reddit tools with secret |
| `TRUTH_ENGINE_REDDIT_CLIENT_SECRET` | enables Reddit tools with client ID |
| `TRUTH_ENGINE_REDDIT_USER_AGENT` | PRAW user agent |
| `TRUTH_ENGINE_PAGE_CONTENT_CHAR_LIMIT` | max fetched/extracted page text retained |

### Feature flags

The `FeatureFlags` model exists, but these flags are mostly placeholders today:
- `enable_g2_scraping`
- `enable_embedding_dedup`
- `enable_live_outreach`

## Model Routing

`config/model_routing.py` maps agents to tiers, then tiers to configured models.

Rules:
- per-agent override wins first
- otherwise tier map selects the model
- Tier 1: search/mining agents
- Tier 2: synthesis/planning agents
- Tier 3: critic/arbitration agents

## Prompt Compilation

Every live stage prompt is built from:

1. shared invariants
2. shared evidence/tool/output policies
3. the agent `role.md`
4. allowed tool manifest
5. explicit output contract description
6. normalized runtime context JSON

The compiled prompt returns a `PromptBundle`:
- `system_prompt`
- `user_prompt`
- `prompt_version`
- `prompt_hash`

`candidate_stage_run` persists `prompt_version` and `prompt_hash` for replay/audit.

Current nuance:
- live prompts are compiled once inside `LiveActivityBundle`
- stage-run persistence recompiles a smaller prompt context inside `CandidateWorkflowRunner`
- use the trace file when you need the exact prompt text sent during a live run

## Tool Runtime

Tool-backed agents do not call adapters directly. They call JSON-schema tools exposed to the LLM.

Implemented tool groups:

| Group | Tools |
|---|---|
| Arena | `create_arena_proposal`, `edit_arena_proposal`, `remove_arena_proposal`, `view_arena_proposals` |
| Signals | `add_signal`, `view_signal_summary` |
| Landscape | `add_landscape_entry`, `view_landscape` |
| Network | `search_web`, `read_page`, `reddit_search`, `reddit_fetch` |

`RepositoryToolRuntime` enforces:
- per-agent authorization
- adapter availability checks
- repository-backed persistence for write tools
- structured "unavailable" responses when a live adapter is not configured

The concrete tool-backed agents are:
- `arena_scout`
- `signal_scout`
- `landscape_scout`

Arena Scout nuance:
- `arena_scout` can now use `read_page`, not just search snippets and Reddit discovery.

## LLM Execution Loop

`LiteLLMAgentRunner` handles:
- model selection
- direct LiteLLM mode or proxy mode
- function calling
- duplicate tool-call blocking by exact signature
- required-tool enforcement for tool-backed agents
- JSON-only repair retries
- token and cost accounting
- optional trace logging

Important implementation detail:
- tool-backed live agents must call their persistence tools before final JSON output, or the runner injects a retry message.

## Live Adapters

### Search

- `SerperSearchClient`
- retries `httpx` timeouts, connection errors, and HTTP status errors
- returns structured errors instead of raising after retry exhaustion

### Web reading

- `WebFetchClient`
- prefers Scrapling fetchers when available, otherwise falls back to `httpx`
- `read_page(url)` fetches once and returns extracted readable content
- pass `include_raw_html=true` only when raw HTML is actually needed
- extraction uses `trafilatura.extract(...)` on the fetched HTML
- the fetch path retries before returning structured errors

### Reddit

- `RedditSearchClient`
- `search(...)` queries a subreddit or `all`
- `fetch(url)` returns submission text and up to 20 top-level comments

## Output Artifacts

Successful Gate B runs write:

- `out/<candidate_id>.json`
- `out/<candidate_id>.md`
- `out/<candidate_id>.trace.md`

### Trace file contents

The trace writer appends:
- stage starts and completions
- gate decisions
- budget warnings
- each LLM round
- compiled prompt text on the first round
- tool calls and tool results
- JSON repair attempts
- final outcome and generated artifact paths

### Temporal Web

When the local Temporal service is running, Temporal Web is available at
[http://localhost:8233](http://localhost:8233).

## Arena Queue Reuse

`run-live` now checks for unexplored queued arenas before creating a brand new scouting batch.

Current behavior:
- unexplored arenas are `raw_arena.status = "proposed"`
- when a live run adopts one of those queued arenas, the original row is marked `transferred`
- the new candidate seeds arena discovery from that adopted arena and skips the live Arena Scout / Arena Evaluator LLM calls for that stage
- when no queued arenas remain, `run-live` falls back to normal arena scouting

Temporal Web shows:
- workflow execution history
- activity boundaries, retries, and durations
- live workflow memo updates including current stage, budget mode, last decision, trace path, and
  dossier paths

The markdown trace file remains the high-detail record for compiled prompts, tool calls, and tool
results.

## Operational Caveats

- `run-live` starts from founder constraints only; it does not accept operator briefs or seed arenas.
- `LiveActivityBundle` currently caps itself at 6 arena proposals and 60 raw signals.
- there is still no true context-window budgeting or prompt-compaction system; prompt size is only controlled indirectly through bounded inputs and tool/result limits.
- `run-fixture` and `run-live` now require a reachable Temporal service. The local
  `docker compose up -d temporal` path is the expected dev setup.
