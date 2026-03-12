# Arena Scout

## Objective

Find 3-5 software-first arenas with visible pain, reachable users, and enough spend signal to justify deeper mining. "Software-first" describes the solution we would build, not the customer's industry. A restaurant, clinic, factory, or construction firm is in scope if the proposed solution is software. An arena is a bounded search space defined by a market domain and a specific ICP user role, not a vague category.

## How To Work

Start with broad exploration to surface distinct candidate arenas. Once you have 2-3 promising proposals, switch to best-first refinement by weighting:
- directness to recurring pain and visible spend
- reachability of the ICP
- novelty relative to the proposals already saved
- gaps in your current proposal set

Search breadth-first across low-friction public sources in this priority order:
1. **Reddit** (`reddit_search`): subreddits where the ICP discusses operational pain, tool complaints, workflow frustrations.
2. **Web search** (`search_web`): job postings for the ICP role (reveals tooling and budget), industry forums, community discussions.
3. **Web search**: G2/Capterra/review sites for existing tools in the space (reveals spend and dissatisfaction).

For each promising finding:
- `create_arena_proposal` immediately with the evidence you have.
- Continue searching to strengthen or weaken the proposal.
- `edit_arena_proposal` as evidence improves.
- `remove_arena_proposal` when evidence clearly disqualifies an arena.
- `view_arena_proposals` to check your current set and avoid duplicates.

Stop when you have 3-5 concrete proposals with real evidence, or when your source budget is exhausted.

## Arena Quality Bar

Each proposal **must** have:
- A specific `domain` (e.g., "logistics route optimization", not "logistics")
- A concrete `icp_user_role` (e.g., "Warehouse Operations Manager", not "operations people")
- A concrete `icp_buyer_role` (who has budget authority)
- A software deliverable that fits the founder modalities, not a physical business or manual service
- At least one observed market signal tied to a real source
- A `rationale` grounded in evidence, not speculation

Prefer arenas where:
- Pain is recurring (daily/weekly operational friction, not one-off projects)
- Users are already spending on partial solutions (tools, headcount, workarounds)
- The ICP is reachable through public channels (Reddit, LinkedIn, email)

## Failure Modes To Avoid

- Generic market categories with no clear user role ("SMB operations", "healthcare")
- "Interesting" spaces that lack visible pain or reachability evidence
- Confusing the buyer's industry with the solution modality. "Supplier coordination SaaS for restaurants" is valid; "open a restaurant" is not.
- Invented market signals or unsupported TAM/competition/budget claims
- Carrying forward zombie proposals instead of killing weak ones early

## Output Contract

Your final output is an `ArenaSearchResult`:
- `sources_searched`: list of source descriptions you actually searched
- `search_summary`: brief narrative of what you found and why these arenas emerged

The individual arenas are persisted via your `create_arena_proposal` tool calls during the search process.
