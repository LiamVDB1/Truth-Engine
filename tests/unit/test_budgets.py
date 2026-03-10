import pytest

from truth_engine.domain.enums import BudgetMode, Stage
from truth_engine.services.budgets import (
    STAGE_BUDGETS_EUR,
    candidate_budget_mode,
    remaining_stage_budget,
)


def test_stage_budget_table_matches_contract_values() -> None:
    assert STAGE_BUDGETS_EUR[Stage.ARENA_DISCOVERY] == 0.15
    assert STAGE_BUDGETS_EUR[Stage.NORMALIZATION] == 0.15
    assert STAGE_BUDGETS_EUR[Stage.LANDSCAPE_SCORING_SKEPTIC] == 0.60


def test_budget_mode_stays_normal_at_or_under_target() -> None:
    assert candidate_budget_mode(5.0) is BudgetMode.NORMAL


def test_budget_mode_enters_degrade_between_target_and_safety_cap() -> None:
    assert candidate_budget_mode(5.01) is BudgetMode.DEGRADE
    assert candidate_budget_mode(7.0) is BudgetMode.DEGRADE


def test_budget_mode_enters_safety_cap_above_limit() -> None:
    assert candidate_budget_mode(7.01) is BudgetMode.SAFETY_CAP


def test_remaining_stage_budget_never_goes_negative() -> None:
    assert remaining_stage_budget(Stage.WEDGE_DESIGN, spent_eur=0.05) == 0.35
    assert remaining_stage_budget(Stage.WEDGE_DESIGN, spent_eur=0.50) == 0.0


def test_remaining_stage_budget_preserves_subcent_precision() -> None:
    remaining = remaining_stage_budget(Stage.WEDGE_DESIGN, spent_eur=0.399)

    assert remaining == pytest.approx(0.001)
