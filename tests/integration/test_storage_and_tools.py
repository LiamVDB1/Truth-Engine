from __future__ import annotations

from pathlib import Path

import pytest

from truth_engine.contracts.models import RawSignal
from truth_engine.domain.enums import AgentName


def test_repository_tool_runtime_rejects_unauthorized_tools_and_dedups_urls(
    tmp_path: Path,
) -> None:
    from truth_engine.adapters.db.migrate import upgrade_database
    from truth_engine.adapters.db.repositories import TruthEngineRepository
    from truth_engine.tools.runtime import RepositoryToolRuntime

    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)
    repository.create_schema()
    repository.create_candidate(candidate_id="cand_tools", status="running")
    runtime = RepositoryToolRuntime(repository=repository)

    first = runtime.invoke(
        AgentName.SIGNAL_SCOUT,
        "add_signal",
        {
            "candidate_id": "cand_tools",
            "signal": RawSignal(
                id="sig_tools_1",
                source_type="reddit",
                source_url="https://reddit.com/r/test/comments/abc/?utm_source=foo",
                verbatim_quote="This hurts every week.",
                persona="Ops manager",
                inferred_pain="Manual coordination is painful",
                inferred_frequency="weekly",
                proof_of_spend=False,
                switching_signal=True,
                tags=["coordination"],
                reliability_score=0.4,
            ),
        },
    )
    duplicate = runtime.invoke(
        AgentName.SIGNAL_SCOUT,
        "add_signal",
        {
            "candidate_id": "cand_tools",
            "signal": RawSignal(
                id="sig_tools_2",
                source_type="reddit",
                source_url="https://REDDIT.com/r/test/comments/abc#frag",
                verbatim_quote="This hurts every week.",
                persona="Ops manager",
                inferred_pain="Manual coordination is painful",
                inferred_frequency="weekly",
                proof_of_spend=False,
                switching_signal=True,
                tags=["coordination"],
                reliability_score=0.4,
            ),
        },
    )

    assert first["status"] == "created"
    assert duplicate["status"] == "duplicate"
    assert repository.count_raw_signals("cand_tools") == 1

    unavailable = runtime.invoke(
        AgentName.SIGNAL_SCOUT,
        "read_page",
        {"candidate_id": "cand_tools", "url": "https://example.com"},
    )

    assert unavailable["status"] == "unavailable"

    with pytest.raises(PermissionError):
        runtime.invoke(
            AgentName.SIGNAL_SCOUT,
            "remove_arena_proposal",
            {"candidate_id": "cand_tools", "arena_id": "arena_1"},
        )


def test_killed_arena_fingerprint_blocks_reproposal(tmp_path: Path) -> None:
    from truth_engine.adapters.db.migrate import upgrade_database
    from truth_engine.adapters.db.repositories import TruthEngineRepository
    from truth_engine.contracts.models import RawArena

    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)
    repository.create_schema()
    repository.create_candidate(candidate_id="cand_dead", status="running")

    created = repository.add_arena_proposal(
        "cand_dead",
        RawArena(
            id="arena_dead",
            domain="Logistics operations",
            icp_user_role="Operations Manager",
            icp_buyer_role="VP Operations",
            geo="EU + US",
            channel_surface=["email"],
            solution_modality="saas",
            market_signals=["Strong operations pain"],
            signal_sources=["https://example.com/logistics"],
            market_size_signal="Large market",
            expected_sales_cycle="2-4 weeks",
            rationale="Strong arena",
        ),
    )

    assert created["status"] == "created"
    repository.set_selected_arena("cand_dead", "arena_dead")
    repository.mark_candidate_killed("cand_dead")

    repository.create_candidate(candidate_id="cand_retry", status="running")
    blocked = repository.add_arena_proposal(
        "cand_retry",
        RawArena(
            id="arena_retry",
            domain=" logistics  operations ",
            icp_user_role="operations-manager",
            icp_buyer_role="VP Operations",
            geo="EU + US",
            channel_surface=["email"],
            solution_modality="saas",
            market_signals=["Same arena"],
            signal_sources=["https://example.com/logistics-2"],
            market_size_signal="Large market",
            expected_sales_cycle="2-4 weeks",
            rationale="Should be blocked",
        ),
    )

    assert blocked["status"] == "blocked"


def test_add_signal_normalizes_source_type_caps_reliability_and_spend(tmp_path: Path) -> None:
    from truth_engine.adapters.db.migrate import upgrade_database
    from truth_engine.adapters.db.repositories import TruthEngineRepository
    from truth_engine.tools.runtime import RepositoryToolRuntime

    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)
    repository.create_schema()
    repository.create_candidate(candidate_id="cand_signal_norm", status="running")
    runtime = RepositoryToolRuntime(repository=repository)

    result = runtime.invoke(
        AgentName.SIGNAL_SCOUT,
        "add_signal",
        {
            "candidate_id": "cand_signal_norm",
            "signal": {
                "id": "sig_blog_1",
                "source_type": "job_post",
                "source_url": "https://example.com/jobs/123",
                "verbatim_quote": "Teams lose hours each week coordinating exceptions by hand.",
                "persona": "Operations manager",
                "inferred_pain": "Manual exception handling is slow.",
                "inferred_frequency": "weekly",
                "proof_of_spend": True,
                "switching_signal": False,
                "tags": ["coordination"],
                "reliability_score": 0.9,
            },
        },
    )

    stored_signal = repository.list_raw_signals("cand_signal_norm")[0]

    assert result["status"] == "created"
    assert result["applied_source_type"] == "job_posting"
    assert result["applied_reliability_score"] == 0.5
    assert result["proof_of_spend"] is False
    assert len(result["warnings"]) == 3
    assert stored_signal.source_type == "job_posting"
    assert stored_signal.reliability_score == 0.5
    assert stored_signal.proof_of_spend is False


def test_add_landscape_entry_coerces_string_lists_instead_of_crashing(
    tmp_path: Path,
) -> None:
    from truth_engine.adapters.db.migrate import upgrade_database
    from truth_engine.adapters.db.repositories import TruthEngineRepository
    from truth_engine.tools.runtime import RepositoryToolRuntime

    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)
    repository.create_schema()
    repository.create_candidate(candidate_id="cand_landscape", status="running")
    runtime = RepositoryToolRuntime(repository=repository)

    result = runtime.invoke(
        AgentName.LANDSCAPE_SCOUT,
        "add_landscape_entry",
        {
            "candidate_id": "cand_landscape",
            "entry": {
                "name": "ExampleCo",
                "type": "active_competitor",
                "status": "active",
                "source_url": "https://example.com",
                "what_they_do": "Workflow automation for logistics teams.",
                "relevance": "direct_competitor",
                "strengths": "Fast onboarding",
                "weaknesses": "Thin analytics",
                "lesson_for_us": "Position around deeper exception handling.",
            },
        },
    )

    assert result["status"] == "created"
    stored_entries = repository.list_landscape_entries("cand_landscape")
    assert len(stored_entries) == 1
    assert stored_entries[0].strengths == ["Fast onboarding"]
    assert stored_entries[0].weaknesses == ["Thin analytics"]
