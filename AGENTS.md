# AGENTS.md
Operational guide for coding agents in this repository.

## 1) Project Snapshot
- Project: **Truth Engine V1** (autonomous-first business validation engine).
- Current state: **executable v0.1 core** (docs + Python runtime + fixture-backed Gate B workflow).
- North-star metric: `time_to_paid_commitment`.
- Architecture direction: deterministic workflow spine + LLM agents as workers.
- Cost posture: `EUR 5` target per candidate (soft), degrade above target, safety cap above that.

## 2) Source-of-Truth Docs (Read First)
Read in this order before making changes:
1. `truth_engine_v1_agent_workflow.md`
2. `docs/implementation_contract.md` if it exists
3. `docs/resolved_decisions.md`
4. `docs/arena_definition.md`
5. `docs/stack_decisions.md`
6. `docs/outreach_strategy.md`
7. `docs/scraping_strategy.md`

Conflict rule:
- product workflow intent: `truth_engine_v1_agent_workflow.md` > `docs/resolved_decisions.md` > others
- implementation-specific ambiguities: `docs/implementation_contract.md` > conflicting secondary summaries and budget/tier drift

## 3) Build / Lint / Test Commands
Use this command contract when adding or updating code.

### Environment setup
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

If `pyproject.toml` exists:
```bash
pip install -e .[dev]
```

If `requirements*.txt` exists:
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Run / build
Canonical runtime entrypoint:
```bash
python -m truth_engine
```

Packaging (when enabled):
```bash
python -m build
```

### Lint / format / type-check
```bash
ruff format .
ruff check .
mypy .
```

### Tests
Run all tests:
```bash
pytest -q
```

Run one file:
```bash
pytest tests/path/test_file.py -q
```

Run one test (important):
```bash
pytest tests/path/test_file.py::test_name -q
```

Run integration tests only (if markers exist):
```bash
pytest -m integration -q
```

## 4) Code Style Guidelines (Python)

### Formatting and structure
- Follow repo config when present; otherwise use `ruff format` defaults.
- Max line length: 100.
- UTF-8, LF endings.
- Keep modules focused and small; avoid god-files.
- Prefer pure functions for transforms/scoring logic.

### Imports
- Order: standard library -> third-party -> local.
- Separate import groups with one blank line.
- No wildcard imports.
- Remove unused imports promptly.

### Types
- Type hints required for all public functions/methods.
- Prefer precise types over `Any`; use `Any` only at unavoidable boundaries.
- Use `TypedDict`, `dataclass`, or Pydantic models for structured payloads.
- Keep nullability explicit (`X | None`).

### Naming conventions
- `snake_case`: functions, variables, modules.
- `PascalCase`: classes, dataclasses, Pydantic models.
- `UPPER_SNAKE_CASE`: constants/env keys.
- Use domain names from docs (`Arena`, `ProblemUnit`, `EvidenceItem`, etc.).

### Error handling
- No bare `except:`.
- Catch specific exceptions and preserve context.
- Fail fast on schema/contract violations.
- Return structured error states where deterministic branching needs them.

### Logging and observability
- Use structured logs.
- Include at minimum: `candidate_id`, `stage`, `agent`, `event`, `cost_eur` (if available).
- Never log secrets or unnecessary personal data.
- Log gate decisions and kill reasons explicitly.

### Workflow/Temporal rules
- Keep workflow/orchestration code deterministic.
- Put side effects (HTTP, LLM calls, DB writes, scraping) in activities/tasks.
- Enforce stage budgets and circuit breakers in deterministic control flow.
- Keep retry policy explicit and bounded.

### Database rules
- Use PostgreSQL as source of truth.
- Prefer explicit schemas/migrations over ad-hoc table creation.
- Store evidence with provenance (`source_url`, timestamps, reliability metadata).
- Preserve decision audit trail (append-only where practical).

### Testing expectations
- Add tests for non-trivial logic: scoring, gate checks, budgets, dedup.
- Unit-test pure logic first.
- Integration-test workflow edges: retries, kill paths, and budget exhaustion.
- Bugfixes: add failing test first, then implement fix.

### Cost and model routing discipline
- Keep model routing in config, not hard-coded in call sites.
- Use the cheapest viable model tier per task.
- Track tokens and EUR cost per call.
- Respect candidate-level budget policy from docs.

## 5) Product and Compliance Constraints
- "No evidence, no claim."
- "No commitment, no build."
- Exclusions are about what we build (software-first), not who we sell to.
- Respect suppression/opt-out handling in outreach flows.
- Do not add outreach automation that bypasses documented compliance constraints.

## 6) Cursor/Copilot Rules Check
No repository rules were found in:
- `.cursor/rules/`
- `.cursorrules`
- `.github/copilot-instructions.md`

If these files are later added, they become mandatory; summarize their requirements here.
