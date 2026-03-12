# Scraping Strategy

## Core Principle

Scraped data is lead-gen, not validation. All scraped evidence gets a capped reliability score. Only direct conversations (email, call, interview) can score above 0.5.

## Tooling Stack

| Concern | Tool | Role |
|---------|------|------|
| Search / URL discovery | **Serper.dev** | Google SERP API. Finds URLs across all source types. Structured metadata (PAA, related searches) feeds Arena Scout. ~$0.001/query. |
| Page fetching | **Scrapling** (`StealthyFetcher`) | Headless browser with Cloudflare Turnstile bypass, TLS fingerprint impersonation, anti-bot evasion. Handles JS-rendered pages (G2, Indeed). Free, self-hosted. |
| Content extraction | **trafilatura** | Strips boilerplate (nav, ads, sidebars, footers) from raw HTML. Returns clean main content text. No per-site config needed. Free. |
| Reddit | **PRAW** | Official Reddit API. Returns structured data: upvotes, comment scores, subreddit metadata, author flair. Richer signal quality than scraping. |
| Signal parsing | **Instructor + LLM** | Extracts structured `RawSignal` from clean text. Already in stack. |

### Extraction Pipeline

```
Arena Scout:  Serper → SERP snippets + metadata (no page extraction needed)
Signal Scout: Serper (domain-filtered) → URLs → Scrapling fetches → trafilatura extracts main content → Instructor parses RawSignal
Reddit:       PRAW → structured data → Instructor parses RawSignal
```

### Why These Tools

**Serper over Tavily/Exa/Brave:** Google's index has no coverage gaps. SERP metadata (People Also Ask, related searches) is free market intelligence. 10x cheaper than alternatives.

**Scrapling over Jina Reader/Crawl4AI:** Cloudflare Turnstile bypass is critical — G2 and Capterra (top priority sources) use it. Jina Reader can't get through. Crawl4AI has generic stealth; Scrapling has targeted evasion. `pip install scrapling && scrapling install` — no Docker needed.

**trafilatura over markdownify/manual parsing:** Automatically identifies and extracts main content from any page without per-site selectors. Strips boilerplate that would waste LLM tokens. No config.

**Future swap option:** If trafilatura quality isn't sufficient on certain sources, the extraction function can swap to Jina ReaderLM V2 API (`r.jina.ai` with `x-engine: readerlm-v2`) for those sources. Interface stays `extract(url) → str`.

### Cost Per Candidate

| Component | Est. Usage | Cost |
|-----------|-----------|------|
| Serper | ~90 queries | ~€0.09 |
| Scrapling | ~80 pages | €0.00 |
| trafilatura | ~80 pages | €0.00 |
| PRAW | ~50 requests | €0.00 |
| **Total** | | **~€0.09** |

## Source Targets

| Source | Method | Signal Type | Reliability Cap |
|--------|--------|-------------|-----------------|
| Reddit | PRAW (official API) | Pain, workaround, frequency | 0.40 |
| G2/Capterra reviews | Scrapling + trafilatura | Product gaps, switching triggers | 0.40 |
| Job postings | Scrapling + trafilatura | Budget signals, role-based pain | 0.50 |
| GitHub Issues | GitHub API | Product/workflow pain | 0.30 |
| "Alternative to X" threads | Scrapling + trafilatura | Switching intent, unmet needs | 0.40 |
| Support communities | Scrapling + trafilatura | Workflow-specific pain | 0.40 |
| YouTube comments | YouTube Data API | Honest workflow complaints | 0.30 |
| App store reviews | Scrapling + trafilatura | Feature gaps, frustrations | 0.40 |

## What the Scout Extracts Per Signal

- Source type + URL
- Verbatim quote
- Persona (who said it, what role)
- Inferred pain point
- Inferred frequency
- Tags (for clustering)

## V1 Priority Sources

Start with the 3 highest-signal, easiest-to-access sources per arena. Don't try to scrape everything at once.

Likely first picks: **Reddit + G2/Capterra + Job postings**. These cover pain signals, switching behavior, and budget evidence respectively.
