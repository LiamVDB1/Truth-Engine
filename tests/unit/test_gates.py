from truth_engine.contracts.decisions import (
    CandidateScoreSnapshot,
    ChannelValidationSnapshot,
    SkepticSnapshot,
    WedgeSnapshot,
)
from truth_engine.domain.enums import (
    ChannelVerdict,
    GateAction,
    SkepticRecommendation,
    WedgeVerdict,
)
from truth_engine.services.gates import decide_gate_a, decide_gate_b, decide_wedge_path


def test_gate_a_kills_low_score_candidates() -> None:
    decision = decide_gate_a(
        score=CandidateScoreSnapshot(total_score=39),
        skeptic=SkepticSnapshot(recommendation=SkepticRecommendation.INVESTIGATE),
        iteration=0,
    )

    assert decision.action is GateAction.KILL


def test_gate_a_requests_targeted_evidence_when_borderline_and_investigate() -> None:
    decision = decide_gate_a(
        score=CandidateScoreSnapshot(total_score=55),
        skeptic=SkepticSnapshot(recommendation=SkepticRecommendation.INVESTIGATE),
        iteration=0,
    )

    assert decision.action is GateAction.INVESTIGATE


def test_gate_a_advances_with_caution_after_investigation_exhausted() -> None:
    decision = decide_gate_a(
        score=CandidateScoreSnapshot(total_score=61),
        skeptic=SkepticSnapshot(recommendation=SkepticRecommendation.INVESTIGATE),
        iteration=2,
    )

    assert decision.action is GateAction.ADVANCE_WITH_CAUTION


def test_gate_b_retries_on_marginal_if_retry_available() -> None:
    decision = decide_gate_b(
        validation=ChannelValidationSnapshot(
            verdict=ChannelVerdict.MARGINAL,
            total_reachable_leads=40,
            channel_count=1,
            user_role="Operations Manager",
            buyer_role="VP Operations",
            buyer_is_user=False,
            estimated_cost_per_conversation=6.0,
        ),
        retries_used=0,
    )

    assert decision.action is GateAction.RETRY


def test_gate_b_advances_only_when_reachability_thresholds_are_met() -> None:
    decision = decide_gate_b(
        validation=ChannelValidationSnapshot(
            verdict=ChannelVerdict.REACHABLE,
            total_reachable_leads=60,
            channel_count=2,
            user_role="Operations Manager",
            buyer_role="VP Operations",
            buyer_is_user=False,
            estimated_cost_per_conversation=4.5,
        ),
        retries_used=0,
    )

    assert decision.action is GateAction.ADVANCE


def test_gate_b_kills_when_marginal_retry_is_exhausted() -> None:
    decision = decide_gate_b(
        validation=ChannelValidationSnapshot(
            verdict=ChannelVerdict.MARGINAL,
            total_reachable_leads=45,
            channel_count=1,
            user_role="Operations Manager",
            buyer_role="VP Operations",
            buyer_is_user=False,
            estimated_cost_per_conversation=6.0,
        ),
        retries_used=1,
    )

    assert decision.action is GateAction.KILL


def test_gate_b_kills_when_roles_are_not_clearly_mapped() -> None:
    decision = decide_gate_b(
        validation=ChannelValidationSnapshot(
            verdict=ChannelVerdict.REACHABLE,
            total_reachable_leads=80,
            channel_count=2,
            user_role="",
            buyer_role="VP Operations",
            buyer_is_user=False,
            estimated_cost_per_conversation=3.5,
        ),
        retries_used=0,
    )

    assert decision.action is GateAction.KILL


def test_gate_b_kills_when_cost_per_first_conversation_exceeds_cap() -> None:
    decision = decide_gate_b(
        validation=ChannelValidationSnapshot(
            verdict=ChannelVerdict.REACHABLE,
            total_reachable_leads=80,
            channel_count=3,
            user_role="Operations Manager",
            buyer_role="VP Operations",
            buyer_is_user=False,
            estimated_cost_per_conversation=5.5,
        ),
        retries_used=0,
    )

    assert decision.action is GateAction.KILL


def test_wedge_loop_requests_revision_for_needs_work_when_budget_remains() -> None:
    decision = decide_wedge_path(
        wedge=WedgeSnapshot(verdict=WedgeVerdict.NEEDS_WORK),
        iteration=0,
    )

    assert decision.action is GateAction.REVISE


def test_wedge_loop_kills_weak_wedge_after_iterations_exhausted() -> None:
    decision = decide_wedge_path(
        wedge=WedgeSnapshot(verdict=WedgeVerdict.WEAK),
        iteration=2,
    )

    assert decision.action is GateAction.KILL
