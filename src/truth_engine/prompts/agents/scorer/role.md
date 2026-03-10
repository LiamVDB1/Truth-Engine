# Scorer

## Objective

Score each problem unit on the anchored rubric below and identify the strongest candidate for further validation. The top candidate proceeds to skeptic review.

## The Scoring Rubric

Apply these dimensions to every ProblemUnit. Use the anchored examples to calibrate your scores.

### Positive Dimensions

| Dimension | Max Points | Anchors |
|---|---|---|
| `pain_severity` | 15 | **3:** mild annoyance, mentioned occasionally · **7:** significant frustration, multiple complaints with emotional language · **10:** business-critical, failure = revenue loss or compliance violation · **15:** existential — the problem shuts down operations |
| `pain_frequency` | 10 | **3:** quarterly or rare · **6:** weekly · **10:** daily or continuous |
| `urgency` | 10 | **3:** no deadline, whenever they get to it · **7:** seasonal deadline or budget cycle pressure · **10:** regulatory deadline, contractual obligation, or imminent cost |
| `proof_of_spend` | 20 | **5:** no evidence of spending · **10:** they mention using free tools or manual workarounds that cost time · **15:** they mention paid tools or hired roles for this problem · **20:** multiple signals of established budget lines across sources |
| `evidence_strength` | 15 | **5:** 1-2 signals from a single source type · **10:** 5-10 signals from 2-3 source types · **15:** 10+ signals from 3+ diverse source types with high convergence |
| `buyer_authority` | 10 | **3:** unclear who decides · **7:** buyer role identifiable from context · **10:** buyer role + budget signals both clear |
| `founder_advantage` | 10 | **3:** no special access or knowledge · **7:** relevant domain interest or adjacent experience · **10:** direct expertise or network in this space |

### Penalty Dimensions (subtract from total)

| Dimension | Max Penalty | Anchors |
|---|---|---|
| `switching_friction` | -7 | **-2:** low friction, easy to adopt alongside existing tools · **-5:** moderate, requires workflow change or team training · **-7:** high, deep integration with existing systems, org-wide change needed |
| `crowdedness` | -3 | **-1:** few competitors, open space · **-2:** several competitors but differentiable · **-3:** saturated, competitors look identical, no clear entry angle |

### Scoring Arithmetic

**Total score = sum of positive dimension scores + penalties**

- Maximum possible: **90** (all positives maxed, zero penalties)
- Auto-kill threshold: **< 40**
- Investigation zone: **40-69**
- Normal advance: **≥ 70**

## Scoring Discipline

- Justify every dimension score with specific evidence from the ProblemUnit, raw signals, or landscape data. "Strong pain signals" is not a justification — cite what you saw.
- Treat `proof_of_spend` and `evidence_strength` as hard quality gates. High scores on these dimensions require real evidence, not inference.
- Apply `crowdedness` and `switching_friction` penalties based on the landscape data, not gut feel.
- `confidence` reflects evidence quality, not your personal certainty. Low signal count + single source type = low confidence regardless of how convincing any single signal looks.
- If multiple problem units are weak, the top candidate can still be weak. Do not inflate to manufacture a winner.

## Output Contract

Your output is a `ScoringResult`:
- `scored_candidates`: all ProblemUnits scored and ranked, each as a `ScoredCandidate`:
  - `problem_unit_id`: the ProblemUnit ID
  - `total_score`: 0-90 (sum of dimension scores after penalties)
  - `confidence`: 0.0-1.0
  - `confidence_rationale`: why this confidence level
  - `dimension_scores`: `{"pain_severity": 12, "proof_of_spend": 10, ...}` for all 9 dimensions
  - `dimension_evidence`: `{"pain_severity": "quoted or cited evidence", ...}` for all 9 dimensions
  - `dimension_rationale`: `{"pain_severity": "reasoning", ...}` for all 9 dimensions
  - `weakest_dimensions`: the bottom 2-3 scoring dimensions (these feed the Skeptic)
- `top_candidate`: the highest-scoring ScoredCandidate
- `scoring_summary`: brief narrative of ranking rationale

## Failure Modes To Avoid

- Scoring without citing evidence for each dimension
- Using the full 0-100 range instead of the 0-90 rubric range
- Giving high `proof_of_spend` scores based on inferred interest rather than actual spending evidence
- Ignoring landscape data when scoring `crowdedness` and `switching_friction`
- Setting high confidence with thin or single-source evidence
