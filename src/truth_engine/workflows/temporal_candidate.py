from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from truth_engine.contracts.decisions import (
        CandidateScoreSnapshot,
        ChannelValidationSnapshot,
        SkepticSnapshot,
        WedgeSnapshot,
    )
    from truth_engine.contracts.fixtures import (
        ArenaDiscoveryFixture,
        ChannelValidationFixtureRun,
        LandscapeResearchFixture,
        ScoringFixtureRun,
        SkepticFixtureRun,
        WedgeCritiqueFixtureRun,
        WedgeDesignFixtureRun,
    )
    from truth_engine.contracts.stages import DecisionEvent, ScoringResult
    from truth_engine.contracts.temporal import (
        DecisionActivityInput,
        KillActivityInput,
        StageExecutionInput,
        StageExecutionResult,
        SuccessActivityInput,
        TruthEngineRunInput,
        TruthEngineRunResult,
        TruthEngineWorkflowSnapshot,
    )
    from truth_engine.domain.enums import (
        BudgetMode,
        GateAction,
        SkepticRecommendation,
        Stage,
        WedgeVerdict,
    )
    from truth_engine.services.gates import decide_gate_a, decide_gate_b, decide_wedge_path


_STAGE_TIMEOUT = timedelta(minutes=30)
_META_TIMEOUT = timedelta(minutes=5)
_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=2)


@workflow.defn
class TruthEngineCandidateWorkflow:
    def __init__(self) -> None:
        self._snapshot = TruthEngineWorkflowSnapshot(
            candidate_id="",
            status="pending",
            current_stage=None,
            budget_mode=BudgetMode.NORMAL.value,
            trace_path="",
        )

    @workflow.query
    def describe(self) -> TruthEngineWorkflowSnapshot:
        return self._snapshot

    @workflow.run
    async def run(self, run_input: TruthEngineRunInput) -> TruthEngineRunResult:
        self._snapshot = TruthEngineWorkflowSnapshot(
            candidate_id=run_input.candidate_id,
            status="running",
            current_stage=None,
            budget_mode=BudgetMode.NORMAL.value,
            trace_path=run_input.trace_path(),
        )
        self._sync_memo()

        existing = await workflow.execute_activity(
            "truth_engine.ensure_candidate",
            run_input,
            start_to_close_timeout=_META_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        if existing is not None:
            result = (
                existing
                if isinstance(existing, TruthEngineRunResult)
                else TruthEngineRunResult(**existing)
            )
            self._set_final_snapshot(result)
            return result

        self._snapshot = self._snapshot_with(budget_mode=await self._budget_mode(run_input))

        arena_discovery_payload = await self._execute_stage_payload(
            "truth_engine.arena_discovery",
            StageExecutionInput(run_input=run_input),
            run_input,
        )
        if isinstance(arena_discovery_payload, TruthEngineRunResult):
            return arena_discovery_payload
        arena_discovery = ArenaDiscoveryFixture.model_validate(arena_discovery_payload)
        selected_arena = arena_discovery.evaluation.ranked_arenas[0]

        signal_payload = await self._execute_stage_payload(
            "truth_engine.signal_mining",
            StageExecutionInput(run_input=run_input),
            run_input,
        )
        if isinstance(signal_payload, TruthEngineRunResult):
            return signal_payload

        normalization_payload = await self._execute_stage_payload(
            "truth_engine.normalization",
            StageExecutionInput(run_input=run_input),
            run_input,
        )
        if isinstance(normalization_payload, TruthEngineRunResult):
            return normalization_payload

        landscape_payload = await self._execute_stage_payload(
            "truth_engine.landscape_research",
            StageExecutionInput(run_input=run_input),
            run_input,
        )
        if isinstance(landscape_payload, TruthEngineRunResult):
            return landscape_payload
        LandscapeResearchFixture.model_validate(landscape_payload)

        gate_a_iteration = 0
        scoring_result: ScoringResult | None = None
        skeptic_payload: dict[str, Any] | None = None
        while True:
            self._snapshot = self._snapshot_with(
                current_stage=Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                gate_a_iteration=gate_a_iteration,
            )

            scoring_payload = await self._execute_stage_payload(
                "truth_engine.scoring",
                StageExecutionInput(run_input=run_input, attempt_index=gate_a_iteration),
                run_input,
            )
            if isinstance(scoring_payload, TruthEngineRunResult):
                return scoring_payload
            scoring_run = ScoringFixtureRun.model_validate(scoring_payload)
            scoring_result = scoring_run.result

            skeptic_stage_payload = await self._execute_stage_payload(
                "truth_engine.skeptic",
                StageExecutionInput(run_input=run_input, attempt_index=gate_a_iteration),
                run_input,
            )
            if isinstance(skeptic_stage_payload, TruthEngineRunResult):
                return skeptic_stage_payload
            skeptic_run = SkepticFixtureRun.model_validate(skeptic_stage_payload)
            skeptic_payload = skeptic_run.result.model_dump(mode="json")
            budget_mode = await self._budget_mode(run_input)
            gate_a_decision = decide_gate_a(
                score=CandidateScoreSnapshot(total_score=scoring_result.top_candidate.total_score),
                skeptic=SkepticSnapshot(
                    recommendation=SkepticRecommendation(skeptic_run.result.recommendation)
                ),
                iteration=gate_a_iteration,
                max_iterations=2 if budget_mode == BudgetMode.NORMAL.value else 0,
            )
            gate_a_event = await self._record_decision(
                DecisionActivityInput(
                    run_input=run_input,
                    stage=Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                    gate="Gate A",
                    action=gate_a_decision.action.value,
                    reason=gate_a_decision.reason,
                    iteration=gate_a_iteration,
                    score=scoring_result.top_candidate.total_score,
                )
            )

            if gate_a_event.action is GateAction.INVESTIGATE:
                targeted_weakness = skeptic_run.result.primary_weakness
                targeted_signal_payload = await self._execute_stage_payload(
                    "truth_engine.signal_mining",
                    StageExecutionInput(
                        run_input=run_input,
                        attempt_index=gate_a_iteration + 1,
                        targeted_weakness=targeted_weakness,
                    ),
                    run_input,
                )
                if isinstance(targeted_signal_payload, TruthEngineRunResult):
                    return targeted_signal_payload

                targeted_normalization_payload = await self._execute_stage_payload(
                    "truth_engine.normalization",
                    StageExecutionInput(
                        run_input=run_input,
                        attempt_index=gate_a_iteration + 1,
                        targeted_weakness=targeted_weakness,
                    ),
                    run_input,
                )
                if isinstance(targeted_normalization_payload, TruthEngineRunResult):
                    return targeted_normalization_payload
                gate_a_iteration += 1
                continue

            if gate_a_event.action is GateAction.KILL:
                result = await workflow.execute_activity(
                    "truth_engine.finalize_kill",
                    KillActivityInput(
                        run_input=run_input,
                        decision_payload=gate_a_event.model_dump(mode="json"),
                        arena_payload=selected_arena.model_dump(mode="json"),
                        scoring_payload=scoring_run.result.model_dump(mode="json"),
                        skeptic_payload=skeptic_run.result.model_dump(mode="json"),
                    ),
                    start_to_close_timeout=_STAGE_TIMEOUT,
                    retry_policy=_ACTIVITY_RETRY_POLICY,
                )
                normalized = self._normalize_result(result)
                self._set_final_snapshot(normalized)
                return normalized

            break

        wedge_iteration = 0
        selected_wedge: dict[str, Any] | None = None
        while True:
            self._snapshot = self._snapshot_with(
                current_stage=Stage.WEDGE_DESIGN.value,
                wedge_iteration=wedge_iteration,
            )

            wedge_design_payload = await self._execute_stage_payload(
                "truth_engine.wedge_design",
                StageExecutionInput(run_input=run_input, attempt_index=wedge_iteration),
                run_input,
            )
            if isinstance(wedge_design_payload, TruthEngineRunResult):
                return wedge_design_payload
            wedge_design_run = WedgeDesignFixtureRun.model_validate(wedge_design_payload)

            wedge_critique_payload = await self._execute_stage_payload(
                "truth_engine.wedge_critique",
                StageExecutionInput(run_input=run_input, attempt_index=wedge_iteration),
                run_input,
            )
            if isinstance(wedge_critique_payload, TruthEngineRunResult):
                return wedge_critique_payload
            wedge_critique_run = WedgeCritiqueFixtureRun.model_validate(wedge_critique_payload)
            budget_mode = await self._budget_mode(run_input)
            wedge_decision = decide_wedge_path(
                wedge=WedgeSnapshot(
                    verdict=WedgeVerdict(
                        wedge_critique_run.result.evaluations[
                            wedge_critique_run.result.best_wedge_index
                        ].verdict
                    )
                ),
                iteration=wedge_iteration,
                max_iterations=2 if budget_mode == BudgetMode.NORMAL.value else 0,
            )
            wedge_event = await self._record_decision(
                DecisionActivityInput(
                    run_input=run_input,
                    stage=Stage.WEDGE_DESIGN.value,
                    gate="Wedge Path",
                    action=wedge_decision.action.value,
                    reason=wedge_decision.reason,
                    iteration=wedge_iteration,
                )
            )
            if wedge_event.action is GateAction.KILL:
                result = await workflow.execute_activity(
                    "truth_engine.finalize_kill",
                    KillActivityInput(
                        run_input=run_input,
                        decision_payload=wedge_event.model_dump(mode="json"),
                    ),
                    start_to_close_timeout=_STAGE_TIMEOUT,
                    retry_policy=_ACTIVITY_RETRY_POLICY,
                )
                normalized = self._normalize_result(result)
                self._set_final_snapshot(normalized)
                return normalized
            if wedge_event.action is GateAction.ADVANCE:
                selected_wedge = wedge_design_run.result.wedges[
                    wedge_critique_run.result.best_wedge_index
                ].model_dump(mode="json")
                break
            wedge_iteration += 1

        if selected_wedge is None or scoring_result is None or skeptic_payload is None:
            raise ValueError("Workflow could not resolve the selected wedge state.")

        gate_b_retry_index = 0
        while True:
            self._snapshot = self._snapshot_with(
                current_stage=Stage.BUYER_CHANNEL.value,
                gate_b_retry_index=gate_b_retry_index,
            )

            channel_payload = await self._execute_stage_payload(
                "truth_engine.channel_validation",
                StageExecutionInput(run_input=run_input, attempt_index=gate_b_retry_index),
                run_input,
            )
            if isinstance(channel_payload, TruthEngineRunResult):
                return channel_payload
            channel_run = ChannelValidationFixtureRun.model_validate(channel_payload)
            budget_mode = await self._budget_mode(run_input)
            gate_b_decision = decide_gate_b(
                validation=ChannelValidationSnapshot(
                    verdict=channel_run.result.verdict,
                    total_reachable_leads=channel_run.result.total_reachable_leads,
                    channel_count=len(channel_run.result.channels),
                    user_role=channel_run.result.user_role,
                    buyer_role=channel_run.result.buyer_role,
                    buyer_is_user=channel_run.result.buyer_is_user,
                    estimated_cost_per_conversation=channel_run.result.estimated_cost_per_conversation,
                ),
                retries_used=gate_b_retry_index,
                max_retries=1 if budget_mode == BudgetMode.NORMAL.value else 0,
            )
            gate_b_event = await self._record_decision(
                DecisionActivityInput(
                    run_input=run_input,
                    stage=Stage.BUYER_CHANNEL.value,
                    gate="Gate B",
                    action=gate_b_decision.action.value,
                    reason=gate_b_decision.reason,
                    iteration=gate_b_retry_index,
                )
            )
            if gate_b_event.action is GateAction.RETRY:
                gate_b_retry_index += 1
                continue
            if gate_b_event.action is GateAction.KILL:
                result = await workflow.execute_activity(
                    "truth_engine.finalize_kill",
                    KillActivityInput(
                        run_input=run_input,
                        decision_payload=gate_b_event.model_dump(mode="json"),
                    ),
                    start_to_close_timeout=_STAGE_TIMEOUT,
                    retry_policy=_ACTIVITY_RETRY_POLICY,
                )
                normalized = self._normalize_result(result)
                self._set_final_snapshot(normalized)
                return normalized

            result = await workflow.execute_activity(
                "truth_engine.finalize_success",
                SuccessActivityInput(
                    run_input=run_input,
                    arena_payload=selected_arena.model_dump(mode="json"),
                    scoring_payload=scoring_result.model_dump(mode="json"),
                    skeptic_payload=skeptic_payload,
                    selected_wedge_payload=selected_wedge,
                    channel_validation_payload=channel_run.result.model_dump(mode="json"),
                ),
                start_to_close_timeout=_STAGE_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY_POLICY,
            )
            normalized = self._normalize_result(result)
            self._set_final_snapshot(normalized)
            return normalized

    async def _execute_stage_payload(
        self,
        activity_name: str,
        stage_input: StageExecutionInput,
        run_input: TruthEngineRunInput,
    ) -> dict[str, Any] | TruthEngineRunResult:
        result = await workflow.execute_activity(
            activity_name,
            stage_input,
            start_to_close_timeout=_STAGE_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        if not isinstance(result, StageExecutionResult):
            result = StageExecutionResult(**result)
        if result.ok:
            self._snapshot = self._snapshot_with(budget_mode=await self._budget_mode(run_input))
            if result.payload is None:
                raise ValueError(f"{activity_name} returned no payload.")
            return result.payload
        await workflow.execute_activity(
            "truth_engine.record_budget_warning",
            run_input,
            start_to_close_timeout=_META_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        stage = result.safety_cap_stage or Stage.ARENA_DISCOVERY.value
        event = await self._record_decision(
            DecisionActivityInput(
                run_input=run_input,
                stage=stage,
                gate="Budget Safety Cap",
                action=GateAction.KILL.value,
                reason="Candidate exceeded the EUR 7 safety cap.",
                iteration=result.safety_cap_attempt_index,
            )
        )
        final_result = await workflow.execute_activity(
            "truth_engine.finalize_kill",
            KillActivityInput(
                run_input=run_input,
                decision_payload=event.model_dump(mode="json"),
            ),
            start_to_close_timeout=_STAGE_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        normalized = self._normalize_result(final_result)
        self._set_final_snapshot(normalized)
        return normalized

    async def _budget_mode(self, run_input: TruthEngineRunInput) -> str:
        result = await workflow.execute_activity(
            "truth_engine.current_budget_mode",
            run_input,
            start_to_close_timeout=_META_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        return str(result)

    async def _record_decision(self, decision_input: DecisionActivityInput) -> DecisionEvent:
        payload = await workflow.execute_activity(
            "truth_engine.record_decision",
            decision_input,
            start_to_close_timeout=_META_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        event = DecisionEvent.model_validate(payload)
        self._snapshot = self._snapshot_with(
            budget_mode=event.metadata.get("budget_mode", self._snapshot.budget_mode),
            last_decision_action=event.action.value,
            last_decision_reason=event.reason,
        )
        return event

    def _set_final_snapshot(self, result: TruthEngineRunResult) -> None:
        self._snapshot = TruthEngineWorkflowSnapshot(
            candidate_id=result.candidate_id,
            status=result.status,
            current_stage=self._snapshot.current_stage,
            budget_mode=self._snapshot.budget_mode,
            trace_path=result.trace_path,
            gate_a_iteration=self._snapshot.gate_a_iteration,
            wedge_iteration=self._snapshot.wedge_iteration,
            gate_b_retry_index=self._snapshot.gate_b_retry_index,
            last_decision_action=DecisionEvent.model_validate(result.final_decision_payload).action.value,
            last_decision_reason=DecisionEvent.model_validate(result.final_decision_payload).reason,
            dossier_json_path=result.dossier_json_path,
            dossier_markdown_path=result.dossier_markdown_path,
        )
        self._sync_memo()

    def _snapshot_with(self, **changes: Any) -> TruthEngineWorkflowSnapshot:
        payload = self._snapshot.__dict__.copy()
        payload.update(changes)
        self._snapshot = TruthEngineWorkflowSnapshot(**payload)
        self._sync_memo()
        return self._snapshot

    def _normalize_result(self, result: Any) -> TruthEngineRunResult:
        if isinstance(result, TruthEngineRunResult):
            return result
        return TruthEngineRunResult(**result)

    def _sync_memo(self) -> None:
        workflow.upsert_memo(
            {
                "candidate_id": self._snapshot.candidate_id,
                "status": self._snapshot.status,
                "current_stage": self._snapshot.current_stage or "",
                "budget_mode": self._snapshot.budget_mode,
                "trace_path": self._snapshot.trace_path,
                "last_decision_action": self._snapshot.last_decision_action or "",
                "last_decision_reason": self._snapshot.last_decision_reason or "",
                "dossier_json_path": self._snapshot.dossier_json_path or "",
                "dossier_markdown_path": self._snapshot.dossier_markdown_path or "",
            }
        )
