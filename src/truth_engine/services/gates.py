from __future__ import annotations

from truth_engine.contracts.decisions import (
    CandidateScoreSnapshot,
    ChannelValidationSnapshot,
    GateDecision,
    SkepticSnapshot,
    WedgeSnapshot,
)
from truth_engine.domain.enums import (
    ChannelVerdict,
    GateAction,
    SkepticRecommendation,
    WedgeVerdict,
)

MAX_GATE_A_INVESTIGATIONS = 2
MAX_WEDGE_REVISIONS = 2
MAX_GATE_B_RETRIES = 1


def decide_gate_a(
    score: CandidateScoreSnapshot,
    skeptic: SkepticSnapshot,
    iteration: int,
    max_iterations: int = MAX_GATE_A_INVESTIGATIONS,
) -> GateDecision:
    if score.total_score >= 70:
        return GateDecision(
            action=GateAction.ADVANCE, reason="Score clears the normal advance threshold."
        )

    if score.total_score < 40:
        return GateDecision(
            action=GateAction.KILL, reason="Score is below the auto-kill threshold."
        )

    if skeptic.recommendation is SkepticRecommendation.KILL and score.total_score < 60:
        return GateDecision(
            action=GateAction.KILL, reason="Borderline score plus skeptic kill recommendation."
        )

    if skeptic.recommendation is SkepticRecommendation.INVESTIGATE and iteration < max_iterations:
        return GateDecision(
            action=GateAction.INVESTIGATE,
            reason="Borderline candidate should run a targeted evidence pass.",
        )

    if skeptic.recommendation is SkepticRecommendation.ADVANCE and score.total_score >= 50:
        return GateDecision(
            action=GateAction.ADVANCE_WITH_CAUTION,
            reason="Borderline score but skeptic recommends advancing.",
        )

    if iteration >= max_iterations:
        if score.total_score >= 60:
            return GateDecision(
                action=GateAction.ADVANCE_WITH_CAUTION,
                reason="Investigation budget exhausted but score remains viable.",
            )
        return GateDecision(
            action=GateAction.KILL,
            reason="Investigation budget exhausted and score remains too weak.",
        )

    return GateDecision(
        action=GateAction.INVESTIGATE,
        reason="Borderline candidate defaults to targeted investigation while budget remains.",
    )


def decide_gate_b(
    validation: ChannelValidationSnapshot,
    retries_used: int,
    max_retries: int = MAX_GATE_B_RETRIES,
) -> GateDecision:
    has_role_mapping = bool(validation.user_role.strip()) and bool(validation.buyer_role.strip())

    if (
        validation.verdict is ChannelVerdict.REACHABLE
        and validation.total_reachable_leads >= 50
        and validation.channel_count >= 2
        and has_role_mapping
        and validation.estimated_cost_per_conversation <= 5.0
    ):
        return GateDecision(
            action=GateAction.ADVANCE,
            reason="Reachability thresholds are satisfied.",
        )

    if validation.verdict is ChannelVerdict.MARGINAL and retries_used < max_retries:
        return GateDecision(
            action=GateAction.RETRY,
            reason="Marginal reachability gets one retry.",
        )

    return GateDecision(
        action=GateAction.KILL,
        reason="Reachability thresholds were not met.",
    )


def decide_wedge_path(
    wedge: WedgeSnapshot,
    iteration: int,
    max_iterations: int = MAX_WEDGE_REVISIONS,
) -> GateDecision:
    if wedge.verdict in {WedgeVerdict.STRONG, WedgeVerdict.VIABLE}:
        return GateDecision(action=GateAction.ADVANCE, reason="A viable wedge was found.")

    if wedge.verdict is WedgeVerdict.NEEDS_WORK and iteration < max_iterations:
        return GateDecision(
            action=GateAction.REVISE,
            reason="The wedge should be revised using critique feedback.",
        )

    if wedge.verdict is WedgeVerdict.WEAK and iteration < max_iterations:
        return GateDecision(
            action=GateAction.RETRY,
            reason="The wedge should be redesigned from scratch.",
        )

    return GateDecision(
        action=GateAction.KILL,
        reason="No viable wedge was found within the iteration budget.",
    )
