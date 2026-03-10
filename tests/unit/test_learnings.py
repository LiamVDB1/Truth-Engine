"""Tests for the learnings extraction system."""

from __future__ import annotations

from truth_engine.contracts.models import RawArena
from truth_engine.contracts.stages import (
    CandidateDossier,
    ChannelPlan,
    ChannelValidation,
    DecisionEvent,
    EvaluatedArena,
    ScoredCandidate,
    SkepticReport,
    WedgeHypothesis,
)
from truth_engine.domain.enums import ChannelVerdict, GateAction, SkepticRecommendation, Stage
from truth_engine.services.learnings import extract_kill_learnings, extract_pass_learnings


def _make_arena() -> EvaluatedArena:
    return EvaluatedArena(
        arena=RawArena(
            domain="logistics-ops",
            icp_user_role="Head of Ops",
            icp_buyer_role="VP Supply Chain",
            geo="US",
            channel_surface=["linkedin"],
            solution_modality="SaaS",
            market_signals=["hiring"],
            signal_sources=["reddit"],
            market_size_signal="Growing",
            expected_sales_cycle="3 months",
            rationale="Logistics pain.",
        ),
        score=72,
        dimension_scores={"viability": 8, "pain": 7},
        dimension_rationale={"viability": "Good", "pain": "Ok"},
        viability_verdict="viable",
        risks=["competition"],
        recommended_first_sources=["reddit"],
    )


def _make_scoring(total: int = 35) -> ScoredCandidate:
    return ScoredCandidate(
        problem_unit_id="pu_1",
        total_score=total,
        confidence=0.7,
        confidence_rationale="Moderate evidence.",
        dimension_scores={"proof_of_spend": 2, "pain_severity": 3, "willingness_to_pay": 6},
        dimension_evidence={
            "proof_of_spend": "None found",
            "pain_severity": "Some",
            "willingness_to_pay": "Budget exists",
        },
        dimension_rationale={
            "proof_of_spend": "No data",
            "pain_severity": "Weak",
            "willingness_to_pay": "Good",
        },
        weakest_dimensions=["proof_of_spend"],
    )


def _make_skeptic() -> SkepticReport:
    return SkepticReport(
        candidate_id="cand_test",
        evidence_integrity="weak",
        risk_flags=["No proof of spend found", "Single source evidence"],
        missing_evidence=["Budget confirmation", "User interviews"],
        disconfirming_signals=["Competitor dominance in segment"],
        landscape_assessment="Crowded with incumbents",
        landscape_detail="Three established TMS players control 80% of market.",
        inflated_dimensions=["pain_severity"],
        primary_weakness="proof_of_spend",
        overall_risk="high",
        recommendation=SkepticRecommendation.KILL,
        recommendation_rationale="Insufficient evidence for spend willingness.",
        improvement_suggestions=["Find budget data"],
    )


def test_kill_learnings_produces_entries() -> None:
    arena = _make_arena()
    scoring = _make_scoring(total=35)
    skeptic = _make_skeptic()

    entries = extract_kill_learnings(
        "cand_test",
        "Score is below the auto-kill threshold.",
        arena=arena,
        scoring=scoring,
        skeptic=skeptic,
    )

    assert 2 <= len(entries) <= 4
    assert all(e.candidate_id == "cand_test" for e in entries)
    assert any("logistics-ops" in e.insight for e in entries)
    assert any("kill" in e.tags for e in entries)


def test_kill_learnings_without_scoring_still_works() -> None:
    entries = extract_kill_learnings(
        "cand_test",
        "Too weak.",
        arena=_make_arena(),
    )
    assert len(entries) >= 1
    assert entries[0].candidate_id == "cand_test"


def test_pass_learnings_produces_entries() -> None:
    dossier = CandidateDossier(
        candidate_id="cand_pass",
        arena=_make_arena(),
        problem_unit=_make_problem_unit(),
        top_evidence=[],
        scoring=_make_scoring(total=78),
        skeptic=_make_skeptic(),
        selected_wedge=_make_wedge(),
        channel_validation=_make_channel_validation(),
        gate_history=[
            DecisionEvent(
                candidate_id="cand_pass",
                stage=Stage.LANDSCAPE_SCORING_SKEPTIC,
                action=GateAction.ADVANCE,
                reason="Score clears threshold.",
            )
        ],
        caution_flags=[],
    )

    entries = extract_pass_learnings("cand_pass", dossier)

    assert 2 <= len(entries) <= 4
    assert all(e.candidate_id == "cand_pass" for e in entries)
    assert any("logistics-ops" in e.insight for e in entries)
    assert any("pass" in e.tags for e in entries)


def _make_problem_unit():
    from truth_engine.contracts.models import ProblemUnit

    return ProblemUnit(
        id="pu_1",
        job_to_be_done="Reduce shipment exceptions.",
        trigger_event="Exception alert",
        frequency="daily",
        severity=8,
        urgency="high",
        cost_of_failure="$5k per exception",
        current_workaround="Manual tracking spreadsheets",
        proof_of_spend="Budget exists for TMS tools",
        switching_friction=4,
        buyer_authority="VP Supply Chain",
        evidence_ids=["ev_1"],
        signal_count=3,
        source_diversity=2,
        confidence=0.7,
    )


def _make_wedge() -> WedgeHypothesis:
    return WedgeHypothesis(
        id="wedge_1",
        wedge_promise="We help logistics teams reduce exceptions by 40%.",
        solution_type="SaaS platform",
        key_capability="Automated exception detection",
        target_outcome="Fewer lost shipments, less manual work",
        differentiation="ML on shipment data",
        rough_pricing="$500/mo per warehouse",
        delivery_complexity="Medium — needs API integration",
        mvp_scope="Exception alerts + dashboard",
        first_10_onboarding="White-glove setup with data import",
        switching_ease="Low friction — runs alongside existing TMS",
        data_advantage="Training on shipment patterns",
        unfair_advantage="ML on shipment data",
        target_job="Reduce exceptions",
        value_prop="Less manual work, fewer lost shipments",
        anti_wedge_risks=["Requires data integration"],
    )


def _make_channel_validation() -> ChannelValidation:
    return ChannelValidation(
        candidate_id="cand_pass",
        user_role="Head of Ops",
        buyer_role="VP Supply Chain",
        buyer_is_user=False,
        blocker_roles=["IT"],
        procurement_notes="Needs IT approval.",
        channels=[
            ChannelPlan(
                channel="LinkedIn",
                message_angle="Exception reduction",
                volume_estimate=50,
                how_to_reach="InMail",
                lead_source="LinkedIn Sales Navigator",
                expected_response_rate=0.08,
                first_20_plan="Start with 20 Heads of Ops",
            ),
            ChannelPlan(
                channel="Email",
                message_angle="Operational efficiency",
                volume_estimate=30,
                how_to_reach="Cold email",
                lead_source="ZoomInfo",
                expected_response_rate=0.05,
                first_20_plan="20 VPs from target companies",
            ),
        ],
        total_reachable_leads=80,
        estimated_cost_per_conversation=3.50,
        verdict=ChannelVerdict.REACHABLE,
        verdict_rationale="Multiple channels with good volume.",
    )
