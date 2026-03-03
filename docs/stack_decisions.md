# Stack Decisions

## Orchestration: Temporal.io (Python SDK)

Deterministic workflow engine with durable execution. Survives crashes, supports retries/timeouts, keeps state across failures, and provides a debug UI.

Temporal owns the state machine. LLM agents run as activities (workers). This keeps control flow deterministic and makes model behavior auditable.

Alternatives considered:
- Celery: weaker fit for long-lived, stateful, multi-stage workflows.
- LangChain/CrewAI orchestration: too agent-opinionated for strict gate/policy control.

## Database: PostgreSQL

Single source of truth for the Truth Warehouse:
- typed tables for `arena`, `candidate`, `problem_unit`, `evidence_item`, `commitment_artifact`, `learning_entry`
- JSONB for flexible payloads
- full-text and vector search for archive retrieval and similarity checks

## LLM Interface: LiteLLM

Unified provider interface (OpenAI, Anthropic, Google, open-weight/local endpoints). Cost logged per call. Routing stays in config, not orchestration logic.

## Structured Output: Instructor + Pydantic

All agent outputs are typed models, never free-form blobs. Schema failures auto-retry. This enforces "structured evidence, not vibes" at the contract layer.

## Search & Scraping: Serper + Scrapling + trafilatura + PRAW

Search and page extraction are split into separate concerns, each handled by the best tool for the job.

| Concern | Tool | Why |
|---------|------|-----|
| Search / URL discovery | Serper.dev | Google SERP API. Best coverage, cheapest ($0.001/query). Structured metadata (PAA, related searches) feeds Arena Scout. |
| Page fetching | Scrapling (`StealthyFetcher`) | Cloudflare Turnstile bypass for G2/Capterra. TLS fingerprint impersonation. Headless browser with anti-bot. Free, self-hosted (`pip install`). |
| Content extraction | trafilatura | Strips boilerplate, extracts main content from raw HTML. No per-site config. Free. |
| Reddit | PRAW | Official API. Structured data (upvotes, scores, subreddit metadata) that scraping can't replicate. |

Alternatives considered:
- Tavily: bundled search+extraction, but proprietary index with coverage gaps and 10x more expensive.
- Jina Reader: simple API but no Cloudflare bypass — fails on priority sources (G2, Capterra).
- Exa: semantic search, but our queries are keyword-based. 5x cost for no benefit.
- Crawl4AI: good extraction but generic stealth vs Scrapling's targeted Turnstile bypass.

Future swap option: if trafilatura quality isn't sufficient, the extraction interface (`extract(url) → str`) can swap to Jina ReaderLM V2 API per-source without changing agent code.

See `docs/scraping_strategy.md` for the full pipeline, source targets, and cost breakdown.

## Model Routing: Config, Not Code

Default tier intent:
- Tier 1: very cheap, high-volume extraction/search
- Tier 2: mid-cost synthesis/scoring/outreach drafting
- Tier 3: premium arbitration/skeptic/negotiation support

```python
AGENT_MODEL_MAP = {
    # Stage 0-2 / high-volume extraction
    "arena_scout": "minimax-M2.5",
    "signal_scout": "minimax-M2.5",
    "normalizer": "minimax-M2.5",

    # Synthesis and planning
    "arena_evaluator": "glm-5",
    "scorer": "glm-5",
    "wedge_designer": "glm-5",
    "buyer_channel_validator": "glm-5",
    "outreach_operator": "glm-5",
    "analyst": "glm-5",

    # High-stakes reasoning and closing
    "skeptic": "gpt-5.3-codex",
    "wedge_critic": "gpt-5.3-codex",
    "conversation_agent": "gpt-5.2",
    "commitment_closer": "gpt-5.2",
}
```

Notes:
- Model names are runtime-configurable aliases; swap per provider availability/cost.
- If a model is unavailable, route to fallback in same tier.
- Do not assume consumer subscription OAuth gives API-grade production access unless provider explicitly supports it.

## Cost Control Policy

Budget checks happen before every LLM/tool call and are written to `cost_log`.

`EUR 5` is a **target per candidate**, not an immediate hard-kill line.

Control behavior:
- **Target zone**: `<= EUR 5` (normal operation)
- **Over-target zone**: `EUR 5-7` (degrade mode: no optional loops, cheaper model fallback, tighter caps)
- **Safety cap**: `> EUR 7` (pause candidate and require explicit policy decision or auto-kill by config)

Suggested stage targets (V1):
- Stage 0-2: `EUR 1.5`
- Stage 3-4: `EUR 2.0`
- Stage 5-7 + retrospective: `EUR 1.5`

Mandatory `cost_log` columns:
- `candidate_id`, `stage`, `agent`, `model`, `input_tokens`, `output_tokens`, `tool_calls`, `cost_eur`, `timestamp`
