# Agents, Tools, and Prompts

This repository does not implement a generic agent framework. It implements one narrow agent runtime for the stages that exist today.

## Implemented Agent Roster

| Agent | Stage | Live implementation | Tool access | Output contract | Role file |
|---|---|---|---|---|---|
| `arena_scout` | Arena discovery | yes | arena CRUD + `search_web` + optional Reddit search | `ArenaSearchResult` | `prompts/agents/arena_scout/role.md` |
| `arena_evaluator` | Arena discovery | yes | none | `ArenaEvaluation` | `prompts/agents/arena_evaluator/role.md` |
| `signal_scout` | Signal mining | yes | signal CRUD + search/fetch/extract + optional Reddit | `SignalMiningResult` | `prompts/agents/signal_scout/role.md` |
| `normalizer` | Normalization | yes | none | `NormalizationResult` | `prompts/agents/normalizer/role.md` |
| `landscape_scout` | Landscape research | yes | landscape CRUD + search/fetch/extract | `LandscapeReport` | `prompts/agents/landscape_scout/role.md` |
| `scorer` | Scoring | yes | none | `ScoringResult` | `prompts/agents/scorer/role.md` |
| `skeptic` | Skeptic review | yes | none | `SkepticReport` | `prompts/agents/skeptic/role.md` |
| `wedge_designer` | Wedge design | yes | none | `WedgeProposal` | `prompts/agents/wedge_designer/role.md` |
| `wedge_critic` | Wedge critique | yes | none | `WedgeCritique` | `prompts/agents/wedge_critic/role.md` |
| `buyer_channel_validator` | Buyer/channel validation | yes | none | `ChannelValidation` | `prompts/agents/buyer_channel_validator/role.md` |

Not implemented in the live runtime:
- `outreach_operator`
- `conversation_agent`
- `commitment_closer`
- `analyst`

## Prompt Compiler

`prompts/builder.py` compiles a `PromptBundle` with:

1. shared policy markdown:
   - `shared/invariants.md`
   - `shared/evidence_policy.md`
   - `shared/tool_policy.md`
   - `shared/output_policy.md`
2. one agent-specific `role.md`
3. an auto-generated tool manifest
4. an auto-generated output-contract section
5. a normalized runtime-context JSON block

The resulting bundle contains:
- `system_prompt`
- `user_prompt`
- `prompt_version`
- `prompt_hash`

Prompt details that matter in practice:
- context normalization is deterministic: keys are sorted, enums become values, dates become ISO strings
- `prompt_hash` is the first 16 hex chars of `sha256(system_prompt + user_prompt)`
- role text is rewritten when Reddit tools are unavailable so prompts do not mention tools the runtime cannot expose
- the compiler supports budget-pressure and past-learning sections, but current live execution only passes `past_learnings` to `arena_scout`, and does not currently pass `budget_mode`

## Tool System

Only three agents are tool-backed today:
- `arena_scout`
- `signal_scout`
- `landscape_scout`

### Registry

`tools/registry.py` defines 13 tools:

| Group | Tools |
|---|---|
| Arena persistence | `create_arena_proposal`, `edit_arena_proposal`, `remove_arena_proposal`, `view_arena_proposals` |
| Signal persistence | `add_signal`, `view_signal_summary` |
| Landscape persistence | `add_landscape_entry`, `view_landscape` |
| Network | `search_web`, `fetch_page`, `extract_content`, `reddit_search`, `reddit_fetch` |

Each tool has:
- a name and description
- a side-effect level: `read_only`, `write`, or `network`
- a coarse cost class: `low`, `medium`, `high`
- an adapter key used as a conceptual execution target

### Bundles and Schemas

`tools/bundles.py` defines which tool names each agent may call.

Filtering happens in two places:
- settings-level filtering removes tools that cannot be supported by current credentials
- runtime filtering removes tools whose concrete adapters were not injected

`tools/schemas.py` turns tool specs into OpenAI-style function-call schemas. Persistence tools derive their argument shapes from the Pydantic contracts.

### Runtime Enforcement

`RepositoryToolRuntime` is the execution boundary.

It enforces:
- per-agent authorization
- adapter presence checks
- repository writes for arena, signal, and landscape tools
- structured `"unavailable"` responses for missing live adapters

If an agent calls a tool it is not allowed to use, the runtime raises `PermissionError`.

## LiteLLM Agent Runner

`adapters/llm/litellm_runner.py` owns the live LLM loop.

### What it does

- selects a model via `resolve_agent_model(...)`
- calls LiteLLM directly, or switches to OpenAI-compatible proxy mode when `TRUTH_ENGINE_LITELLM_API_BASE` is set and the model alias has no provider prefix
- executes function calls round-by-round
- blocks exact duplicate tool calls by signature
- enforces required persistence tools before accepting final JSON
- retries invalid JSON responses with a repair prompt
- accumulates `ActivityMetrics`
- optionally mirrors everything into a Markdown trace

### Loop semantics

Important limits:
- tool rounds are capped by `TRUTH_ENGINE_AGENT_MAX_TOOL_ROUNDS`
- JSON repair attempts are capped by `TRUTH_ENGINE_LLM_MAX_RETRIES`
- after tool-round exhaustion the runner forces `tool_choice="none"` and asks for final JSON

Required-tool enforcement is important for the tool-backed agents:
- `arena_scout` must call `create_arena_proposal`
- `signal_scout` must call `add_signal`
- `landscape_scout` must call `add_landscape_entry`

If the model returns valid JSON before calling the required tool, the runner sends a corrective message and continues instead of accepting the output.

## Tracing and Logging

Two observability paths exist:

- terminal logging from `services/logging.py`
- append-only Markdown traces from `services/run_trace.py`

The trace is the highest-fidelity execution record because it can include:
- the first compiled prompt body
- every tool call and tool result
- JSON repair attempts
- final artifact paths

Current nuance:
- `CandidateWorkflowRunner` persists `prompt_version` and `prompt_hash` on every `candidate_stage_run`
- in live mode those values are rebuilt from a reduced context, so use the trace file when you need the exact prompt that was sent to the model
