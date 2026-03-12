from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import is_dataclass
from typing import Any

from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.worker import Worker

from truth_engine.activities.temporal import TemporalCandidateActivities
from truth_engine.config.settings import Settings
from truth_engine.contracts.temporal import TruthEngineRunInput, TruthEngineRunResult
from truth_engine.workflows.temporal_candidate import TruthEngineCandidateWorkflow


def workflow_id_for_candidate(candidate_id: str) -> str:
    return f"truth-engine-{candidate_id}"


async def connect_temporal(settings: Settings) -> Client:
    return await Client.connect(
        settings.temporal_host,
        namespace=settings.temporal_namespace,
    )


async def run_worker(settings: Settings) -> None:
    client = await connect_temporal(settings)
    activities = TemporalCandidateActivities()
    with ThreadPoolExecutor(max_workers=8) as executor:
        worker = Worker(
            client,
            task_queue=settings.temporal_task_queue,
            workflows=[TruthEngineCandidateWorkflow],
            activities=activities.activity_callables(),
            activity_executor=executor,
        )
        await worker.run()


async def execute_truth_engine_run(
    settings: Settings,
    run_input: TruthEngineRunInput,
    *,
    inline_worker: bool = True,
    wait_for_result: bool = True,
) -> TruthEngineRunResult | str:
    client = await connect_temporal(settings)
    if inline_worker:
        activities = TemporalCandidateActivities()
        with ThreadPoolExecutor(max_workers=8) as executor:
            async with Worker(
                client,
                task_queue=settings.temporal_task_queue,
                workflows=[TruthEngineCandidateWorkflow],
                activities=activities.activity_callables(),
                activity_executor=executor,
            ):
                handle = await _start_or_attach(client, settings, run_input)
                if not wait_for_result:
                    return handle.id
                result = await handle.result()
                return _normalize_result(result)

    handle = await _start_or_attach(client, settings, run_input)
    if not wait_for_result:
        return handle.id
    result = await handle.result()
    return _normalize_result(result)


async def _start_or_attach(
    client: Client,
    settings: Settings,
    run_input: TruthEngineRunInput,
) -> WorkflowHandle[Any, TruthEngineRunResult]:
    return await client.start_workflow(
        TruthEngineCandidateWorkflow.run,
        run_input,
        id=workflow_id_for_candidate(run_input.candidate_id),
        task_queue=settings.temporal_task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        memo={
            "candidate_id": run_input.candidate_id,
            "mode": run_input.mode,
            "prompt_version": run_input.prompt_version,
            "trace_path": run_input.trace_path(),
        },
        static_summary=f"Truth Engine {run_input.mode} run",
        static_details=f"candidate={run_input.candidate_id}",
    )


def _normalize_result(result: Any) -> TruthEngineRunResult:
    if isinstance(result, TruthEngineRunResult):
        return result
    if is_dataclass(result) and not isinstance(result, type):
        return TruthEngineRunResult(**result.__dict__)
    if isinstance(result, dict):
        return TruthEngineRunResult(**result)
    raise TypeError(f"Unexpected workflow result type: {type(result).__name__}")
