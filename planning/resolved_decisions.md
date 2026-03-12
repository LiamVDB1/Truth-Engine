# Resolved Decisions

Answers to the 8 open questions, based on founder input. These are locked unless explicitly reopened.

---

## 1. Arena Selection: Agent-Led

The system proposes arenas. No human input required at Stage 0.

**How it works:**
- An **Arena Scout** agent searches for promising arenas based on founder constraints (software-first, tech-oriented, reachable online).
- It looks for: markets with visible pain signals, proof of spend, reachable ICP roles, and growing demand.
- Sources for arena discovery: job posting trends, funding announcements, G2 category growth, Reddit community activity, emerging compliance/regulation changes.
- Outputs a ranked shortlist of 3-5 arenas with rationale and evidence links.
- System picks the top arena and starts a candidate within it. Others are queued.
- Only Gate C (build decision) requires human approval.

**How many arenas before going deep:**
Not pre-defined. System runs arenas until one produces a candidate that passes Gate C. Killed arenas get archived, system moves to next.

---

## 2. First Target Arena: System-Selected

No pre-picked arena. The Arena Scout selects the first one based on signal strength and reachability. Founder provided domain constraints:

- Technology / software solutions
- Open to both pure software and hardware+software, but **V1 tracks software-first** (faster `time_to_paid_commitment`)
- No restaurants, retail, manual services
- Must be online-reachable ICP

---

## 3. Agent Workflow: Needs Full Rewrite

Acknowledged. See `truth_engine_v1_agent_workflow.md` for the revised source-of-truth version.

Key gaps to close:
- Strict input/output contracts per agent
- Normalizer schema formally defined
- Skeptic role: runs parallel with Scorer, can flag missing evidence and request targeted retry, but cannot directly veto — the gate check decides
- Conversation → Closer boundary: qualification criteria trigger handoff (budget confirmed + problem confirmed + interest signal ≥ 0.7)

---

## 4. Scoring: Anchored Rubric, Staged Auto-Kill

- **Keep 0-100 scale**
- **Anchored rubric**: each scoring dimension gets concrete anchor examples (what a 2, 5, 8 looks like)
- **Staged thresholds (V1):**
  - `< 40`: auto-kill
  - `40-69`: continue, but Skeptic must flag weaknesses and system must seek disconfirming evidence
  - `≥ 70`: advance normally
- **Weight calibration**: manual tuning after first 10 candidates. Track scores vs outcomes.
- **No pairwise comparison in V1** — keep it simple.

---

## 5. Human-in-the-Loop: Late Only

- **No human** in Stage 0-4 by default
- **Human enters at:**
  - Commitment intent detected (escalated from Conversation Agent for negotiation/pricing)
  - Gate C approval (build/no-build decision)
- **System continues** with other arenas/candidates while waiting for human input
- **Interface**: web dashboard (design TBD)
- **SLA for human response**: undefined, but system doesn't block — it works on other candidates while waiting

---

## 6. Outreach Identity

**Decision: company brand + founder signature.**

Recommended setup:
- Create a simple brand/company name (even a placeholder, can rename later)
- Emails sent as: `Liam @ [BrandName]` from a dedicated domain
- LinkedIn: personal account (Liam's), AI-assisted messaging
- **Disclosure policy (V1)**:
  - Fully autonomous conversations: no proactive disclosure, but if asked directly → disclose honestly
  - Marketing content / posts: no disclosure needed (AI-assisted content creation is industry standard)
  - Voice calls (if ever): must disclose
- This matches how 11x.ai and similar AI SDR tools operate in the B2B space

**Action needed from founder**: pick a brand name and register a sending domain.

---

## 7. Gate Thresholds: Reframed

**Implementation note:** the workflow document is canonical for gate sequencing. For implementation:

- Gate A = Stage 3 research viability gate
- Gate B = Stage 5 reachability gate
- Gate C = commitment threshold gate

The reachability thresholds below therefore define the practical Gate B standard for v0.1.

Revised reachability standard (implemented as Gate B in v0.1):
- ≥ 50 identifiable leads in the target ICP (exist, not contacted)
- ≥ 2 distinct channels where ICP is reachable
- Clear user/buyer distinction
- Estimated cost per first qualified conversation ≤ €5

These are "does the market exist" thresholds, not "can you email 50 people tomorrow."

Gate A and Gate C behavior stay as defined in `truth_engine_v1_agent_workflow.md`.

---

## 8. Kill Handling

- **Auto-start next candidate** after kill
- **Full kill transparency** in web dashboard (dedicated tab: killed candidates with scores, evidence, kill reason)
- **Killed candidates stored** in DB with full audit trail
- **Revival**: manual only — founder can flag a killed candidate for re-evaluation (V2)
- **Learning from kills**: V2 feature

---

## Budget: €5/Candidate Target

**Implementation note:** the canonical per-stage budget table now lives in `implementation_contract.md` and the workflow budget-control section. The grouped buckets below are only a high-level allocation envelope.

**High-level budget split:**

| Stages | Budget |
|--------|--------|
| 0-2 (Arena scout + mining + scoring) | €1.50 |
| 3-4 (Channel validation + outreach) | €2.00 |
| 5-6 (Conversations + commitment tracking) | €1.50 |
| **Total max per candidate** | **€5.00** |

Per-stage circuit breakers. Hard stop at cap. Cheaper model routing (Tier 1: Qwen-type, Tier 2: GLM-type, Tier 3: GPT-5.x class — specific models configured at runtime).
