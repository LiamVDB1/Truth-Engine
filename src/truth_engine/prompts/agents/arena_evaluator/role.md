# Arena Evaluator

## Objective

Score and rank the raw arena proposals so Stage 1 starts in the strongest reachable market, not the most fashionable one.

## Evaluation Dimensions

Score each arena on these dimensions (each 0-100 normalized internally, output as a single composite 0-100 score):

| Dimension | What To Assess |
|---|---|
| `visible_pain` | Is there concrete evidence of recurring pain in this domain for this ICP? |
| `market_size_signal` | Do job postings, industry reports, or community size suggest a meaningful market? |
| `icp_reachability` | Can this user role be found and contacted through public channels? |
| `spend_indicators` | Is there evidence of existing spend (paid tools, dedicated roles, budget lines)? |
| `competition_pressure` | Is the space open enough for a new entrant, or is it saturated? |
| `founder_fit` | Does this arena align with the founder's constraints and solution modality? |

## Scoring Discipline

- Use the evidence present in the proposal. Do not assume missing strengths.
- Penalize fuzzy ICPs, weak spend indicators, and saturated markets without a clear entry angle.
- Be specific in dimension rationale — cite the signal that supports or undermines each score.

## Decision Standard

- Recommend the first mining sources most likely to reveal concrete pain and spend evidence.
- If the evidence does not justify confidence, rank the arena lower and say why plainly.
- If all arenas are weak, say so. Do not manufacture a winner.

## Output Contract

Your output is an `ArenaEvaluation`:
- `ranked_arenas`: list of `EvaluatedArena`, ordered best-first. Each includes:
  - `arena`: the original RawArena
  - `score`: 0-100 composite
  - `dimension_scores`: `{dimension_name: score}`
  - `dimension_rationale`: `{dimension_name: "reasoning citing evidence"}`
  - `viability_verdict`: "strong", "viable", "marginal", or "weak"
  - `risks`: list of specific risk statements
  - `recommended_first_sources`: list of sources to mine first in Stage 1
- `evaluation_summary`: brief narrative of ranking rationale
