from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from truth_engine.activities.temporal import TemporalCandidateActivities
from truth_engine.adapters.db.migrate import upgrade_database
from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.contracts.temporal import TruthEngineRunInput
from truth_engine.workflows.temporal_candidate import TruthEngineCandidateWorkflow

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "workflows"


def test_temporal_schema_uses_agent_checkpoints_but_not_workflow_checkpoints(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    upgrade_database(database_url)

    inspector = inspect(create_engine(database_url, future=True))
    table_names = set(inspector.get_table_names())

    assert "agent_checkpoint" in table_names
    assert "workflow_checkpoint" not in table_names


def test_temporal_fixture_workflow_reaches_gate_b_and_persists_artifacts(tmp_path: Path) -> None:
    asyncio.run(_run_temporal_fixture_workflow_test(tmp_path))


async def _run_temporal_fixture_workflow_test(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    output_dir = tmp_path / "out"
    upgrade_database(database_url)

    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server unavailable in this environment: {error}")

    async with env:
        activities = TemporalCandidateActivities()
        with ThreadPoolExecutor(max_workers=4) as executor:
            async with Worker(
                env.client,
                task_queue="truth-engine-test",
                workflows=[TruthEngineCandidateWorkflow],
                activities=activities.activity_callables(),
                activity_executor=executor,
            ):
                result_payload = await env.client.execute_workflow(
                    TruthEngineCandidateWorkflow.run,
                    TruthEngineRunInput(
                        mode="fixture",
                        candidate_id="cand_logistics_ops",
                        database_url=database_url,
                        output_dir=str(output_dir),
                        prompt_version="temporal-test",
                        fixture_path=str(FIXTURE_ROOT / "investigate_revise_reachable.json"),
                    ),
                    id="truth-engine-cand_logistics_ops",
                    task_queue="truth-engine-test",
                )

    repository = TruthEngineRepository.from_database_url(database_url)
    candidate = repository.get_candidate("cand_logistics_ops")
    assert candidate is not None
    assert candidate.status == "passed_gate_b"
    assert result_payload.status == "passed_gate_b"
    assert (output_dir / "cand_logistics_ops.trace.md").exists()
    assert (output_dir / "cand_logistics_ops.json").exists()
    assert (output_dir / "cand_logistics_ops.md").exists()
