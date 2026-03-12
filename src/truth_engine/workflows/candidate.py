from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from truth_engine.activities.base import ActivityBundle
from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.config.model_routing import resolve_agent_model
from truth_engine.config.settings import Settings
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
    NormalizationFixtureRun,
    ScoringFixtureRun,
    SignalMiningFixtureRun,
    SkepticFixtureRun,
    WedgeCritiqueFixtureRun,
    WedgeDesignFixtureRun,
)
from truth_engine.contracts.models import CostRecord, ProblemUnit, RawArena
from truth_engine.contracts.stages import (
    ActivityMetrics,
    ArenaEvaluation,
    ArenaSearchResult,
    CandidateDossier,
    ChannelValidation,
    DecisionEvent,
    EvaluatedArena,
    LandscapeReport,
    NormalizationResult,
    ScoredCandidate,
    ScoringResult,
    SignalMiningResult,
    SkepticReport,
    WedgeCritique,
    WedgeHypothesis,
    WedgeProposal,
    WorkflowOutcome,
    wedge_verdict_for_critique,
)
from truth_engine.domain.enums import (
    AgentName,
    BudgetMode,
    GateAction,
    SkepticRecommendation,
    Stage,
)
from truth_engine.prompts.builder import build_prompt
from truth_engine.services.budgets import candidate_budget_mode
from truth_engine.services.gates import decide_gate_a, decide_gate_b, decide_wedge_path
from truth_engine.services.learnings import (
    extract_kill_learnings,
    extract_pass_learnings,
)
from truth_engine.services.logging import (
    flow_budget_warning,
    flow_gate_decision,
    flow_outcome,
    flow_stage_done,
    flow_stage_start,
)
from truth_engine.services.run_trace import RunTraceWriter
from truth_engine.tools.runtime import RepositoryToolRuntime

TStageModel = TypeVar("TStageModel", bound=BaseModel)


class PersistsToolState(Protocol):
    persists_tool_state: bool


class CandidateWorkflowRunner:
    def __init__(
        self,
        repository: TruthEngineRepository,
        settings: Settings,
        *,
        tool_runtime: RepositoryToolRuntime | None = None,
        trace_writer: RunTraceWriter | None = None,
    ):
        self.repository = repository
        self.settings = settings
        self.tool_runtime = tool_runtime or RepositoryToolRuntime(repository)
        self.trace_writer = trace_writer

    def run(self, activities: ActivityBundle) -> WorkflowOutcome:
        candidate_id = activities.candidate_id
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            request_payload = None
            live_request = getattr(activities, "request", None)
            if isinstance(live_request, BaseModel):
                request_payload = live_request.model_dump(mode="json")
            self.repository.create_candidate(
                candidate_id=candidate_id,
                status="running",
                request_payload=request_payload,
            )
        elif candidate.request_payload is None:
            live_request = getattr(activities, "request", None)
            if isinstance(live_request, BaseModel):
                self.repository.update_candidate(
                    candidate_id,
                    request_payload=live_request.model_dump(mode="json"),
                )
        elif candidate.status == "passed_gate_b":
            dossier = self.repository.load_dossier(candidate_id)
            if dossier is None:
                raise ValueError(
                    f"Candidate {candidate_id} passed Gate B without a stored dossier."
                )
            final_decision = self._latest_decision_event(candidate_id)
            if final_decision is None:
                raise ValueError(f"Candidate {candidate_id} is missing its final decision event.")
            return WorkflowOutcome(
                candidate_id=candidate_id,
                status="passed_gate_b",
                final_decision=final_decision,
                dossier=dossier,
            )
        elif candidate.status == "killed":
            final_decision = self._latest_decision_event(candidate_id)
            if final_decision is None:
                raise ValueError(f"Candidate {candidate_id} is missing its kill decision event.")
            return WorkflowOutcome(
                candidate_id=candidate_id,
                status="killed",
                final_decision=final_decision,
            )
        try:
            selected_arena = self._checkpointed_step(
                candidate_id=candidate_id,
                attempt_index=0,
                stage_label="Arena Discovery",
                agent_label="arena_scout",
                execute=activities.arena_discovery,
                apply=lambda run: self._apply_arena_discovery(
                    candidate_id=candidate_id,
                    activities=activities,
                    run=run,
                ),
                model_type=ArenaDiscoveryFixture,
                cost_of=lambda run: run.scout_metrics.cost_eur + run.evaluator_metrics.cost_eur,
                resume=lambda: self._resume_arena_discovery(candidate_id),
            ).evaluation.ranked_arenas[0]

            self._checkpointed_step(
                candidate_id=candidate_id,
                attempt_index=0,
                stage_label="Signal Mining",
                agent_label="signal_scout",
                execute=activities.signal_mining,
                apply=lambda run: self._apply_signal_mining(
                    candidate_id=candidate_id,
                    run=run,
                    attempt_index=0,
                    persists_tool_state=activities.persists_tool_state,
                ),
                model_type=SignalMiningFixtureRun,
                cost_of=lambda run: run.metrics.cost_eur,
                resume=lambda: self._resume_signal_mining(candidate_id, 0),
            )
            self._checkpointed_step(
                candidate_id=candidate_id,
                attempt_index=0,
                stage_label="Normalization",
                agent_label="normalizer",
                execute=activities.normalization,
                apply=lambda run: self._apply_normalization(
                    candidate_id=candidate_id,
                    run=run,
                    attempt_index=0,
                ),
                model_type=NormalizationFixtureRun,
                cost_of=lambda run: run.metrics.cost_eur,
                summary=lambda run: f"{len(run.result.problem_units)} problem units",
                resume=lambda: self._resume_normalization(candidate_id, 0),
            )

            self._checkpointed_step(
                candidate_id=candidate_id,
                attempt_index=0,
                stage_label="Landscape",
                agent_label="landscape_scout",
                execute=activities.landscape_research,
                apply=lambda run: self._apply_landscape_research(
                    candidate_id=candidate_id,
                    activities=activities,
                    run=run,
                ),
                model_type=LandscapeResearchFixture,
                cost_of=lambda run: run.metrics.cost_eur,
                resume=lambda: self._resume_landscape_research(candidate_id),
            )

            selected_problem_unit: ProblemUnit | None = None
            scoring_result: ScoredCandidate | None = None
            skeptic_result: SkepticReport | None = None
            gate_a_iteration = 0
            while True:
                scoring_attempt = gate_a_iteration

                def apply_scoring(
                    run: ScoringFixtureRun,
                    attempt_index: int = scoring_attempt,
                ) -> None:
                    self._apply_scoring(
                        candidate_id=candidate_id,
                        run=run,
                        attempt_index=attempt_index,
                    )

                def resume_scoring(
                    attempt_index: int = scoring_attempt,
                ) -> ScoringFixtureRun | None:
                    return self._resume_scoring(candidate_id, attempt_index)

                scoring_run = self._checkpointed_step(
                    candidate_id=candidate_id,
                    attempt_index=scoring_attempt,
                    stage_label="Scoring",
                    agent_label="scorer",
                    execute=activities.scoring,
                    apply=apply_scoring,
                    model_type=ScoringFixtureRun,
                    cost_of=lambda run: run.metrics.cost_eur,
                    summary=lambda run: f"score={run.result.top_candidate.total_score}",
                    attempt=scoring_attempt,
                    resume=resume_scoring,
                )
                scoring_result = scoring_run.result.top_candidate
                selected_problem_unit = self.repository.get_problem_unit(
                    candidate_id, scoring_result.problem_unit_id
                )
                if selected_problem_unit is None:
                    raise ValueError(f"Unknown problem unit: {scoring_result.problem_unit_id}")

                def apply_skeptic(
                    run: SkepticFixtureRun,
                    attempt_index: int = scoring_attempt,
                ) -> None:
                    self._apply_skeptic(
                        candidate_id=candidate_id,
                        run=run,
                        attempt_index=attempt_index,
                    )

                def resume_skeptic(
                    attempt_index: int = scoring_attempt,
                ) -> SkepticFixtureRun | None:
                    return self._resume_skeptic(candidate_id, attempt_index)

                skeptic_run = self._checkpointed_step(
                    candidate_id=candidate_id,
                    attempt_index=scoring_attempt,
                    stage_label="Skeptic",
                    agent_label="skeptic",
                    execute=activities.skeptic,
                    apply=apply_skeptic,
                    model_type=SkepticFixtureRun,
                    cost_of=lambda run: run.metrics.cost_eur,
                    summary=lambda run: f"rec={run.result.recommendation}",
                    attempt=scoring_attempt,
                    resume=resume_skeptic,
                )
                skeptic_result = skeptic_run.result

                gate_a_event = self.repository.get_decision_event(
                    candidate_id=candidate_id,
                    stage=Stage.LANDSCAPE_SCORING_SKEPTIC,
                    iteration=gate_a_iteration,
                )
                if gate_a_event is None:
                    gate_a_decision = decide_gate_a(
                        score=CandidateScoreSnapshot(total_score=scoring_result.total_score),
                        skeptic=SkepticSnapshot(
                            recommendation=SkepticRecommendation(skeptic_result.recommendation)
                        ),
                        iteration=gate_a_iteration,
                        max_iterations=self._optional_loop_limit(candidate_id),
                    )
                    gate_a_event = self._append_decision(
                        candidate_id=candidate_id,
                        stage=Stage.LANDSCAPE_SCORING_SKEPTIC,
                        action=gate_a_decision.action,
                        reason=gate_a_decision.reason,
                        iteration=gate_a_iteration,
                    )
                self._gate_decision(
                    candidate_id,
                    "Gate A",
                    gate_a_event.action.value,
                    gate_a_event.reason,
                    score=scoring_result.total_score,
                    budget_mode=self._budget_mode(candidate_id).value,
                )

                if gate_a_event.action is GateAction.INVESTIGATE:
                    targeted_attempt = gate_a_iteration + 1
                    targeted_weakness = skeptic_result.primary_weakness

                    def execute_targeted_signal(
                        weakness: str = targeted_weakness,
                    ) -> SignalMiningFixtureRun:
                        return activities.signal_mining(weakness)

                    def apply_targeted_signal(
                        run: SignalMiningFixtureRun,
                        attempt_index: int = targeted_attempt,
                    ) -> None:
                        self._apply_signal_mining(
                            candidate_id=candidate_id,
                            run=run,
                            attempt_index=attempt_index,
                            persists_tool_state=activities.persists_tool_state,
                        )

                    def resume_targeted_signal(
                        attempt_index: int = targeted_attempt,
                        weakness: str = targeted_weakness,
                    ) -> SignalMiningFixtureRun | None:
                        return self._resume_signal_mining(
                            candidate_id,
                            attempt_index,
                            targeted_weakness=weakness,
                        )

                    self._checkpointed_step(
                        candidate_id=candidate_id,
                        attempt_index=targeted_attempt,
                        stage_label="Targeted Mining",
                        agent_label="signal_scout",
                        execute=execute_targeted_signal,
                        apply=apply_targeted_signal,
                        model_type=SignalMiningFixtureRun,
                        cost_of=lambda run: run.metrics.cost_eur,
                        extra=f"weakness: {targeted_weakness}",
                        resume=resume_targeted_signal,
                    )

                    def apply_targeted_normalization(
                        run: NormalizationFixtureRun,
                        attempt_index: int = targeted_attempt,
                        weakness: str = targeted_weakness,
                    ) -> None:
                        self._apply_normalization(
                            candidate_id=candidate_id,
                            run=run,
                            attempt_index=attempt_index,
                            targeted_weakness=weakness,
                        )

                    def resume_targeted_normalization(
                        attempt_index: int = targeted_attempt,
                    ) -> NormalizationFixtureRun | None:
                        return self._resume_normalization(candidate_id, attempt_index)

                    self._checkpointed_step(
                        candidate_id=candidate_id,
                        attempt_index=targeted_attempt,
                        stage_label="Normalization",
                        agent_label="normalizer",
                        execute=activities.normalization,
                        apply=apply_targeted_normalization,
                        model_type=NormalizationFixtureRun,
                        cost_of=lambda run: run.metrics.cost_eur,
                        summary=lambda run: f"{len(run.result.problem_units)} problem units",
                        resume=resume_targeted_normalization,
                    )
                    gate_a_iteration += 1
                    continue

                if gate_a_event.action is GateAction.KILL:
                    self._store_learnings(
                        candidate_id,
                        extract_kill_learnings(
                            candidate_id,
                            gate_a_event.reason,
                            arena=selected_arena,
                            scoring=scoring_result,
                            skeptic=skeptic_result,
                        ),
                    )
                    return self._kill_outcome(candidate_id, gate_a_event)

                break

            wedge_iteration = 0
            selected_wedge: WedgeHypothesis | None = None
            while True:
                wedge_attempt = wedge_iteration

                def apply_wedge_design(
                    run: WedgeDesignFixtureRun,
                    attempt_index: int = wedge_attempt,
                ) -> None:
                    self._apply_wedge_design(
                        candidate_id=candidate_id,
                        run=run,
                        attempt_index=attempt_index,
                    )

                def resume_wedge_design(
                    attempt_index: int = wedge_attempt,
                ) -> WedgeDesignFixtureRun | None:
                    return self._resume_wedge_design(candidate_id, attempt_index)

                wedge_design_run = self._checkpointed_step(
                    candidate_id=candidate_id,
                    attempt_index=wedge_attempt,
                    stage_label="Wedge Design",
                    agent_label="wedge_designer",
                    execute=activities.wedge_design,
                    apply=apply_wedge_design,
                    model_type=WedgeDesignFixtureRun,
                    cost_of=lambda run: run.metrics.cost_eur,
                    summary=lambda run: f"{len(run.result.wedges)} wedges",
                    attempt=wedge_attempt,
                    resume=resume_wedge_design,
                )

                def apply_wedge_critique(
                    run: WedgeCritiqueFixtureRun,
                    attempt_index: int = wedge_attempt,
                ) -> None:
                    self._apply_wedge_critique(
                        candidate_id=candidate_id,
                        run=run,
                        attempt_index=attempt_index,
                    )

                def resume_wedge_critique(
                    attempt_index: int = wedge_attempt,
                ) -> WedgeCritiqueFixtureRun | None:
                    return self._resume_wedge_critique(candidate_id, attempt_index)

                wedge_critique_run = self._checkpointed_step(
                    candidate_id=candidate_id,
                    attempt_index=wedge_attempt,
                    stage_label="Wedge Critique",
                    agent_label="wedge_critic",
                    execute=activities.wedge_critique,
                    apply=apply_wedge_critique,
                    model_type=WedgeCritiqueFixtureRun,
                    cost_of=lambda run: run.metrics.cost_eur,
                    summary=lambda run: f"best={run.result.best_wedge_index}",
                    attempt=wedge_attempt,
                    resume=resume_wedge_critique,
                )

                wedge_event = self.repository.get_decision_event(
                    candidate_id=candidate_id,
                    stage=Stage.WEDGE_DESIGN,
                    iteration=wedge_iteration,
                )
                if wedge_event is None:
                    wedge_decision = decide_wedge_path(
                        wedge=WedgeSnapshot(
                            verdict=wedge_verdict_for_critique(wedge_critique_run.result)
                        ),
                        iteration=wedge_iteration,
                        max_iterations=self._optional_loop_limit(candidate_id),
                    )
                    wedge_event = self._append_decision(
                        candidate_id=candidate_id,
                        stage=Stage.WEDGE_DESIGN,
                        action=wedge_decision.action,
                        reason=wedge_decision.reason,
                        iteration=wedge_iteration,
                    )
                self._gate_decision(
                    candidate_id,
                    "Wedge Path",
                    wedge_event.action.value,
                    wedge_event.reason,
                    budget_mode=self._budget_mode(candidate_id).value,
                )

                if wedge_event.action is GateAction.KILL:
                    return self._kill_outcome(candidate_id, wedge_event)

                if wedge_event.action is GateAction.ADVANCE:
                    best_index = wedge_critique_run.result.best_wedge_index
                    selected_wedge = wedge_design_run.result.wedges[best_index]
                    self.repository.replace_wedges(
                        candidate_id,
                        [wedge.model_dump(mode="json") for wedge in wedge_design_run.result.wedges],
                        selected_wedge.id,
                    )
                    self.repository.update_candidate(
                        candidate_id,
                        current_stage=Stage.WEDGE_DESIGN.value,
                        selected_wedge_id=selected_wedge.id,
                    )
                    break

                wedge_iteration += 1

            if selected_wedge is None or selected_problem_unit is None or scoring_result is None:
                raise ValueError("Workflow could not resolve the selected wedge state.")

            gate_b_retry_index = 0
            while True:
                channel_attempt = gate_b_retry_index

                def apply_channel_validation(
                    run: ChannelValidationFixtureRun,
                    attempt_index: int = channel_attempt,
                ) -> None:
                    self._apply_channel_validation(
                        candidate_id=candidate_id,
                        run=run,
                        attempt_index=attempt_index,
                    )

                def resume_channel_validation(
                    attempt_index: int = channel_attempt,
                ) -> ChannelValidationFixtureRun | None:
                    return self._resume_channel_validation(candidate_id, attempt_index)

                channel_validation_run = self._checkpointed_step(
                    candidate_id=candidate_id,
                    attempt_index=channel_attempt,
                    stage_label="Buyer/Channel",
                    agent_label="buyer_channel_validator",
                    execute=activities.channel_validation,
                    apply=apply_channel_validation,
                    model_type=ChannelValidationFixtureRun,
                    cost_of=lambda run: run.metrics.cost_eur,
                    summary=lambda run: (
                        f"verdict={run.result.verdict.value} "
                        f"leads={run.result.total_reachable_leads}"
                    ),
                    attempt=channel_attempt,
                    resume=resume_channel_validation,
                )

                gate_b_event = self.repository.get_decision_event(
                    candidate_id=candidate_id,
                    stage=Stage.BUYER_CHANNEL,
                    iteration=gate_b_retry_index,
                )
                if gate_b_event is None:
                    gate_b_decision = decide_gate_b(
                        validation=ChannelValidationSnapshot(
                            verdict=channel_validation_run.result.verdict,
                            total_reachable_leads=channel_validation_run.result.total_reachable_leads,
                            channel_count=len(channel_validation_run.result.channels),
                            user_role=channel_validation_run.result.user_role,
                            buyer_role=channel_validation_run.result.buyer_role,
                            buyer_is_user=channel_validation_run.result.buyer_is_user,
                            estimated_cost_per_conversation=channel_validation_run.result.estimated_cost_per_conversation,
                        ),
                        retries_used=gate_b_retry_index,
                        max_retries=self._optional_retry_limit(candidate_id),
                    )
                    gate_b_event = self._append_decision(
                        candidate_id=candidate_id,
                        stage=Stage.BUYER_CHANNEL,
                        action=gate_b_decision.action,
                        reason=gate_b_decision.reason,
                        iteration=gate_b_retry_index,
                    )
                self._gate_decision(
                    candidate_id,
                    "Gate B",
                    gate_b_event.action.value,
                    gate_b_event.reason,
                    budget_mode=self._budget_mode(candidate_id).value,
                )
                if gate_b_event.action is GateAction.RETRY:
                    gate_b_retry_index += 1
                    continue
                if gate_b_event.action is GateAction.KILL:
                    return self._kill_outcome(candidate_id, gate_b_event)

                dossier = self._build_dossier(
                    candidate_id=candidate_id,
                    arena=selected_arena,
                    problem_unit=selected_problem_unit,
                    scoring=scoring_result,
                    skeptic=skeptic_result,
                    selected_wedge=selected_wedge,
                    caution_flags=self._caution_flags(candidate_id),
                    channel_validation=channel_validation_run.result,
                )
                self.repository.store_dossier(candidate_id, dossier)
                self.repository.update_candidate(
                    candidate_id,
                    status="passed_gate_b",
                    current_stage=Stage.BUYER_CHANNEL.value,
                )
                self._store_learnings(
                    candidate_id,
                    extract_pass_learnings(candidate_id, dossier),
                )
                candidate = self.repository.get_candidate(candidate_id)
                total_cost = candidate.total_cost_eur if candidate else 0.0
                self._outcome(candidate_id, "passed_gate_b", total_cost_eur=total_cost)
                return WorkflowOutcome(
                    candidate_id=candidate_id,
                    status="passed_gate_b",
                    final_decision=gate_b_event,
                    dossier=dossier,
                )
        except BudgetSafetyCapExceeded as error:
            candidate = self.repository.get_candidate(candidate_id)
            total_cost = candidate.total_cost_eur if candidate else 0.0
            self._budget_warning(candidate_id, "safety_cap", total_cost)
            safety_cap_event = self._append_decision(
                candidate_id=candidate_id,
                stage=error.stage,
                action=GateAction.KILL,
                reason="Candidate exceeded the EUR 7 safety cap.",
                iteration=error.attempt_index,
            )
            return self._kill_outcome(candidate_id, safety_cap_event)
        except Exception as error:
            if self.trace_writer is not None:
                self.trace_writer.error(stage="workflow", error=error)
            raise

    def _checkpointed_step(
        self,
        *,
        candidate_id: str,
        attempt_index: int,
        stage_label: str,
        agent_label: str,
        execute: Callable[[], TStageModel],
        apply: Callable[[TStageModel], None],
        model_type: type[TStageModel],
        cost_of: Callable[[TStageModel], float],
        resume: Callable[[], TStageModel | None] | None = None,
        summary: Callable[[TStageModel], str] | None = None,
        attempt: int = 0,
        extra: str = "",
    ) -> TStageModel:
        resumed = resume() if resume is not None else None
        start_extra = extra
        if resumed is not None:
            start_extra = f"{extra} | resume stage state".strip(" |")
        self._stage_start(
            candidate_id,
            stage_label,
            agent_label,
            attempt=attempt,
            extra=start_extra,
        )
        if resumed is not None:
            result = model_type.model_validate(resumed.model_dump(mode="json"))
            self._stage_done(
                candidate_id,
                stage_label,
                agent_label,
                cost_eur=0.0,
                summary=(summary(result) if summary is not None else "resumed from stage state"),
            )
            return result

        result = execute()
        apply(result)
        self._stage_done(
            candidate_id,
            stage_label,
            agent_label,
            cost_eur=cost_of(result),
            summary=summary(result) if summary is not None else "",
        )
        return result

    def _resume_arena_discovery(self, candidate_id: str) -> ArenaDiscoveryFixture | None:
        scout_run = self.repository.get_stage_run(candidate_id, AgentName.ARENA_SCOUT, 0)
        evaluator_run = self.repository.get_stage_run(candidate_id, AgentName.ARENA_EVALUATOR, 0)
        raw_arenas = self.repository.load_arena_proposals(candidate_id)
        if scout_run is None or evaluator_run is None or not raw_arenas:
            return None
        evaluation = _hydrate_evaluation(
            ArenaEvaluation.model_validate(evaluator_run.payload),
            raw_arenas,
        )
        return ArenaDiscoveryFixture(
            scout_metrics=scout_run.metrics,
            evaluator_metrics=evaluator_run.metrics,
            search_result=ArenaSearchResult.model_validate(scout_run.payload),
            raw_arenas=raw_arenas,
            evaluation=evaluation,
        )

    def _resume_signal_mining(
        self,
        candidate_id: str,
        attempt_index: int,
        *,
        targeted_weakness: str | None = None,
    ) -> SignalMiningFixtureRun | None:
        stage_run = self.repository.get_stage_run(
            candidate_id, AgentName.SIGNAL_SCOUT, attempt_index
        )
        if stage_run is None:
            return None
        return SignalMiningFixtureRun(
            targeted_weakness=targeted_weakness,
            metrics=stage_run.metrics,
            result=SignalMiningResult.model_validate(stage_run.payload),
            raw_signals=self.repository.list_raw_signals(candidate_id),
        )

    def _resume_normalization(
        self,
        candidate_id: str,
        attempt_index: int,
    ) -> NormalizationFixtureRun | None:
        stage_run = self.repository.get_stage_run(candidate_id, AgentName.NORMALIZER, attempt_index)
        if stage_run is None:
            return None
        return NormalizationFixtureRun(
            metrics=stage_run.metrics,
            result=NormalizationResult.model_validate(stage_run.payload),
        )

    def _resume_landscape_research(self, candidate_id: str) -> LandscapeResearchFixture | None:
        stage_run = self.repository.get_stage_run(candidate_id, AgentName.LANDSCAPE_SCOUT, 0)
        if stage_run is None:
            return None
        return LandscapeResearchFixture(
            metrics=stage_run.metrics,
            result=LandscapeReport.model_validate(stage_run.payload),
            entries=self.repository.list_landscape_entries(candidate_id),
        )

    def _resume_scoring(self, candidate_id: str, attempt_index: int) -> ScoringFixtureRun | None:
        stage_run = self.repository.get_stage_run(candidate_id, AgentName.SCORER, attempt_index)
        if stage_run is None:
            return None
        return ScoringFixtureRun(
            metrics=stage_run.metrics,
            result=ScoringResult.model_validate(stage_run.payload),
        )

    def _resume_skeptic(self, candidate_id: str, attempt_index: int) -> SkepticFixtureRun | None:
        stage_run = self.repository.get_stage_run(candidate_id, AgentName.SKEPTIC, attempt_index)
        if stage_run is None:
            return None
        return SkepticFixtureRun(
            metrics=stage_run.metrics,
            result=SkepticReport.model_validate(stage_run.payload),
        )

    def _resume_wedge_design(
        self,
        candidate_id: str,
        attempt_index: int,
    ) -> WedgeDesignFixtureRun | None:
        stage_run = self.repository.get_stage_run(
            candidate_id, AgentName.WEDGE_DESIGNER, attempt_index
        )
        if stage_run is None:
            return None
        return WedgeDesignFixtureRun(
            metrics=stage_run.metrics,
            result=WedgeProposal.model_validate(stage_run.payload),
        )

    def _resume_wedge_critique(
        self,
        candidate_id: str,
        attempt_index: int,
    ) -> WedgeCritiqueFixtureRun | None:
        stage_run = self.repository.get_stage_run(
            candidate_id, AgentName.WEDGE_CRITIC, attempt_index
        )
        if stage_run is None:
            return None
        return WedgeCritiqueFixtureRun(
            metrics=stage_run.metrics,
            result=WedgeCritique.model_validate(stage_run.payload),
        )

    def _resume_channel_validation(
        self,
        candidate_id: str,
        attempt_index: int,
    ) -> ChannelValidationFixtureRun | None:
        stage_run = self.repository.get_stage_run(
            candidate_id,
            AgentName.BUYER_CHANNEL_VALIDATOR,
            attempt_index,
        )
        if stage_run is None:
            return None
        return ChannelValidationFixtureRun(
            metrics=stage_run.metrics,
            result=ChannelValidation.model_validate(stage_run.payload),
        )

    def _apply_arena_discovery(
        self,
        *,
        candidate_id: str,
        activities: PersistsToolState,
        run: ArenaDiscoveryFixture,
    ) -> None:
        if self.repository.get_stage_run(candidate_id, AgentName.ARENA_SCOUT, 0) is None:
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.ARENA_DISCOVERY,
                agent=AgentName.ARENA_SCOUT,
                attempt_index=0,
                payload=run.search_result,
                metrics=run.scout_metrics,
                context={
                    "candidate_id": candidate_id,
                    "stage": Stage.ARENA_DISCOVERY.value,
                    "output_contract": "ArenaSearchResult",
                },
            )
        existing_fingerprints = {
            arena.fingerprint() for arena in self.repository.load_arena_proposals(candidate_id)
        }
        for arena in run.raw_arenas:
            if activities.persists_tool_state and arena.fingerprint() in existing_fingerprints:
                continue
            self.tool_runtime.invoke(
                AgentName.ARENA_SCOUT,
                "create_arena_proposal",
                {"candidate_id": candidate_id, "arena": arena},
            )
            existing_fingerprints.add(arena.fingerprint())
        if self.repository.get_stage_run(candidate_id, AgentName.ARENA_EVALUATOR, 0) is None:
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.ARENA_DISCOVERY,
                agent=AgentName.ARENA_EVALUATOR,
                attempt_index=0,
                payload=run.evaluation,
                metrics=run.evaluator_metrics,
                context={
                    "candidate_id": candidate_id,
                    "stage": Stage.ARENA_DISCOVERY.value,
                    "output_contract": "ArenaEvaluation",
                },
            )
        selected_arena = run.evaluation.ranked_arenas[0]
        self.repository.update_candidate(candidate_id, current_stage=Stage.ARENA_DISCOVERY.value)
        if selected_arena.arena.id is not None:
            self.repository.set_selected_arena(candidate_id, selected_arena.arena.id)

    def _apply_signal_mining(
        self,
        *,
        candidate_id: str,
        run: SignalMiningFixtureRun,
        attempt_index: int,
        persists_tool_state: bool = False,
    ) -> None:
        if (
            self.repository.get_stage_run(candidate_id, AgentName.SIGNAL_SCOUT, attempt_index)
            is None
        ):
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.SIGNAL_MINING,
                agent=AgentName.SIGNAL_SCOUT,
                attempt_index=attempt_index,
                payload=run.result,
                metrics=run.metrics,
                context={
                    "candidate_id": candidate_id,
                    "stage": Stage.SIGNAL_MINING.value,
                    "output_contract": "SignalMiningResult",
                    "targeted_weakness": run.targeted_weakness,
                },
            )
        if not persists_tool_state:
            for signal in run.raw_signals:
                self.tool_runtime.invoke(
                    AgentName.SIGNAL_SCOUT,
                    "add_signal",
                    {"candidate_id": candidate_id, "signal": signal},
                )

    def _apply_normalization(
        self,
        *,
        candidate_id: str,
        run: NormalizationFixtureRun,
        attempt_index: int,
        targeted_weakness: str | None = None,
    ) -> None:
        if self.repository.get_stage_run(candidate_id, AgentName.NORMALIZER, attempt_index) is None:
            context = {
                "candidate_id": candidate_id,
                "stage": Stage.NORMALIZATION.value,
                "output_contract": "NormalizationResult",
            }
            if targeted_weakness is not None:
                context["targeted_weakness"] = targeted_weakness
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.NORMALIZATION,
                agent=AgentName.NORMALIZER,
                attempt_index=attempt_index,
                payload=run.result,
                metrics=run.metrics,
                context=context,
            )
        self.repository.replace_problem_units(candidate_id, run.result.problem_units)

    def _apply_landscape_research(
        self,
        *,
        candidate_id: str,
        activities: PersistsToolState,
        run: LandscapeResearchFixture,
    ) -> None:
        if self.repository.get_stage_run(candidate_id, AgentName.LANDSCAPE_SCOUT, 0) is None:
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.LANDSCAPE_SCORING_SKEPTIC,
                agent=AgentName.LANDSCAPE_SCOUT,
                attempt_index=0,
                payload=run.result,
                metrics=run.metrics,
                context={
                    "candidate_id": candidate_id,
                    "stage": Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                    "output_contract": "LandscapeReport",
                },
            )
        if not activities.persists_tool_state:
            self.repository.replace_landscape_entries(candidate_id, run.entries)

    def _apply_scoring(
        self,
        *,
        candidate_id: str,
        run: ScoringFixtureRun,
        attempt_index: int,
    ) -> None:
        if self.repository.get_stage_run(candidate_id, AgentName.SCORER, attempt_index) is None:
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.LANDSCAPE_SCORING_SKEPTIC,
                agent=AgentName.SCORER,
                attempt_index=attempt_index,
                payload=run.result,
                metrics=run.metrics,
                context={
                    "candidate_id": candidate_id,
                    "stage": Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                    "output_contract": "ScoringResult",
                },
            )
        top_candidate = run.result.top_candidate
        self.repository.update_candidate(
            candidate_id,
            current_stage=Stage.LANDSCAPE_SCORING_SKEPTIC.value,
            selected_problem_unit_id=top_candidate.problem_unit_id,
        )

    def _apply_skeptic(
        self,
        *,
        candidate_id: str,
        run: SkepticFixtureRun,
        attempt_index: int,
    ) -> None:
        if self.repository.get_stage_run(candidate_id, AgentName.SKEPTIC, attempt_index) is None:
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.LANDSCAPE_SCORING_SKEPTIC,
                agent=AgentName.SKEPTIC,
                attempt_index=attempt_index,
                payload=run.result,
                metrics=run.metrics,
                context={
                    "candidate_id": candidate_id,
                    "stage": Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                    "output_contract": "SkepticReport",
                },
            )

    def _apply_wedge_design(
        self,
        *,
        candidate_id: str,
        run: WedgeDesignFixtureRun,
        attempt_index: int,
    ) -> None:
        if (
            self.repository.get_stage_run(candidate_id, AgentName.WEDGE_DESIGNER, attempt_index)
            is None
        ):
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.WEDGE_DESIGN,
                agent=AgentName.WEDGE_DESIGNER,
                attempt_index=attempt_index,
                payload=run.result,
                metrics=run.metrics,
                context={
                    "candidate_id": candidate_id,
                    "stage": Stage.WEDGE_DESIGN.value,
                    "output_contract": "WedgeProposal",
                },
            )

    def _apply_wedge_critique(
        self,
        *,
        candidate_id: str,
        run: WedgeCritiqueFixtureRun,
        attempt_index: int,
    ) -> None:
        if (
            self.repository.get_stage_run(candidate_id, AgentName.WEDGE_CRITIC, attempt_index)
            is None
        ):
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.WEDGE_DESIGN,
                agent=AgentName.WEDGE_CRITIC,
                attempt_index=attempt_index,
                payload=run.result,
                metrics=run.metrics,
                context={
                    "candidate_id": candidate_id,
                    "stage": Stage.WEDGE_DESIGN.value,
                    "output_contract": "WedgeCritique",
                },
            )

    def _apply_channel_validation(
        self,
        *,
        candidate_id: str,
        run: ChannelValidationFixtureRun,
        attempt_index: int,
    ) -> None:
        if (
            self.repository.get_stage_run(
                candidate_id,
                AgentName.BUYER_CHANNEL_VALIDATOR,
                attempt_index,
            )
            is None
        ):
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.BUYER_CHANNEL,
                agent=AgentName.BUYER_CHANNEL_VALIDATOR,
                attempt_index=attempt_index,
                payload=run.result,
                metrics=run.metrics,
                context={
                    "candidate_id": candidate_id,
                    "stage": Stage.BUYER_CHANNEL.value,
                    "output_contract": "ChannelValidation",
                },
            )
        self.repository.replace_channel_plans(
            candidate_id,
            attempt_index,
            [plan.model_dump(mode="json") for plan in run.result.channels],
        )

    def _record_agent_stage_run(
        self,
        *,
        candidate_id: str,
        stage: Stage,
        agent: AgentName,
        attempt_index: int,
        payload: BaseModel,
        metrics: ActivityMetrics,
        context: Mapping[str, object],
    ) -> None:
        prompt = build_prompt(agent.value, context=dict(context), settings=self.settings)
        model_alias = resolve_agent_model(agent, self.settings)
        self.repository.store_stage_run(
            candidate_id=candidate_id,
            stage=stage,
            agent=agent,
            attempt_index=attempt_index,
            prompt_version=prompt.prompt_version,
            prompt_hash=prompt.prompt_hash,
            model_alias=model_alias,
            payload=payload.model_dump(mode="json"),
            metrics=metrics.model_dump(mode="json"),
        )
        self.repository.record_cost(
            CostRecord(
                candidate_id=candidate_id,
                stage=stage,
                agent=agent,
                model=model_alias,
                input_tokens=metrics.input_tokens,
                output_tokens=metrics.output_tokens,
                tool_calls=metrics.tool_calls,
                cost_eur=metrics.cost_eur,
                timestamp=datetime.now(UTC),
            )
        )
        if self._budget_mode(candidate_id) is BudgetMode.SAFETY_CAP:
            raise BudgetSafetyCapExceeded(stage=stage, attempt_index=attempt_index)

    def _append_decision(
        self,
        *,
        candidate_id: str,
        stage: Stage,
        action: GateAction,
        reason: str,
        iteration: int,
    ) -> DecisionEvent:
        event = DecisionEvent(
            candidate_id=candidate_id,
            stage=stage,
            action=action,
            reason=reason,
            iteration=iteration,
            metadata={"budget_mode": self._budget_mode(candidate_id).value},
        )
        return self.repository.append_decision_event(event)

    def _latest_decision_event(self, candidate_id: str) -> DecisionEvent | None:
        events = self.repository.list_decision_events(candidate_id)
        if not events:
            return None
        return events[-1]

    def _caution_flags(self, candidate_id: str) -> list[str]:
        return [
            event.reason
            for event in self.repository.list_decision_events(candidate_id)
            if event.action is GateAction.ADVANCE_WITH_CAUTION
        ]

    def _kill_outcome(self, candidate_id: str, event: DecisionEvent) -> WorkflowOutcome:
        self.repository.update_candidate(candidate_id, current_stage=event.stage.value)
        self.repository.mark_candidate_killed(candidate_id)
        candidate = self.repository.get_candidate(candidate_id)
        total_cost = candidate.total_cost_eur if candidate else 0.0
        self._outcome(candidate_id, "killed", total_cost_eur=total_cost)
        return WorkflowOutcome(candidate_id=candidate_id, status="killed", final_decision=event)

    def _store_learnings(
        self,
        candidate_id: str,
        entries: list[Any],
    ) -> None:
        """Persist learnings, converting LearningEntry dataclasses to dicts."""
        self.repository.store_learnings(
            candidate_id,
            [
                {"insight": e.insight, "tags": e.tags, "candidate_id": e.candidate_id}
                for e in entries
            ],
        )

    def _build_dossier(
        self,
        *,
        candidate_id: str,
        arena: EvaluatedArena,
        problem_unit: ProblemUnit,
        scoring: ScoredCandidate,
        skeptic: SkepticReport | None,
        selected_wedge: WedgeHypothesis,
        caution_flags: list[str],
        channel_validation: ChannelValidation,
    ) -> CandidateDossier:
        if skeptic is None:
            raise ValueError("Cannot build a dossier without a skeptic report.")
        evidence = self.repository.get_raw_signals_by_ids(candidate_id, problem_unit.evidence_ids)
        gate_history = self.repository.list_decision_events(candidate_id)
        return CandidateDossier(
            candidate_id=candidate_id,
            arena=arena,
            problem_unit=problem_unit,
            top_evidence=evidence,
            scoring=scoring,
            skeptic=skeptic,
            selected_wedge=selected_wedge,
            channel_validation=channel_validation,
            gate_history=gate_history,
            caution_flags=caution_flags,
        )

    def _budget_mode(self, candidate_id: str) -> BudgetMode:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Unknown candidate: {candidate_id}")
        return candidate_budget_mode(candidate.total_cost_eur)

    def _optional_loop_limit(self, candidate_id: str) -> int:
        if self._budget_mode(candidate_id) is BudgetMode.NORMAL:
            return 2
        return 0

    def _optional_retry_limit(self, candidate_id: str) -> int:
        if self._budget_mode(candidate_id) is BudgetMode.NORMAL:
            return 1
        return 0

    def _stage_start(
        self,
        candidate_id: str,
        stage: str,
        agent: str,
        *,
        attempt: int = 0,
        extra: str = "",
    ) -> None:
        flow_stage_start(candidate_id, stage, agent, attempt=attempt, extra=extra)
        if self.trace_writer is not None:
            self.trace_writer.stage_start(stage=stage, agent=agent, attempt=attempt, extra=extra)

    def _stage_done(
        self,
        candidate_id: str,
        stage: str,
        agent: str,
        *,
        cost_eur: float = 0.0,
        summary: str = "",
    ) -> None:
        flow_stage_done(candidate_id, stage, agent, cost_eur=cost_eur, summary=summary)
        if self.trace_writer is not None:
            self.trace_writer.stage_done(
                stage=stage,
                agent=agent,
                cost_eur=cost_eur,
                summary=summary,
            )

    def _gate_decision(
        self,
        candidate_id: str,
        gate: str,
        action: str,
        reason: str,
        *,
        score: int | None = None,
        budget_mode: str = "normal",
    ) -> None:
        flow_gate_decision(
            candidate_id,
            gate,
            action,
            reason,
            score=score,
            budget_mode=budget_mode,
        )
        if self.trace_writer is not None:
            self.trace_writer.gate_decision(
                gate=gate,
                action=action,
                reason=reason,
                score=score,
                budget_mode=budget_mode,
            )

    def _budget_warning(self, candidate_id: str, budget_mode: str, total_cost_eur: float) -> None:
        flow_budget_warning(candidate_id, budget_mode, total_cost_eur)
        if self.trace_writer is not None:
            self.trace_writer.budget_warning(
                budget_mode=budget_mode,
                total_cost_eur=total_cost_eur,
            )

    def _outcome(self, candidate_id: str, status: str, *, total_cost_eur: float) -> None:
        flow_outcome(candidate_id, status, total_cost_eur=total_cost_eur)
        if self.trace_writer is not None:
            self.trace_writer.outcome(status=status, total_cost_eur=total_cost_eur)


class BudgetSafetyCapExceeded(RuntimeError):
    def __init__(self, stage: Stage, attempt_index: int):
        super().__init__("Candidate exceeded the safety cap.")
        self.stage = stage
        self.attempt_index = attempt_index


def _hydrate_evaluation(
    evaluation: ArenaEvaluation,
    raw_arenas: list[RawArena],
) -> ArenaEvaluation:
    by_fingerprint = {arena.fingerprint(): arena for arena in raw_arenas}
    ranked: list[EvaluatedArena] = []
    for item in evaluation.ranked_arenas:
        arena = item.arena
        if arena.id is None:
            stored = by_fingerprint.get(arena.fingerprint())
            if stored is not None:
                arena = stored
        ranked.append(item.model_copy(update={"arena": arena}))
    return evaluation.model_copy(update={"ranked_arenas": ranked})
