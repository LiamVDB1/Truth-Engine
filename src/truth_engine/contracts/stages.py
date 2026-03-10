from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from truth_engine.domain.enums import ChannelVerdict, GateAction, Stage, WedgeVerdict

from .models import ProblemUnit, RawArena, RawSignal


class ActivityMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    cost_eur: float = Field(default=0.0, ge=0.0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)


class ArenaSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    sources_searched: list[str]
    search_summary: str


class EvaluatedArena(BaseModel):
    model_config = ConfigDict(frozen=True)

    arena: RawArena
    score: int = Field(ge=0, le=100)
    dimension_scores: dict[str, int]
    dimension_rationale: dict[str, str]
    viability_verdict: str
    risks: list[str]
    recommended_first_sources: list[str]


class ArenaEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    ranked_arenas: list[EvaluatedArena]
    evaluation_summary: str


class SignalMiningResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    sources_searched: int = Field(ge=0)
    search_summary: str


class NormalizationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    problem_units: list[ProblemUnit]
    unclustered_signals: int = Field(ge=0)
    clustering_summary: str


class LandscapeEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str | None = None
    name: str
    type: str
    status: str
    source_url: str
    what_they_do: str
    relevance: str
    strengths: list[str] | None = None
    weaknesses: list[str] | None = None
    pricing: str | None = None
    failure_reason: str | None = None
    years_active: str | None = None
    funding_raised: str | None = None
    lesson_for_us: str


class LandscapeReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    sources_searched: int = Field(ge=0)
    search_summary: str
    active_competitor_count: int = Field(ge=0)
    dead_attempt_count: int = Field(ge=0)
    open_source_count: int = Field(ge=0)
    market_density: str


class ScoredCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    problem_unit_id: str
    total_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_rationale: str
    dimension_scores: dict[str, int]
    dimension_evidence: dict[str, str]
    dimension_rationale: dict[str, str]
    weakest_dimensions: list[str]


class ScoringResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scored_candidates: list[ScoredCandidate]
    top_candidate: ScoredCandidate
    scoring_summary: str


class SkepticReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    evidence_integrity: str
    risk_flags: list[str]
    missing_evidence: list[str]
    disconfirming_signals: list[str]
    landscape_assessment: str
    landscape_detail: str
    inflated_dimensions: list[str]
    primary_weakness: str
    overall_risk: str
    recommendation: str
    recommendation_rationale: str


class WedgeHypothesis(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str | None = None
    wedge_promise: str
    solution_type: str
    key_capability: str
    target_outcome: str
    differentiation: str
    rough_pricing: str
    delivery_complexity: str
    mvp_scope: str
    first_10_onboarding: str
    switching_ease: str
    data_advantage: str


class WedgeProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    wedges: list[WedgeHypothesis]
    design_rationale: str


class WedgeEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    wedge_index: int = Field(ge=0)
    promise_alignment: str
    feasibility: str
    differentiation_strength: str
    pricing_viability: str
    switching_ease: str
    competitive_risk: str
    verdict: WedgeVerdict
    key_issues: list[str]


class WedgeCritique(BaseModel):
    model_config = ConfigDict(frozen=True)

    evaluations: list[WedgeEvaluation]
    best_wedge_index: int = Field(ge=0)
    revision_suggestions: list[str]
    overall_summary: str


class ChannelPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel: str
    how_to_reach: str
    lead_source: str
    expected_response_rate: float = Field(ge=0.0, le=1.0)
    volume_estimate: int = Field(ge=0)
    message_angle: str
    first_20_plan: str


class ChannelValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    user_role: str
    buyer_role: str
    buyer_is_user: bool
    blocker_roles: list[str]
    procurement_notes: str
    channels: list[ChannelPlan]
    total_reachable_leads: int = Field(ge=0)
    estimated_cost_per_conversation: float = Field(ge=0.0)
    verdict: ChannelVerdict
    verdict_rationale: str


class DecisionEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    stage: Stage
    action: GateAction
    reason: str
    iteration: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LearningEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str | None = None
    candidate_id: str
    insight: str
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CandidateRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    status: str
    current_stage: Stage | None = None
    caution_flag: bool = False
    selected_arena_id: str | None = None
    selected_problem_unit_id: str | None = None
    selected_wedge_id: str | None = None
    total_cost_eur: float = Field(default=0.0, ge=0.0)
    dossier_payload: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class CandidateDossier(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    arena: EvaluatedArena
    problem_unit: ProblemUnit
    top_evidence: list[RawSignal]
    scoring: ScoredCandidate
    skeptic: SkepticReport
    selected_wedge: WedgeHypothesis
    channel_validation: ChannelValidation
    gate_history: list[DecisionEvent]
    caution_flags: list[str]
    cost_breakdown: dict[str, float] = Field(default_factory=dict)
    total_cost_eur: float = Field(default=0.0, ge=0.0)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkflowOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    status: str
    final_decision: DecisionEvent
    dossier: CandidateDossier | None = None


def wedge_verdict_for_critique(critique: WedgeCritique) -> WedgeVerdict:
    return critique.evaluations[critique.best_wedge_index].verdict
