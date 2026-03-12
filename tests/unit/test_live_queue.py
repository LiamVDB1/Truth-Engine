from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from truth_engine.activities.live import LiveActivityBundle
from truth_engine.adapters.db.migrate import upgrade_database
from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.adapters.llm.litellm_runner import LiteLLMAgentRunner
from truth_engine.config.settings import Settings
from truth_engine.contracts.live import FounderConstraints, LiveRunRequest
from truth_engine.contracts.models import RawArena
from truth_engine.contracts.stages import EvaluatedArena
from truth_engine.tools.runtime import RepositoryToolRuntime


class _UnexpectedAgentRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("seeded arena discovery should not invoke the live agent runner")


def test_resolve_live_request_uses_unexplored_arena_queue_before_new_scout(
    tmp_path: Path,
) -> None:
    from truth_engine.cli.main import _resolve_live_request

    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)

    request = LiveRunRequest(
        candidate_id="cand_source",
        founder_constraints=FounderConstraints(geo_preference="DACH"),
    )
    repository.create_candidate(
        "cand_source",
        status="killed",
        request_payload=request.model_dump(mode="json"),
    )
    repository.add_arena_proposal(
        "cand_source",
        RawArena(
            id="arena_queue_1",
            domain="Field service dispatch",
            icp_user_role="Service Operations Manager",
            icp_buyer_role="VP Operations",
            geo="EU",
            channel_surface=["linkedin", "email"],
            solution_modality="saas",
            market_signals=["Growing operational complexity"],
            signal_sources=["https://example.com/dispatch"],
            market_size_signal="Large installed base",
            expected_sales_cycle="2-4 weeks",
            rationale="Worth exploring next.",
        ),
    )

    resolved = _resolve_live_request(
        argparse.Namespace(request_file=None, candidate_id=None),
        repository,
    )

    assert resolved.candidate_id != "cand_source"
    assert resolved.founder_constraints.geo_preference == "DACH"
    assert resolved.seed_arena is not None
    assert resolved.seed_arena.domain == "Field service dispatch"
    assert resolved.seed_arena_evaluation is not None
    assert resolved.seed_arena_evaluation.arena.domain == "Field service dispatch"

    next_resolved = _resolve_live_request(
        argparse.Namespace(request_file=None, candidate_id=None),
        repository,
    )

    assert next_resolved.seed_arena is None
    assert next_resolved.seed_arena_evaluation is None


def test_live_activity_bundle_uses_seeded_arena_without_running_arena_scout(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)

    seed_arena = RawArena(
        id="arena_seeded",
        domain="Warehouse exception workflows",
        icp_user_role="Operations Manager",
        icp_buyer_role="VP Operations",
        geo="EU + US",
        channel_surface=["linkedin", "reddit"],
        solution_modality="saas",
        market_signals=["Visible pain on public forums"],
        signal_sources=["https://example.com/warehouse"],
        market_size_signal="Large ops software market",
        expected_sales_cycle="2-4 weeks",
        rationale="Already queued from an earlier live run.",
    )
    seed_evaluation = EvaluatedArena(
        arena=seed_arena,
        score=72,
        dimension_scores={"pain_signal_visibility": 8},
        dimension_rationale={"pain_signal_visibility": "Already evaluated earlier."},
        viability_verdict="viable",
        risks=["Needs fresh signal mining."],
        recommended_first_sources=["reddit", "job_postings"],
    )
    bundle = LiveActivityBundle(
        request=LiveRunRequest(
            candidate_id="cand_seeded",
            seed_arena=seed_arena,
            seed_arena_evaluation=seed_evaluation,
        ),
        repository=repository,
        settings=Settings(database_url=database_url),
        agent_runner=cast(LiteLLMAgentRunner, _UnexpectedAgentRunner()),
        tool_runtime=RepositoryToolRuntime(repository),
    )

    result = bundle.arena_discovery()

    assert result.scout_metrics.cost_eur == 0.0
    assert result.evaluator_metrics.cost_eur == 0.0
    assert result.raw_arenas == [seed_arena]
    assert result.evaluation.ranked_arenas == [seed_evaluation]
