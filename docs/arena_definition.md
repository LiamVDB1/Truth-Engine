# Arena Definition

## What Is an Arena?

An arena is a bounded search space for finding business opportunities. It defines **who** has pain, **where** they work, **how** you can reach them, and **what kind of solution** you'd build.

An arena is NOT a business idea. It's the territory the system explores to find and validate ideas.

## Arena Object (Required Fields)

| Field | Description | Example |
|-------|-------------|---------|
| `domain` | Industry or problem space | "logistics operations", "video editing workflow" |
| `icp_user_role` | Who experiences the pain daily | "warehouse operations manager" |
| `icp_buyer_role` | Who signs the check (can be same as user) | "VP of Operations" |
| `geo` | Geographic focus | "EU + US", "DACH region" |
| `channel_surface` | Where you can reach the ICP | "LinkedIn, industry forums, G2 reviews" |
| `solution_modality` | What kind of thing you'd build | "SaaS", "API", "browser extension", "hardware+software" |
| `market_size_signal` | Rough indicator that there's a real market | "500+ job postings for this role", "3 funded competitors" |
| `expected_sales_cycle` | How fast can you go from first contact to paid pilot | "1-4 weeks" (software) vs "3-6 months" (hardware) |

## Arena Constraints (V1 Founder Filter)

These are hard filters based on your preferences. Arenas that violate these are filtered before scoring.

- **Solution modality** (what YOU build): software-first (SaaS, API, tooling, automation, integration). Hardware/robotics is a V2 track.
- **Excluded business models** (what YOU wouldn't operate): physical operations, manual service delivery, brick-and-mortar ownership.
- **Target market**: **unrestricted**. The customer can be in any industry — restaurants, construction, healthcare, whatever. As long as what you're delivering is software.
- **Reachable online**: the ICP must exist on channels the system can access (LinkedIn, email, Reddit, forums, communities).

## Arena Scope: How Broad?

Start broad. The target market is unrestricted — the system narrows by scoring.

- Arena examples at the RIGHT granularity:
  - ✅ "Logistics SMEs — ops managers struggling with supplier coordination"
  - ✅ "Freelance video editors — workflow automation between editing tools"
  - ✅ "DevOps teams at mid-market SaaS — infrastructure cost optimization"

- Too broad:
  - ❌ "Technology companies"
  - ❌ "Businesses that use software"

- Too narrow:
  - ❌ "Warehouse managers in Berlin using SAP who also need Python scripts"

**Rule of thumb**: an arena should be narrow enough that you can write a specific cold email to the ICP, but broad enough that there are hundreds (ideally thousands) of potential customers.

## Arena vs Candidate

- **Arena** = the territory (e.g., "logistics SMEs, ops managers, EU")
- **Candidate** = a specific problem + solution hypothesis within that arena (e.g., "automating supplier reorder communication for logistics ops managers via email parsing")

Multiple candidates can come from the same arena. If all candidates in an arena get killed, the arena itself gets marked as exhausted.
