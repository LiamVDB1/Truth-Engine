# Scraping Strategy

## Core Principle

Scraped data is lead-gen, not validation. All scraped evidence gets a capped reliability score. Only direct conversations (email, call, interview) can score above 0.5.

## Source Targets

| Source | Method | Signal Type | Reliability Cap |
|--------|--------|-------------|-----------------|
| Reddit | PRAW (official API) | Pain, workaround, frequency | 0.4 |
| G2/Capterra reviews | HTTP scrape + LLM parse | Product gaps, switching triggers | 0.4 |
| Job postings | Indeed/LinkedIn scrape | Budget signals, role-based pain | 0.5 |
| GitHub Issues | GitHub API | Product/workflow pain | 0.3 |
| "Alternative to X" threads | HTTP scrape | Switching intent, unmet needs | 0.4 |
| Support communities | HTTP scrape | Workflow-specific pain | 0.4 |
| YouTube comments | YouTube Data API | Honest workflow complaints | 0.3 |
| App store reviews | HTTP scrape | Feature gaps, frustrations | 0.4 |

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
