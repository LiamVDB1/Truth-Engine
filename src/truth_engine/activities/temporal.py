from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from temporalio import activity

from truth_engine.activities.live import LiveActivityBundle
from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.adapters.llm.litellm_runner import LiteLLMAgentRunner
from truth_engine.adapters.reddit.praw_client import RedditSearchClient
from truth_engine.adapters.scraping.web import WebFetchClient
from truth_engine.adapters.search.serper import SerperSearchClient
from truth_engine.config.settings import Settings
from truth_engine.contracts.fixtures import (
    ArenaDiscoveryFixture,
    ChannelValidationFixtureRun,
    FixtureScenario,
    LandscapeResearchFixture,
    NormalizationFixtureRun,
    ScoringFixtureRun,
    SignalMiningFixtureRun,
    SkepticFixtureRun,
    WedgeCritiqueFixtureRun,
    WedgeDesignFixtureRun,
)
from truth_engine.contracts.live import LiveRunRequest
from truth_engine.contracts.stages import (
    ChannelValidation,
    DecisionEvent,
    EvaluatedArena,
    ScoringResult,
    SkepticReport,
    WedgeHypothesis,
    WorkflowOutcome,
)
from truth_engine.contracts.temporal import (
    DecisionActivityInput,
    KillActivityInput,
    StageExecutionInput,
    StageExecutionResult,
    SuccessActivityInput,
    TruthEngineRunInput,
    TruthEngineRunResult,
)
from truth_engine.domain.enums import BudgetMode, GateAction, Stage
from truth_engine.reporting.dossier import write_dossier_artifacts
from truth_engine.services.budgets import candidate_budget_mode
from truth_engine.services.learnings import extract_kill_learnings, extract_pass_learnings
from truth_engine.services.run_trace import RunTraceWriter
from truth_engine.tools.runtime import RepositoryToolRuntime
from truth_engine.workflows.candidate import BudgetSafetyCapExceeded, CandidateWorkflowRunner


@dataclass
class _PersistenceContext:
    persists_tool_state: bool


class TemporalCandidateActivities:
    def activity_callables(self) -> list[Any]:
        return [
            self.ensure_candidate,
            self.current_budget_mode,
            self.arena_discovery,
            self.signal_mining,
            self.normalization,
            self.landscape_research,
            self.scoring,
            self.skeptic,
            self.wedge_design,
            self.wedge_critique,
            self.channel_validation,
            self.record_decision,
            self.record_budget_warning,
            self.finalize_kill,
            self.finalize_success,
        ]

    @activity.defn(name="truth_engine.ensure_candidate")
    def ensure_candidate(self, run_input: TruthEngineRunInput) -> TruthEngineRunResult | None:
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        settings = self._settings_for(run_input)
        trace_writer = self._trace_writer_for(run_input)
        candidate = repository.get_candidate(run_input.candidate_id)
        request_payload = run_input.request_payload

        if candidate is None:
            repository.create_candidate(
                candidate_id=run_input.candidate_id,
                status="running",
                request_payload=request_payload,
            )
            return None

        if candidate.request_payload is None and request_payload is not None:
            repository.update_candidate(run_input.candidate_id, request_payload=request_payload)

        runner = CandidateWorkflowRunner(
            repository=repository,
            settings=settings,
            trace_writer=trace_writer,
        )
        existing = self._existing_result(repository, run_input, runner)
        if existing is not None:
            return existing
        return None

    @activity.defn(name="truth_engine.current_budget_mode")
    def current_budget_mode(self, run_input: TruthEngineRunInput) -> str:
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        candidate = repository.get_candidate(run_input.candidate_id)
        total_cost = candidate.total_cost_eur if candidate is not None else 0.0
        return candidate_budget_mode(total_cost).value

    @activity.defn(name="truth_engine.arena_discovery")
    def arena_discovery(self, stage_input: StageExecutionInput) -> StageExecutionResult:
        run_input = stage_input.run_input
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        settings = self._settings_for(run_input)
        runner = self._runner_for(run_input, repository, settings)
        scenario = self._fixture_scenario(run_input)
        bundle = self._live_bundle(run_input, repository, settings, runner.trace_writer)
        context = _PersistenceContext(persists_tool_state=run_input.mode == "live")

        def execute() -> ArenaDiscoveryFixture:
            if scenario is not None:
                return scenario.arena_discovery
            assert bundle is not None
            return bundle.arena_discovery()

        try:
            result = runner._checkpointed_step(
                candidate_id=run_input.candidate_id,
                attempt_index=0,
                stage_label="Arena Discovery",
                agent_label="arena_scout",
                execute=execute,
                apply=lambda run: runner._apply_arena_discovery(
                    candidate_id=run_input.candidate_id,
                    activities=context,
                    run=run,
                ),
                model_type=ArenaDiscoveryFixture,
                cost_of=lambda run: run.scout_metrics.cost_eur + run.evaluator_metrics.cost_eur,
                resume=lambda: runner._resume_arena_discovery(run_input.candidate_id),
            )
        except BudgetSafetyCapExceeded as error:
            return self._safety_cap_result(error)
        return StageExecutionResult(ok=True, payload=result.model_dump(mode="json"))

    @activity.defn(name="truth_engine.signal_mining")
    def signal_mining(self, stage_input: StageExecutionInput) -> StageExecutionResult:
        run_input = stage_input.run_input
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        settings = self._settings_for(run_input)
        runner = self._runner_for(run_input, repository, settings)
        scenario = self._fixture_scenario(run_input)
        bundle = self._live_bundle(run_input, repository, settings, runner.trace_writer)

        def execute() -> SignalMiningFixtureRun:
            if scenario is not None:
                run = self._take(
                    scenario.signal_mining_runs,
                    stage_input.attempt_index,
                    "signal_mining",
                )
                if run.targeted_weakness != stage_input.targeted_weakness:
                    raise ValueError(
                        "Signal fixture weakness mismatch: "
                        f"expected {run.targeted_weakness!r}, got {stage_input.targeted_weakness!r}"
                    )
                return run
            assert bundle is not None
            return bundle.signal_mining(stage_input.targeted_weakness)

        try:
            result = runner._checkpointed_step(
                candidate_id=run_input.candidate_id,
                attempt_index=stage_input.attempt_index,
                stage_label="Targeted Mining" if stage_input.targeted_weakness else "Signal Mining",
                agent_label="signal_scout",
                execute=execute,
                apply=lambda run: runner._apply_signal_mining(
                    candidate_id=run_input.candidate_id,
                    run=run,
                    attempt_index=stage_input.attempt_index,
                    persists_tool_state=run_input.mode == "live",
                ),
                model_type=SignalMiningFixtureRun,
                cost_of=lambda run: run.metrics.cost_eur,
                extra=(
                    f"weakness: {stage_input.targeted_weakness}"
                    if stage_input.targeted_weakness
                    else ""
                ),
                resume=lambda: runner._resume_signal_mining(
                    run_input.candidate_id,
                    stage_input.attempt_index,
                    targeted_weakness=stage_input.targeted_weakness,
                ),
            )
        except BudgetSafetyCapExceeded as error:
            return self._safety_cap_result(error)
        return StageExecutionResult(ok=True, payload=result.model_dump(mode="json"))

    @activity.defn(name="truth_engine.normalization")
    def normalization(self, stage_input: StageExecutionInput) -> StageExecutionResult:
        run_input = stage_input.run_input
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        settings = self._settings_for(run_input)
        runner = self._runner_for(run_input, repository, settings)
        scenario = self._fixture_scenario(run_input)
        bundle = self._live_bundle(run_input, repository, settings, runner.trace_writer)

        def execute() -> NormalizationFixtureRun:
            if scenario is not None:
                return self._take(
                    scenario.normalization_runs,
                    stage_input.attempt_index,
                    "normalization",
                )
            assert bundle is not None
            return bundle.normalization()

        try:
            result = runner._checkpointed_step(
                candidate_id=run_input.candidate_id,
                attempt_index=stage_input.attempt_index,
                stage_label="Normalization",
                agent_label="normalizer",
                execute=execute,
                apply=lambda run: runner._apply_normalization(
                    candidate_id=run_input.candidate_id,
                    run=run,
                    attempt_index=stage_input.attempt_index,
                    targeted_weakness=stage_input.targeted_weakness,
                ),
                model_type=NormalizationFixtureRun,
                cost_of=lambda run: run.metrics.cost_eur,
                summary=lambda run: f"{len(run.result.problem_units)} problem units",
                resume=lambda: runner._resume_normalization(
                    run_input.candidate_id,
                    stage_input.attempt_index,
                ),
            )
        except BudgetSafetyCapExceeded as error:
            return self._safety_cap_result(error)
        return StageExecutionResult(ok=True, payload=result.model_dump(mode="json"))

    @activity.defn(name="truth_engine.landscape_research")
    def landscape_research(self, stage_input: StageExecutionInput) -> StageExecutionResult:
        run_input = stage_input.run_input
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        settings = self._settings_for(run_input)
        runner = self._runner_for(run_input, repository, settings)
        scenario = self._fixture_scenario(run_input)
        bundle = self._live_bundle(run_input, repository, settings, runner.trace_writer)
        context = _PersistenceContext(persists_tool_state=run_input.mode == "live")

        def execute() -> LandscapeResearchFixture:
            if scenario is not None:
                return scenario.landscape_research
            assert bundle is not None
            return bundle.landscape_research()

        try:
            result = runner._checkpointed_step(
                candidate_id=run_input.candidate_id,
                attempt_index=0,
                stage_label="Landscape",
                agent_label="landscape_scout",
                execute=execute,
                apply=lambda run: runner._apply_landscape_research(
                    candidate_id=run_input.candidate_id,
                    activities=context,
                    run=run,
                ),
                model_type=LandscapeResearchFixture,
                cost_of=lambda run: run.metrics.cost_eur,
                resume=lambda: runner._resume_landscape_research(run_input.candidate_id),
            )
        except BudgetSafetyCapExceeded as error:
            return self._safety_cap_result(error)
        return StageExecutionResult(ok=True, payload=result.model_dump(mode="json"))

    @activity.defn(name="truth_engine.scoring")
    def scoring(self, stage_input: StageExecutionInput) -> StageExecutionResult:
        run_input = stage_input.run_input
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        settings = self._settings_for(run_input)
        runner = self._runner_for(run_input, repository, settings)
        scenario = self._fixture_scenario(run_input)
        bundle = self._live_bundle(run_input, repository, settings, runner.trace_writer)

        def execute() -> ScoringFixtureRun:
            if scenario is not None:
                return self._take(scenario.scoring_runs, stage_input.attempt_index, "scoring")
            assert bundle is not None
            return bundle.scoring()

        try:
            result = runner._checkpointed_step(
                candidate_id=run_input.candidate_id,
                attempt_index=stage_input.attempt_index,
                stage_label="Scoring",
                agent_label="scorer",
                execute=execute,
                apply=lambda run: runner._apply_scoring(
                    candidate_id=run_input.candidate_id,
                    run=run,
                    attempt_index=stage_input.attempt_index,
                ),
                model_type=ScoringFixtureRun,
                cost_of=lambda run: run.metrics.cost_eur,
                summary=lambda run: f"score={run.result.top_candidate.total_score}",
                attempt=stage_input.attempt_index,
                resume=lambda: runner._resume_scoring(
                    run_input.candidate_id,
                    stage_input.attempt_index,
                ),
            )
        except BudgetSafetyCapExceeded as error:
            return self._safety_cap_result(error)
        return StageExecutionResult(ok=True, payload=result.model_dump(mode="json"))

    @activity.defn(name="truth_engine.skeptic")
    def skeptic(self, stage_input: StageExecutionInput) -> StageExecutionResult:
        run_input = stage_input.run_input
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        settings = self._settings_for(run_input)
        runner = self._runner_for(run_input, repository, settings)
        scenario = self._fixture_scenario(run_input)
        bundle = self._live_bundle(run_input, repository, settings, runner.trace_writer)

        def execute() -> SkepticFixtureRun:
            if scenario is not None:
                return self._take(scenario.skeptic_runs, stage_input.attempt_index, "skeptic")
            assert bundle is not None
            return bundle.skeptic()

        try:
            result = runner._checkpointed_step(
                candidate_id=run_input.candidate_id,
                attempt_index=stage_input.attempt_index,
                stage_label="Skeptic",
                agent_label="skeptic",
                execute=execute,
                apply=lambda run: runner._apply_skeptic(
                    candidate_id=run_input.candidate_id,
                    run=run,
                    attempt_index=stage_input.attempt_index,
                ),
                model_type=SkepticFixtureRun,
                cost_of=lambda run: run.metrics.cost_eur,
                summary=lambda run: f"rec={run.result.recommendation}",
                attempt=stage_input.attempt_index,
                resume=lambda: runner._resume_skeptic(
                    run_input.candidate_id,
                    stage_input.attempt_index,
                ),
            )
        except BudgetSafetyCapExceeded as error:
            return self._safety_cap_result(error)
        return StageExecutionResult(ok=True, payload=result.model_dump(mode="json"))

    @activity.defn(name="truth_engine.wedge_design")
    def wedge_design(self, stage_input: StageExecutionInput) -> StageExecutionResult:
        run_input = stage_input.run_input
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        settings = self._settings_for(run_input)
        runner = self._runner_for(run_input, repository, settings)
        scenario = self._fixture_scenario(run_input)
        bundle = self._live_bundle(run_input, repository, settings, runner.trace_writer)

        def execute() -> WedgeDesignFixtureRun:
            if scenario is not None:
                return self._take(
                    scenario.wedge_design_runs,
                    stage_input.attempt_index,
                    "wedge_design",
                )
            assert bundle is not None
            return bundle.wedge_design()

        try:
            result = runner._checkpointed_step(
                candidate_id=run_input.candidate_id,
                attempt_index=stage_input.attempt_index,
                stage_label="Wedge Design",
                agent_label="wedge_designer",
                execute=execute,
                apply=lambda run: runner._apply_wedge_design(
                    candidate_id=run_input.candidate_id,
                    run=run,
                    attempt_index=stage_input.attempt_index,
                ),
                model_type=WedgeDesignFixtureRun,
                cost_of=lambda run: run.metrics.cost_eur,
                summary=lambda run: f"{len(run.result.wedges)} wedges",
                attempt=stage_input.attempt_index,
                resume=lambda: runner._resume_wedge_design(
                    run_input.candidate_id,
                    stage_input.attempt_index,
                ),
            )
        except BudgetSafetyCapExceeded as error:
            return self._safety_cap_result(error)
        return StageExecutionResult(ok=True, payload=result.model_dump(mode="json"))

    @activity.defn(name="truth_engine.wedge_critique")
    def wedge_critique(self, stage_input: StageExecutionInput) -> StageExecutionResult:
        run_input = stage_input.run_input
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        settings = self._settings_for(run_input)
        runner = self._runner_for(run_input, repository, settings)
        scenario = self._fixture_scenario(run_input)
        bundle = self._live_bundle(run_input, repository, settings, runner.trace_writer)

        def execute() -> WedgeCritiqueFixtureRun:
            if scenario is not None:
                return self._take(
                    scenario.wedge_critique_runs,
                    stage_input.attempt_index,
                    "wedge_critique",
                )
            assert bundle is not None
            return bundle.wedge_critique()

        try:
            result = runner._checkpointed_step(
                candidate_id=run_input.candidate_id,
                attempt_index=stage_input.attempt_index,
                stage_label="Wedge Critique",
                agent_label="wedge_critic",
                execute=execute,
                apply=lambda run: runner._apply_wedge_critique(
                    candidate_id=run_input.candidate_id,
                    run=run,
                    attempt_index=stage_input.attempt_index,
                ),
                model_type=WedgeCritiqueFixtureRun,
                cost_of=lambda run: run.metrics.cost_eur,
                summary=lambda run: f"best={run.result.best_wedge_index}",
                attempt=stage_input.attempt_index,
                resume=lambda: runner._resume_wedge_critique(
                    run_input.candidate_id,
                    stage_input.attempt_index,
                ),
            )
        except BudgetSafetyCapExceeded as error:
            return self._safety_cap_result(error)
        return StageExecutionResult(ok=True, payload=result.model_dump(mode="json"))

    @activity.defn(name="truth_engine.channel_validation")
    def channel_validation(self, stage_input: StageExecutionInput) -> StageExecutionResult:
        run_input = stage_input.run_input
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        settings = self._settings_for(run_input)
        runner = self._runner_for(run_input, repository, settings)
        scenario = self._fixture_scenario(run_input)
        bundle = self._live_bundle(run_input, repository, settings, runner.trace_writer)

        def execute() -> ChannelValidationFixtureRun:
            if scenario is not None:
                return self._take(
                    scenario.channel_validation_runs,
                    stage_input.attempt_index,
                    "channel_validation",
                )
            assert bundle is not None
            return bundle.channel_validation()

        try:
            result = runner._checkpointed_step(
                candidate_id=run_input.candidate_id,
                attempt_index=stage_input.attempt_index,
                stage_label="Buyer/Channel",
                agent_label="buyer_channel_validator",
                execute=execute,
                apply=lambda run: runner._apply_channel_validation(
                    candidate_id=run_input.candidate_id,
                    run=run,
                    attempt_index=stage_input.attempt_index,
                ),
                model_type=ChannelValidationFixtureRun,
                cost_of=lambda run: run.metrics.cost_eur,
                summary=lambda run: (
                    f"verdict={run.result.verdict.value} leads={run.result.total_reachable_leads}"
                ),
                attempt=stage_input.attempt_index,
                resume=lambda: runner._resume_channel_validation(
                    run_input.candidate_id,
                    stage_input.attempt_index,
                ),
            )
        except BudgetSafetyCapExceeded as error:
            return self._safety_cap_result(error)
        return StageExecutionResult(ok=True, payload=result.model_dump(mode="json"))

    @activity.defn(name="truth_engine.record_decision")
    def record_decision(self, decision_input: DecisionActivityInput) -> dict[str, Any]:
        repository = TruthEngineRepository.from_database_url(decision_input.run_input.database_url)
        settings = self._settings_for(decision_input.run_input)
        runner = self._runner_for(decision_input.run_input, repository, settings)
        stage = Stage(decision_input.stage)
        existing = repository.get_decision_event(
            candidate_id=decision_input.run_input.candidate_id,
            stage=stage,
            iteration=decision_input.iteration,
        )
        event = existing
        if event is None:
            event = runner._append_decision(
                candidate_id=decision_input.run_input.candidate_id,
                stage=stage,
                action=GateAction(decision_input.action),
                reason=decision_input.reason,
                iteration=decision_input.iteration,
            )
        budget_mode = runner._budget_mode(decision_input.run_input.candidate_id).value
        runner._gate_decision(
            decision_input.run_input.candidate_id,
            decision_input.gate,
            event.action.value,
            event.reason,
            score=decision_input.score,
            budget_mode=budget_mode,
        )
        return event.model_dump(mode="json")

    @activity.defn(name="truth_engine.record_budget_warning")
    def record_budget_warning(self, run_input: TruthEngineRunInput) -> None:
        repository = TruthEngineRepository.from_database_url(run_input.database_url)
        settings = self._settings_for(run_input)
        runner = self._runner_for(run_input, repository, settings)
        candidate = repository.get_candidate(run_input.candidate_id)
        total_cost = candidate.total_cost_eur if candidate is not None else 0.0
        runner._budget_warning(run_input.candidate_id, BudgetMode.SAFETY_CAP.value, total_cost)

    @activity.defn(name="truth_engine.finalize_kill")
    def finalize_kill(self, kill_input: KillActivityInput) -> TruthEngineRunResult:
        repository = TruthEngineRepository.from_database_url(kill_input.run_input.database_url)
        settings = self._settings_for(kill_input.run_input)
        runner = self._runner_for(kill_input.run_input, repository, settings)
        decision = DecisionEvent.model_validate(kill_input.decision_payload)

        if (
            kill_input.arena_payload is not None
            and kill_input.scoring_payload is not None
            and kill_input.skeptic_payload is not None
        ):
            scoring = ScoringResult.model_validate(kill_input.scoring_payload).top_candidate
            runner._store_learnings(
                kill_input.run_input.candidate_id,
                extract_kill_learnings(
                    kill_input.run_input.candidate_id,
                    decision.reason,
                    arena=EvaluatedArena.model_validate(kill_input.arena_payload),
                    scoring=scoring,
                    skeptic=SkepticReport.model_validate(kill_input.skeptic_payload),
                ),
            )

        outcome = runner._kill_outcome(kill_input.run_input.candidate_id, decision)
        return TruthEngineRunResult(
            candidate_id=outcome.candidate_id,
            status=outcome.status,
            final_decision_payload=outcome.final_decision.model_dump(mode="json"),
            trace_path=kill_input.run_input.trace_path(),
        )

    @activity.defn(name="truth_engine.finalize_success")
    def finalize_success(self, success_input: SuccessActivityInput) -> TruthEngineRunResult:
        repository = TruthEngineRepository.from_database_url(success_input.run_input.database_url)
        settings = self._settings_for(success_input.run_input)
        runner = self._runner_for(success_input.run_input, repository, settings)

        arena = EvaluatedArena.model_validate(success_input.arena_payload)
        scoring = ScoringResult.model_validate(success_input.scoring_payload)
        skeptic = SkepticReport.model_validate(success_input.skeptic_payload)
        selected_wedge = WedgeHypothesis.model_validate(success_input.selected_wedge_payload)
        channel_validation = ChannelValidation.model_validate(
            success_input.channel_validation_payload
        )
        problem_unit = repository.get_problem_unit(
            success_input.run_input.candidate_id,
            scoring.top_candidate.problem_unit_id,
        )
        if problem_unit is None:
            raise ValueError(f"Unknown problem unit: {scoring.top_candidate.problem_unit_id}")

        dossier = runner._build_dossier(
            candidate_id=success_input.run_input.candidate_id,
            arena=arena,
            problem_unit=problem_unit,
            scoring=scoring.top_candidate,
            skeptic=skeptic,
            selected_wedge=selected_wedge,
            caution_flags=runner._caution_flags(success_input.run_input.candidate_id),
            channel_validation=channel_validation,
        )
        repository.store_dossier(success_input.run_input.candidate_id, dossier)
        repository.update_candidate(
            success_input.run_input.candidate_id,
            status="passed_gate_b",
            current_stage=Stage.BUYER_CHANNEL.value,
        )
        runner._store_learnings(
            success_input.run_input.candidate_id,
            extract_pass_learnings(success_input.run_input.candidate_id, dossier),
        )

        json_path, markdown_path = write_dossier_artifacts(
            dossier,
            Path(success_input.run_input.output_dir),
        )
        if runner.trace_writer is not None:
            runner.trace_writer.artifact(label="dossier_json", path=json_path)
            runner.trace_writer.artifact(label="dossier_markdown", path=markdown_path)
        candidate = repository.get_candidate(success_input.run_input.candidate_id)
        total_cost = candidate.total_cost_eur if candidate is not None else 0.0
        runner._outcome(
            success_input.run_input.candidate_id,
            "passed_gate_b",
            total_cost_eur=total_cost,
        )
        final_decision = runner._latest_decision_event(success_input.run_input.candidate_id)
        if final_decision is None:
            raise ValueError("Final decision event missing for successful candidate.")
        outcome = WorkflowOutcome(
            candidate_id=success_input.run_input.candidate_id,
            status="passed_gate_b",
            final_decision=final_decision,
            dossier=dossier,
        )
        return TruthEngineRunResult(
            candidate_id=outcome.candidate_id,
            status=outcome.status,
            final_decision_payload=outcome.final_decision.model_dump(mode="json"),
            trace_path=success_input.run_input.trace_path(),
            dossier_json_path=str(json_path),
            dossier_markdown_path=str(markdown_path),
        )

    def _existing_result(
        self,
        repository: TruthEngineRepository,
        run_input: TruthEngineRunInput,
        runner: CandidateWorkflowRunner,
    ) -> TruthEngineRunResult | None:
        candidate = repository.get_candidate(run_input.candidate_id)
        if candidate is None:
            return None
        final_decision = runner._latest_decision_event(run_input.candidate_id)
        if candidate.status == "passed_gate_b":
            if final_decision is None:
                raise ValueError(
                    f"Candidate {run_input.candidate_id} passed Gate B without a final decision."
                )
            dossier = repository.load_dossier(run_input.candidate_id)
            if dossier is None:
                raise ValueError(
                    f"Candidate {run_input.candidate_id} passed Gate B without a stored dossier."
                )
            json_path, markdown_path = write_dossier_artifacts(dossier, Path(run_input.output_dir))
            if runner.trace_writer is not None:
                runner.trace_writer.artifact(label="dossier_json", path=json_path)
                runner.trace_writer.artifact(label="dossier_markdown", path=markdown_path)
            return TruthEngineRunResult(
                candidate_id=run_input.candidate_id,
                status="passed_gate_b",
                final_decision_payload=final_decision.model_dump(mode="json"),
                trace_path=run_input.trace_path(),
                dossier_json_path=str(json_path),
                dossier_markdown_path=str(markdown_path),
            )
        if candidate.status == "killed":
            if final_decision is None:
                raise ValueError(
                    f"Candidate {run_input.candidate_id} is killed without a final decision."
                )
            return TruthEngineRunResult(
                candidate_id=run_input.candidate_id,
                status="killed",
                final_decision_payload=final_decision.model_dump(mode="json"),
                trace_path=run_input.trace_path(),
            )
        return None

    def _runner_for(
        self,
        run_input: TruthEngineRunInput,
        repository: TruthEngineRepository,
        settings: Settings,
    ) -> CandidateWorkflowRunner:
        tool_runtime = self._build_live_tool_runtime(repository, settings)
        return CandidateWorkflowRunner(
            repository=repository,
            settings=settings,
            tool_runtime=tool_runtime,
            trace_writer=self._trace_writer_for(run_input),
        )

    def _settings_for(self, run_input: TruthEngineRunInput) -> Settings:
        return Settings(
            database_url=run_input.database_url,
            prompt_version=run_input.prompt_version,
        )

    def _trace_writer_for(self, run_input: TruthEngineRunInput) -> RunTraceWriter:
        return RunTraceWriter.create(
            output_dir=Path(run_input.output_dir),
            candidate_id=run_input.candidate_id,
            mode=run_input.mode,
            prompt_version=run_input.prompt_version,
        )

    def _live_bundle(
        self,
        run_input: TruthEngineRunInput,
        repository: TruthEngineRepository,
        settings: Settings,
        trace_writer: RunTraceWriter | None,
    ) -> LiveActivityBundle | None:
        if run_input.mode != "live":
            return None
        request_payload = run_input.request_payload or LiveRunRequest(
            candidate_id=run_input.candidate_id
        ).model_dump(mode="json")
        request = LiveRunRequest.model_validate(request_payload)
        if request.candidate_id != run_input.candidate_id:
            request = request.model_copy(update={"candidate_id": run_input.candidate_id})
        return LiveActivityBundle(
            request=request,
            repository=repository,
            settings=settings,
            agent_runner=LiteLLMAgentRunner(
                settings=settings,
                repository=repository,
                trace_writer=trace_writer,
            ),
            tool_runtime=self._build_live_tool_runtime(repository, settings),
        )

    def _fixture_scenario(self, run_input: TruthEngineRunInput) -> FixtureScenario | None:
        if run_input.mode != "fixture":
            return None
        if run_input.fixture_path is None:
            raise ValueError("Fixture mode requires fixture_path.")
        return FixtureScenario.from_path(Path(run_input.fixture_path))

    def _build_live_tool_runtime(
        self,
        repository: TruthEngineRepository,
        settings: Settings,
    ) -> RepositoryToolRuntime:
        fetch_client = WebFetchClient(settings)
        search_client = SerperSearchClient(settings) if settings.has_serper_search() else None
        reddit_client = RedditSearchClient(settings) if settings.has_reddit_tools() else None
        return RepositoryToolRuntime(
            repository,
            search_client=search_client,
            page_fetcher=fetch_client,
            content_extractor=fetch_client,
            reddit_client=reddit_client,
        )

    @staticmethod
    def _safety_cap_result(error: BudgetSafetyCapExceeded) -> StageExecutionResult:
        return StageExecutionResult(
            ok=False,
            safety_cap_stage=error.stage.value,
            safety_cap_attempt_index=error.attempt_index,
        )

    @staticmethod
    def _take[T](items: list[T], index: int, name: str) -> T:
        if index >= len(items):
            raise ValueError(f"No remaining {name} fixture at index {index}")
        return items[index]
