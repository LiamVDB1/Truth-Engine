from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
from truth_engine.contracts.fixtures import SignalMiningFixtureRun
from truth_engine.contracts.models import CostRecord, ProblemUnit
from truth_engine.contracts.stages import (
    ActivityMetrics,
    CandidateDossier,
    ChannelValidation,
    DecisionEvent,
    EvaluatedArena,
    ScoredCandidate,
    SkepticReport,
    WedgeHypothesis,
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
        if self.repository.get_candidate(candidate_id) is None:
            self.repository.create_candidate(candidate_id=candidate_id, status="running")
        try:
            caution_flags: list[str] = []
            self._stage_start(candidate_id, "Arena Discovery", "arena_scout")
            selected_arena = self._run_arena_discovery(candidate_id, activities)

            self._stage_start(candidate_id, "Signal Mining", "signal_scout")
            signal_run = activities.signal_mining()
            self._run_signal_mining(
                candidate_id,
                signal_run,
                attempt_index=0,
                persists_tool_state=activities.persists_tool_state,
            )
            self._stage_done(
                candidate_id,
                "Signal Mining",
                "signal_scout",
                cost_eur=signal_run.metrics.cost_eur,
            )
            self._stage_start(candidate_id, "Normalization", "normalizer")
            normalization_run = activities.normalization()
            problem_units = normalization_run.result.problem_units
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.NORMALIZATION,
                agent=AgentName.NORMALIZER,
                attempt_index=0,
                payload=normalization_run.result,
                metrics=normalization_run.metrics,
                context={
                    "candidate_id": candidate_id,
                    "stage": Stage.NORMALIZATION.value,
                    "output_contract": "NormalizationResult",
                },
            )
            self.repository.replace_problem_units(candidate_id, problem_units)
            self._stage_done(
                candidate_id,
                "Normalization",
                "normalizer",
                cost_eur=normalization_run.metrics.cost_eur,
                summary=f"{len(problem_units)} problem units",
            )

            self._stage_start(candidate_id, "Landscape", "landscape_scout")
            landscape = activities.landscape_research()
            self._record_agent_stage_run(
                candidate_id=candidate_id,
                stage=Stage.LANDSCAPE_SCORING_SKEPTIC,
                agent=AgentName.LANDSCAPE_SCOUT,
                attempt_index=0,
                payload=landscape.result,
                metrics=landscape.metrics,
                context={
                    "candidate_id": candidate_id,
                    "stage": Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                    "output_contract": "LandscapeReport",
                },
            )
            if not activities.persists_tool_state:
                self.repository.replace_landscape_entries(candidate_id, landscape.entries)
            self._stage_done(
                candidate_id,
                "Landscape",
                "landscape_scout",
                cost_eur=landscape.metrics.cost_eur,
            )

            selected_problem_unit: ProblemUnit | None = None
            scoring_result: ScoredCandidate | None = None
            skeptic_result: SkepticReport | None = None
            gate_a_iteration = 0
            while True:
                self._stage_start(
                    candidate_id,
                    "Scoring",
                    "scorer",
                    attempt=gate_a_iteration,
                )
                scoring_run = activities.scoring()
                self._record_agent_stage_run(
                    candidate_id=candidate_id,
                    stage=Stage.LANDSCAPE_SCORING_SKEPTIC,
                    agent=AgentName.SCORER,
                    attempt_index=gate_a_iteration,
                    payload=scoring_run.result,
                    metrics=scoring_run.metrics,
                    context={
                        "candidate_id": candidate_id,
                        "stage": Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                        "output_contract": "ScoringResult",
                    },
                )
                scoring_result = scoring_run.result.top_candidate
                self.repository.update_candidate(
                    candidate_id,
                    current_stage=Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                    selected_problem_unit_id=scoring_result.problem_unit_id,
                )
                selected_problem_unit = self.repository.get_problem_unit(
                    candidate_id, scoring_result.problem_unit_id
                )
                if selected_problem_unit is None:
                    raise ValueError(f"Unknown problem unit: {scoring_result.problem_unit_id}")
                self._stage_done(
                    candidate_id,
                    "Scoring",
                    "scorer",
                    cost_eur=scoring_run.metrics.cost_eur,
                    summary=f"score={scoring_result.total_score}",
                )

                self._stage_start(
                    candidate_id,
                    "Skeptic",
                    "skeptic",
                    attempt=gate_a_iteration,
                )
                skeptic_run = activities.skeptic()
                self._record_agent_stage_run(
                    candidate_id=candidate_id,
                    stage=Stage.LANDSCAPE_SCORING_SKEPTIC,
                    agent=AgentName.SKEPTIC,
                    attempt_index=gate_a_iteration,
                    payload=skeptic_run.result,
                    metrics=skeptic_run.metrics,
                    context={
                        "candidate_id": candidate_id,
                        "stage": Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                        "output_contract": "SkepticReport",
                    },
                )
                skeptic_result = skeptic_run.result
                self._stage_done(
                    candidate_id,
                    "Skeptic",
                    "skeptic",
                    cost_eur=skeptic_run.metrics.cost_eur,
                    summary=f"rec={skeptic_result.recommendation}",
                )

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
                    gate_a_decision.action.value,
                    gate_a_decision.reason,
                    score=scoring_result.total_score,
                    budget_mode=self._budget_mode(candidate_id).value,
                )

                if gate_a_decision.action is GateAction.INVESTIGATE:
                    self._stage_start(
                        candidate_id,
                        "Targeted Mining",
                        "signal_scout",
                        extra=f"weakness: {skeptic_result.primary_weakness}",
                    )
                    targeted_signal_run = activities.signal_mining(skeptic_result.primary_weakness)
                    self._run_signal_mining(
                        candidate_id,
                        targeted_signal_run,
                        attempt_index=gate_a_iteration + 1,
                        persists_tool_state=activities.persists_tool_state,
                    )
                    targeted_normalization = activities.normalization()
                    self._record_agent_stage_run(
                        candidate_id=candidate_id,
                        stage=Stage.NORMALIZATION,
                        agent=AgentName.NORMALIZER,
                        attempt_index=gate_a_iteration + 1,
                        payload=targeted_normalization.result,
                        metrics=targeted_normalization.metrics,
                        context={
                            "candidate_id": candidate_id,
                            "stage": Stage.NORMALIZATION.value,
                            "output_contract": "NormalizationResult",
                            "targeted_weakness": skeptic_result.primary_weakness,
                        },
                    )
                    self.repository.replace_problem_units(
                        candidate_id, targeted_normalization.result.problem_units
                    )
                    gate_a_iteration += 1
                    continue

                if gate_a_decision.action is GateAction.KILL:
                    self._store_learnings(
                        candidate_id,
                        extract_kill_learnings(
                            candidate_id,
                            gate_a_decision.reason,
                            arena=selected_arena,
                            scoring=scoring_result,
                            skeptic=skeptic_result,
                        ),
                    )
                    return self._kill_outcome(candidate_id, gate_a_event)

                if gate_a_decision.action is GateAction.ADVANCE_WITH_CAUTION:
                    caution_flags.append(gate_a_decision.reason)
                break

            wedge_iteration = 0
            selected_wedge: WedgeHypothesis | None = None
            while True:
                self._stage_start(
                    candidate_id,
                    "Wedge Design",
                    "wedge_designer",
                    attempt=wedge_iteration,
                )
                wedge_design_run = activities.wedge_design()
                self._record_agent_stage_run(
                    candidate_id=candidate_id,
                    stage=Stage.WEDGE_DESIGN,
                    agent=AgentName.WEDGE_DESIGNER,
                    attempt_index=wedge_iteration,
                    payload=wedge_design_run.result,
                    metrics=wedge_design_run.metrics,
                    context={
                        "candidate_id": candidate_id,
                        "stage": Stage.WEDGE_DESIGN.value,
                        "output_contract": "WedgeProposal",
                    },
                )
                self._stage_done(
                    candidate_id,
                    "Wedge Design",
                    "wedge_designer",
                    cost_eur=wedge_design_run.metrics.cost_eur,
                    summary=f"{len(wedge_design_run.result.wedges)} wedges",
                )

                self._stage_start(
                    candidate_id,
                    "Wedge Critique",
                    "wedge_critic",
                    attempt=wedge_iteration,
                )
                wedge_critique_run = activities.wedge_critique()
                self._record_agent_stage_run(
                    candidate_id=candidate_id,
                    stage=Stage.WEDGE_DESIGN,
                    agent=AgentName.WEDGE_CRITIC,
                    attempt_index=wedge_iteration,
                    payload=wedge_critique_run.result,
                    metrics=wedge_critique_run.metrics,
                    context={
                        "candidate_id": candidate_id,
                        "stage": Stage.WEDGE_DESIGN.value,
                        "output_contract": "WedgeCritique",
                    },
                )
                self._stage_done(
                    candidate_id,
                    "Wedge Critique",
                    "wedge_critic",
                    cost_eur=wedge_critique_run.metrics.cost_eur,
                    summary=f"best={wedge_critique_run.result.best_wedge_index}",
                )

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
                    wedge_decision.action.value,
                    wedge_decision.reason,
                    budget_mode=self._budget_mode(candidate_id).value,
                )

                if wedge_decision.action is GateAction.KILL:
                    return self._kill_outcome(candidate_id, wedge_event)

                if wedge_decision.action is GateAction.ADVANCE:
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
                self._stage_start(
                    candidate_id,
                    "Buyer/Channel",
                    "buyer_channel_validator",
                    attempt=gate_b_retry_index,
                )
                channel_validation_run = activities.channel_validation()
                self._record_agent_stage_run(
                    candidate_id=candidate_id,
                    stage=Stage.BUYER_CHANNEL,
                    agent=AgentName.BUYER_CHANNEL_VALIDATOR,
                    attempt_index=gate_b_retry_index,
                    payload=channel_validation_run.result,
                    metrics=channel_validation_run.metrics,
                    context={
                        "candidate_id": candidate_id,
                        "stage": Stage.BUYER_CHANNEL.value,
                        "output_contract": "ChannelValidation",
                    },
                )
                self._stage_done(
                    candidate_id,
                    "Buyer/Channel",
                    "buyer_channel_validator",
                    cost_eur=channel_validation_run.metrics.cost_eur,
                    summary=(
                        f"verdict={channel_validation_run.result.verdict.value} "
                        f"leads={channel_validation_run.result.total_reachable_leads}"
                    ),
                )
                self.repository.replace_channel_plans(
                    candidate_id,
                    gate_b_retry_index,
                    [
                        plan.model_dump(mode="json")
                        for plan in channel_validation_run.result.channels
                    ],
                )

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
                    gate_b_decision.action.value,
                    gate_b_decision.reason,
                    budget_mode=self._budget_mode(candidate_id).value,
                )
                if gate_b_decision.action is GateAction.RETRY:
                    gate_b_retry_index += 1
                    continue
                if gate_b_decision.action is GateAction.KILL:
                    return self._kill_outcome(candidate_id, gate_b_event)

                dossier = self._build_dossier(
                    candidate_id=candidate_id,
                    arena=selected_arena,
                    problem_unit=selected_problem_unit,
                    scoring=scoring_result,
                    skeptic=skeptic_result,
                    selected_wedge=selected_wedge,
                    caution_flags=caution_flags,
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

    def _run_arena_discovery(self, candidate_id: str, activities: ActivityBundle) -> EvaluatedArena:
        arena_discovery = activities.arena_discovery()
        self._record_agent_stage_run(
            candidate_id=candidate_id,
            stage=Stage.ARENA_DISCOVERY,
            agent=AgentName.ARENA_SCOUT,
            attempt_index=0,
            payload=arena_discovery.search_result,
            metrics=arena_discovery.scout_metrics,
            context={
                "candidate_id": candidate_id,
                "stage": Stage.ARENA_DISCOVERY.value,
                "output_contract": "ArenaSearchResult",
            },
        )
        if not activities.persists_tool_state:
            for arena in arena_discovery.raw_arenas:
                self.tool_runtime.invoke(
                    AgentName.ARENA_SCOUT,
                    "create_arena_proposal",
                    {"candidate_id": candidate_id, "arena": arena},
                )

        self._record_agent_stage_run(
            candidate_id=candidate_id,
            stage=Stage.ARENA_DISCOVERY,
            agent=AgentName.ARENA_EVALUATOR,
            attempt_index=0,
            payload=arena_discovery.evaluation,
            metrics=arena_discovery.evaluator_metrics,
            context={
                "candidate_id": candidate_id,
                "stage": Stage.ARENA_DISCOVERY.value,
                "output_contract": "ArenaEvaluation",
            },
        )
        selected_arena = arena_discovery.evaluation.ranked_arenas[0]
        self.repository.update_candidate(candidate_id, current_stage=Stage.ARENA_DISCOVERY.value)
        if selected_arena.arena.id is not None:
            self.repository.set_selected_arena(candidate_id, selected_arena.arena.id)
        return selected_arena

    def _run_signal_mining(
        self,
        candidate_id: str,
        run: SignalMiningFixtureRun,
        attempt_index: int,
        *,
        persists_tool_state: bool = False,
    ) -> None:
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

    def _record_agent_stage_run(
        self,
        *,
        candidate_id: str,
        stage: Stage,
        agent: AgentName,
        attempt_index: int,
        payload: BaseModel,
        metrics: ActivityMetrics,
        context: dict[str, object],
    ) -> None:
        prompt = build_prompt(agent.value, context=context, settings=self.settings)
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
