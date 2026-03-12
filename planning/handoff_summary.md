# Conversation Handoff Summary

## Goal

Build the **Truth Engine V1** — an autonomous multi-agent system that discovers, validates, and commits to business opportunities. The system should find real pain signals, validate them with evidence, design solution wedges, run autonomous outreach, and only proceed to building when paid commitments are secured. The founder is a single operator, tech-oriented, targeting max €5/candidate in LLM costs.

The immediate goal is to **finalize the in-depth agent workflow document** (`truth_engine_v1_agent_workflow.md`). The founder still has remarks and refinements before it's ready. Once the workflow is finalized, the next step is generating a PRD and moving to implementation.

## Instructions

- **Read `AGENTS.md` first** — it's the project brief and knowledge transfer doc. It has the file map, project status, locked decisions, and working instructions.
- **Read `truth_engine_v1_agent_workflow.md` second** — this is THE core document. It has all 8 stages, 13 agents, typed I/O schemas, feedback loops, gate logic, and cross-cutting systems.
- **The workflow is still being iterated.** Do NOT skip to PRD or implementation without explicit founder approval. Ask the founder what remarks they still have.
- **Think deeply before responding.** The founder explicitly wants thorough internal reasoning on every response. Weigh pros and cons, consider alternatives, and present only the best conclusions.
- **Keep docs short and targeted.** No filler. The founder dislikes unnecessary verbosity and clutter.
- **Exclusions framing:** Constraints are about what YOU BUILD (software), not who you sell to. Target market is unrestricted — restaurants, healthcare, construction, etc. are all valid markets if the solution is software.
- **Tool-based agents:** The Arena Scout and Signal Scout use CRUD tools (create/edit/remove/view) instead of traditional input→output. This gives real-time dedup feedback during search and keeps the context window clean. Other agents might get this pattern later but currently only the two Scouts have it.
- **Budget:** Max €5/candidate total. Cheaper models preferred (Tier 1: Qwen-class, Tier 2: GLM-class, Tier 3: GPT-5.x class). Current stage budgets sum to ~€3 with €2 buffer.

## Discoveries

- **B2B cold email is legal in the EU** under GDPR "legitimate interest" (Recital 47). Companies like 11x.ai and Instantly operate this way. The key requirements are: business emails only, opt-out in every message, sender identity clear, legal basis documented.
- **Tool-based agent pattern** (giving agents CRUD tools to manage their work product incrementally) was identified as a powerful approach. It provides real-time feedback (e.g., similarity checking against killed arenas on `create`), keeps the agent's context clean, and allows for more natural search workflows. Currently applied to both Scouts only.
- **A Wedge Design stage was missing** from the original workflow. Without it, outreach would happen without a concrete solution to pitch. Stage 4 (Wedge Designer + Wedge Critic with refinement loop) was added to fill this gap.
- **Scoring feedback loop:** When a candidate scores in the 40-69 range, a targeted evidence pass runs (max 2 iterations) where the Signal Scout re-runs focused on the Skeptic's identified weakness, then the candidate is rescored. This prevents false kills on strong ideas with initial evidence gaps.
- **The constitution doc (`truth_engine_v1_constitution.md`) has some thresholds that are now superseded** by the workflow doc. The workflow doc takes precedence on any conflicts.

## Accomplished

**Completed:**
- Full project foundation: philosophy, lessons, constitution, all locked
- Resolved all 8 open design questions (arena selection, scoring, human-in-the-loop, outreach identity, gates, kills, budget)
- Precise Arena definition with required fields and scope guidelines
- Stack decisions locked (Temporal.io, PostgreSQL, LiteLLM, Instructor)
- Outreach strategy with GDPR compliance, channel playbooks, interview tiers
- Scraping strategy with source priorities and reliability caps
- In-depth agent workflow document with 8 stages, 13 agents, typed I/O schemas, feedback loops, gate logic, cross-cutting systems (learnings, dedup, budget, error handling)
- Tool-based pattern applied to Arena Scout and Signal Scout
- Exclusions reframed correctly (constrain solution modality, not target market)
- `AGENTS.md` knowledge transfer file created

**Still in progress:**
- Founder has additional remarks/refinements on the workflow (unspecified — ask them)

**Not yet started:**
- PRD generation
- Database schema design
- Project scaffolding and code implementation

## Relevant files / directories

```
/Users/liamvdb/PycharmProjects/idea_factory/
├── AGENTS.md                              # Project brief for new agents — READ THIS FIRST
├── truth_engine_v1_agent_workflow.md       # Core workflow doc — READ THIS SECOND (🔄 in progress)
├── truth_engine_v1_constitution.md         # Operational policy (reference, workflow takes precedence)
├── truth_engine_foundation_lessons.md      # Source-backed lessons from YC/PG/a16z/Sequoia (reference)
├── docs/
│   ├── resolved_decisions.md              # All 8 open questions locked
│   ├── arena_definition.md                # What an Arena is (recently updated)
│   ├── stack_decisions.md                 # Tech stack decisions
│   ├── outreach_strategy.md               # GDPR compliance + channel playbooks
│   ├── scraping_strategy.md               # Signal sources + reliability caps
│   └── handoff_summary.md                 # This file
```
