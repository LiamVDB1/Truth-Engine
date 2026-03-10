from __future__ import annotations

from decimal import Decimal

from truth_engine.domain.enums import BudgetMode, Stage

TARGET_CANDIDATE_BUDGET_EUR = 5.0
SAFETY_CAP_BUDGET_EUR = 7.0

STAGE_BUDGETS_EUR: dict[Stage, float] = {
    Stage.ARENA_DISCOVERY: 0.15,
    Stage.SIGNAL_MINING: 0.30,
    Stage.NORMALIZATION: 0.15,
    Stage.LANDSCAPE_SCORING_SKEPTIC: 0.60,
    Stage.WEDGE_DESIGN: 0.40,
    Stage.BUYER_CHANNEL: 0.15,
    Stage.OUTREACH_CONVERSATIONS: 1.00,
    Stage.COMMITMENT: 0.20,
    Stage.ANALYST: 0.05,
}


def candidate_budget_mode(total_spent_eur: float) -> BudgetMode:
    if total_spent_eur <= TARGET_CANDIDATE_BUDGET_EUR:
        return BudgetMode.NORMAL
    if total_spent_eur <= SAFETY_CAP_BUDGET_EUR:
        return BudgetMode.DEGRADE
    return BudgetMode.SAFETY_CAP


def remaining_stage_budget(stage: Stage, spent_eur: float) -> float:
    remaining = Decimal(str(STAGE_BUDGETS_EUR[stage])) - Decimal(str(spent_eur))
    return float(max(remaining, Decimal("0")))
