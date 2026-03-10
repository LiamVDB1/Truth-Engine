import pytest

from truth_engine.config.settings import Settings
from truth_engine.prompts.builder import build_prompt


def test_build_prompt_uses_configured_prompt_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUTH_ENGINE_PROMPT_VERSION", "v2026-03-10")

    bundle = build_prompt(
        agent_id="scorer",
        context={
            "candidate_id": "cand_123",
            "stage": "landscape_scoring_skeptic",
            "output_contract": "ScoringResult",
        },
        settings=Settings(),
    )

    assert bundle.prompt_version == "v2026-03-10"
    assert bundle.prompt_hash
    assert "no evidence, no claim" in bundle.system_prompt.lower()
    assert "top-level fields" in bundle.system_prompt.lower()
    assert "`problem_unit_id`" in bundle.system_prompt
    assert "this agent has no direct tool access" in bundle.system_prompt.lower()
    assert '"candidate_id": "cand_123"' in bundle.user_prompt


def test_build_prompt_hash_is_stable_for_same_inputs() -> None:
    settings = Settings(prompt_version="v-stable")

    first = build_prompt(
        agent_id="scorer",
        context={
            "candidate_id": "cand_123",
            "stage": "landscape_scoring_skeptic",
            "output_contract": "ScoringResult",
        },
        settings=settings,
    )
    second = build_prompt(
        agent_id="scorer",
        context={
            "candidate_id": "cand_123",
            "stage": "landscape_scoring_skeptic",
            "output_contract": "ScoringResult",
        },
        settings=settings,
    )

    assert first.prompt_hash == second.prompt_hash


def test_build_prompt_includes_tool_manifest_for_tool_backed_agent() -> None:
    bundle = build_prompt(
        agent_id="signal_scout",
        context={
            "candidate_id": "cand_123",
            "stage": "signal_mining",
            "output_contract": "SignalMiningResult",
        },
        settings=Settings(prompt_version="v-tools"),
    )

    assert "allowed tools" in bundle.system_prompt.lower()
    assert "`add_signal`" in bundle.system_prompt
    assert "`fetch_page`" in bundle.system_prompt
    assert "`reddit_fetch`" in bundle.system_prompt


def test_build_prompt_serializes_nested_context_deterministically() -> None:
    context = {
        "output_contract": "SignalMiningResult",
        "candidate_id": "cand_123",
        "stage": "signal_mining",
        "nested": {"beta": 2, "alpha": 1},
    }

    first = build_prompt(agent_id="signal_scout", context=context, settings=Settings())
    second = build_prompt(agent_id="signal_scout", context=context, settings=Settings())

    assert first.user_prompt == second.user_prompt
    assert '"alpha": 1' in first.user_prompt
    assert '"beta": 2' in first.user_prompt
