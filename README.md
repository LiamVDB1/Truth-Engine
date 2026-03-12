# Truth Engine

Truth Engine V1 is an evidence-backed business validation engine.

The current repo now supports both:

- a Temporal-orchestrated fixture replay for testing the full Gate B workflow
- a Temporal-orchestrated live provider-backed runtime for stages `0-5` through buyer/channel
  validation

The v0.1 boundary is unchanged:

- stages `0-5`
- product boundary at `Gate B`
- output as an operator-ready Markdown/JSON dossier
- no autonomous outbound or conversation automation

## What Works

- Temporal orchestration for fixture and live runs through Gate B
- Temporal worker command plus inline-worker execution for one-shot runs
- Temporal Web visibility for stage/activity history and workflow state memo
- deterministic single-candidate workflow through Gate B
- bounded Gate A targeted-evidence loop
- bounded wedge refinement loop
- Gate B retry / kill logic
- repository-backed storage for arenas, signals, problem units, landscape entries, wedges,
  channel plans, decisions, and cost logs
- live tool runtime for:
  - `search_web` via Serper
  - `read_page`
  - `reddit_search` and `reddit_fetch` via PRAW
- LiteLLM-backed agent execution with:
  - structured JSON outputs
  - tool-calling loops for tool-based agents
  - per-stage token/cost accounting
- prompt hash and prompt version capture on stage runs
- Alembic migration scaffold for the initial schema
- CLI commands for schema init, fixture execution, live execution, dossier export, and prompt preview

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
docker compose up -d postgres temporal
```

Initialize a local database:

```bash
python -m truth_engine init-db --database-url sqlite:///./truth_engine.db
```

## Environment

Copy [.env.example](/Users/liamvdb/Workspace/Active/Work/truth_engine/.env.example) to `.env` and fill in the provider keys you want to use.

Minimum live setup:

- one LiteLLM-compatible model route
- `TRUTH_ENGINE_SERPER_API_KEY`

Optional but recommended:

- `TRUTH_ENGINE_REDDIT_CLIENT_ID`
- `TRUTH_ENGINE_REDDIT_CLIENT_SECRET`

Model routing defaults to:

- `TRUTH_ENGINE_TIER1_MODEL=openai/gpt-4.1-mini`
- `TRUTH_ENGINE_TIER2_MODEL=openai/gpt-4.1`
- `TRUTH_ENGINE_TIER3_MODEL=openai/gpt-4.1`

You can override individual agents with JSON:

```bash
export TRUTH_ENGINE_AGENT_MODEL_OVERRIDES='{"skeptic":"openai/gpt-4.1","wedge_critic":"openai/gpt-4.1"}'
```

If you prefer a LiteLLM proxy/gateway, set:

- `TRUTH_ENGINE_LITELLM_API_BASE`
- `TRUTH_ENGINE_LITELLM_API_KEY`

Useful runtime overrides:

- `TRUTH_ENGINE_AGENT_MAX_TOOL_ROUNDS=100`
- `TRUTH_ENGINE_TEMPORAL_HOST=localhost:7233`
- `TRUTH_ENGINE_TEMPORAL_NAMESPACE=default`
- `TRUTH_ENGINE_TEMPORAL_TASK_QUEUE=truth-engine`

Temporal Web is available at [http://localhost:8233](http://localhost:8233) when the local
Temporal service is running.

## Run Live

`run-live` now submits a Temporal workflow that starts Arena Discovery from system context,
matching the workflow doc:

- `founder_constraints`
- `past_learnings`

It does not require an operator brief or seed arenas.

If you want to override the default founder constraints, use [examples/live_request.json](/Users/liamvdb/Workspace/Active/Work/truth_engine/examples/live_request.json). Otherwise you can run with no request file at all.

Run the live stages `0-5` flow:

```bash
python -m truth_engine run-live --prompt-version live-v1
```

Optional founder-constraint override:

```bash
python -m truth_engine run-live \
  --request-file examples/live_request.json \
  --prompt-version live-v1
```

The default command path starts an inline Temporal worker and waits for completion. If you want a
dedicated worker process instead:

```bash
python -m truth_engine run-worker
python -m truth_engine run-live --no-inline-worker
```

Runtime artifacts are written to `./out` by default:

- `./out/<candidate_id>.trace.md`
- `./out/<candidate_id>.md`
- `./out/<candidate_id>.json`

The trace file is appended while the run is active. For live runs it includes stage transitions,
compiled prompts, assistant responses, tool calls, tool results, JSON repair attempts, and final
artifacts. Temporal Web shows the orchestration history and workflow memo; the markdown trace file
remains the detailed prompt/tool transcript.

## Run Fixture

Run the full Gate B workflow on the primary happy-path fixture:

```bash
python -m truth_engine run-fixture \
  --fixture tests/fixtures/workflows/investigate_revise_reachable.json \
  --prompt-version live-v1
```

## Prompt Inspection

Preview a compiled prompt before a run:

```bash
python -m truth_engine preview-prompt \
  --agent signal_scout \
  --context-file tests/fixtures/prompts/signal_scout_preview.json \
  --prompt-version review
```

## Dossier Export

Export a previously stored dossier:

```bash
python -m truth_engine export-dossier \
  --candidate-id cand_logistics_ops \
  --database-url sqlite:///./truth_engine.db \
  --output-dir ./out
```

## Fixture Scenarios

- `tests/fixtures/workflows/investigate_revise_reachable.json`
  - Gate A investigate pass
  - wedge revision
  - Gate B retry
  - final advance with dossier
- `tests/fixtures/workflows/gate_b_retry_kill.json`
  - Gate B retry followed by kill
- `tests/fixtures/workflows/budget_degrade_gate_b_kill.json`
  - over-target degrade mode disables the optional Gate B retry
- `tests/fixtures/workflows/safety_cap_gate_b_kill.json`
  - safety-cap kill path

## Verification

```bash
ruff format .
ruff check .
mypy .
pytest -q
```

## Source Of Truth

Implementation and planning intent are constrained by:

1. `truth_engine_v1_agent_workflow.md`
2. `planning/implementation_contract.md`
3. `planning/resolved_decisions.md`
4. `planning/stack_decisions.md`

Code-oriented documentation lives in [`docs/README.md`](/Users/liamvdb/Workspace/Active/Work/truth_engine/docs/README.md).
