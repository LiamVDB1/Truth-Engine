# Truth Engine Documentation

Truth Engine is a Python implementation of an evidence-backed business-validation engine.

The repository currently ships a v0.1 runtime for stages `0-5`:
- Arena discovery
- Signal mining
- Normalization
- Landscape research + scoring + skeptic review
- Wedge design
- Buyer/channel validation

The runtime stops at **Gate B** and produces an operator-ready dossier in Markdown and JSON.

## Read This First

The most important distinction in this repository is:

| Topic | Current code | Older planning docs |
|---|---|---|
| Orchestration | Synchronous Python runner | Temporal-first design |
| Database | SQLAlchemy repository, SQLite-friendly, PostgreSQL-intended | PostgreSQL-first |
| Output boundary | Gate B dossier | Full multi-stage system through commitment |
| Live adapters | Serper, public web fetch/extract, Reddit via PRAW | Broader future scraping stack |

If you need product intent or future architecture, see [`planning/README.md`](/Users/liamvdb/Workspace/Active/Work/truth_engine/planning/README.md). If you need to understand the code that actually runs today, start here.

## Documentation Map

- [`architecture.md`](/Users/liamvdb/Workspace/Active/Work/truth_engine/docs/architecture.md): package layout, execution layers, key boundaries
- [`workflow.md`](/Users/liamvdb/Workspace/Active/Work/truth_engine/docs/workflow.md): stage-by-stage runtime behavior, loops, gates, and budget controls
- [`data-model.md`](/Users/liamvdb/Workspace/Active/Work/truth_engine/docs/data-model.md): Pydantic contracts, database tables, persistence rules
- [`agents-tools-prompts.md`](/Users/liamvdb/Workspace/Active/Work/truth_engine/docs/agents-tools-prompts.md): agent roster, prompt compiler, tool registry, LLM execution loop
- [`runtime.md`](/Users/liamvdb/Workspace/Active/Work/truth_engine/docs/runtime.md): CLI, configuration, live adapters, tracing, and operational caveats
- [`testing.md`](/Users/liamvdb/Workspace/Active/Work/truth_engine/docs/testing.md): test suite structure, fixtures, coverage focus, and gaps

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m truth_engine init-db --database-url sqlite:///./truth_engine.db
python -m truth_engine run-fixture --fixture tests/fixtures/workflows/investigate_revise_reachable.json
```

Run live mode:

```bash
python -m truth_engine run-live --prompt-version live-v1
```

## Repository Shape

| Path | Role |
|---|---|
| `src/truth_engine/cli` | CLI entrypoints |
| `src/truth_engine/workflows` | Deterministic candidate runner |
| `src/truth_engine/activities` | Fixture-backed and live-backed stage execution |
| `src/truth_engine/adapters` | DB, LLM, search, scraping, and Reddit integrations |
| `src/truth_engine/contracts` | Shared typed schemas for stages, decisions, fixtures, and live requests |
| `src/truth_engine/services` | Pure logic: gates, budgets, dedup, learnings, logging, trace writer |
| `src/truth_engine/tools` | Tool registry, bundles, schemas, and runtime enforcement |
| `src/truth_engine/prompts` | Prompt assembly and per-agent role files |
| `src/truth_engine/reporting` | Dossier rendering and artifact writing |
| `tests` | Unit and integration coverage |
| `migrations` | Alembic environment and initial schema |

## Current Scope

Implemented:
- Gate A investigation loop
- Wedge revision loop
- Gate B retry loop
- Degrade-mode suppression of optional retries/loops
- Safety-cap kill when candidate cost exceeds `EUR 7`
- Prompt hash/version persistence
- Per-stage run logging and cost logging
- Markdown trace output during runs

Not implemented yet:
- Temporal worker/runtime
- Stages `6-7` outbound, conversation, and commitment execution
- General runtime learnings injection into prompts
- Embedding-based arena dedup

Important implementation caveats:
- `Settings` defaults target local PostgreSQL plus `minimax-m2.5` / `kimi-k2.5` / `gpt-5.4`, while `.env.example` demonstrates a SQLite + `openai/gpt-4.1*` setup.
- The workflow persists stage-run `prompt_version` and `prompt_hash`, but the exact live prompt body is most faithfully captured in the trace file.
