# Testing

The test suite is built around the deterministic Gate B workflow and the low-level pure logic that supports it.

## Verification Commands

```bash
ruff format .
ruff check .
mypy .
pytest -q
```

## Test Layout

| Area | Focus |
|---|---|
| `tests/unit` | pure logic, contracts, prompt compilation, tool bundles/runtime, adapter resilience, run tracing |
| `tests/integration` | full workflow execution, repository persistence, CLI behavior, budget mode transitions |
| `tests/fixtures` | deterministic workflow scenarios and prompt preview contexts |

## Unit Coverage Highlights

### Pure logic

- `test_gates.py`: Gate A, Gate B, and wedge-path decisions
- `test_budgets.py`: budget thresholds and remaining-stage math
- `test_dedup.py`: arena fingerprint normalization
- `test_learnings.py`: retrospective learning extraction

### Contracts and prompt system

- `test_contract_models.py`: model validation helpers like arena fingerprints and auto-derived signal hashes
- `test_prompt_builder.py`: prompt version/hash stability, tool manifest rendering, deterministic context serialization

### Tooling and adapters

- `test_tool_registry.py`: registry completeness and per-agent bundles
- `test_live_tool_runtime.py`: live search adapter wiring and closed-fail behavior when adapters are missing
- `test_adapter_resilience.py`: Serper structured error handling
- `test_litellm_runner.py`: tool-calling loop, JSON parsing/repair, and proxy mode behavior
- `test_run_trace.py`: Markdown trace generation and truncation/fence handling

### CLI/config

- `test_cli_defaults.py`: parser defaults derived from settings
- `test_live_request.py`: default founder-constraint based live request

## Integration Coverage

### `test_candidate_workflow.py`

Validates:
- fixture happy path through Gate B
- targeted investigation loop
- wedge revision loop
- Gate B retry loop
- degrade-mode retry suppression
- safety-cap kill
- prompt preview command output

### `test_temporal_workflow.py`

Validates:
- Temporal orchestration replay for the Gate B happy path
- artifact persistence through the Temporal workflow path
- worker/activity registration against Temporal's embedded test server when the environment allows it

### `test_storage_and_tools.py`

Validates:
- URL dedup in the repository tool runtime
- tool authorization failures
- unavailable live adapter behavior
- killed-arena fingerprint blocking

## Fixture Scenarios

| Fixture | What it exercises |
|---|---|
| `investigate_revise_reachable.json` | Gate A investigate -> wedge revise -> Gate B retry -> final pass |
| `gate_b_retry_kill.json` | Gate B retry then kill |
| `budget_degrade_gate_b_kill.json` | degrade mode disables optional Gate B retry |
| `safety_cap_gate_b_kill.json` | kill after crossing the `EUR 7` safety cap |

## What Is Not Covered Yet

Current gaps are mostly about future-state functionality or real external integrations:

- no real end-to-end live network tests against Serper, Reddit, or provider-backed LLMs
- no direct unit coverage for `WebFetchClient` or `RedditSearchClient`
- no stages `6-7` tests because outbound/conversation/commitment execution is out of scope
- no prompt-eval harness or golden-output regression suite yet
- limited focused coverage for migration shape, dossier formatting edge cases, and live CLI execution
- `test_temporal_workflow.py` skips automatically when the embedded Temporal test server cannot start
  in the current environment (for example, restricted sandboxes)

## Testing Philosophy in This Repo

The code is optimized for:
- typed contracts
- deterministic workflow replay
- pure, unit-testable gate and budget logic
- integration tests that assert persisted state, not just return values
