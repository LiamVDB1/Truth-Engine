from __future__ import annotations

from typing import Any
from uuid import uuid4

from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.adapters.llm.litellm_runner import LiteLLMAgentRunner
from truth_engine.config.settings import Settings
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
from truth_engine.contracts.live import LiveRunRequest
from truth_engine.contracts.models import ProblemUnit, RawArena
from truth_engine.contracts.stages import (
    ArenaEvaluation,
    ArenaSearchResult,
    ChannelValidation,
    EvaluatedArena,
    LandscapeReport,
    NormalizationResult,
    ScoringResult,
    SignalMiningResult,
    SkepticReport,
    WedgeCritique,
    WedgeHypothesis,
    WedgeProposal,
)
from truth_engine.domain.enums import AgentName, Stage
from truth_engine.prompts.builder import build_prompt
from truth_engine.tools.runtime import RepositoryToolRuntime
from truth_engine.tools.schemas import tool_schemas_for_agent


class LiveActivityBundle:
    persists_tool_state = True
    _MAX_ARENA_PROPOSALS = 6
    _SEARCH_RESULTS_PER_QUERY = 5
    _MAX_SIGNALS = 60

    def __init__(
        self,
        *,
        request: LiveRunRequest,
        repository: TruthEngineRepository,
        settings: Settings,
        agent_runner: LiteLLMAgentRunner,
        tool_runtime: RepositoryToolRuntime,
    ):
        self.request = request
        self.repository = repository
        self.settings = settings
        self.agent_runner = agent_runner
        self.tool_runtime = tool_runtime
        self._selected_arena: EvaluatedArena | None = None
        self._latest_landscape_report: LandscapeReport | None = None
        self._latest_scoring_result: ScoringResult | None = None
        self._latest_skeptic_report: SkepticReport | None = None
        self._latest_wedge_proposal: WedgeProposal | None = None
        self._latest_wedge_critique: WedgeCritique | None = None

    @property
    def candidate_id(self) -> str:
        return self.request.candidate_id

    def arena_discovery(self) -> ArenaDiscoveryFixture:
        scout_context = {
            "candidate_id": self.candidate_id,
            "stage": Stage.ARENA_DISCOVERY.value,
            "output_contract": "ArenaSearchResult",
            "founder_constraints": self.request.founder_constraints.model_dump(mode="json"),
            "past_learnings": self.repository.list_recent_learnings(limit=10),
            "max_arena_proposals": self._MAX_ARENA_PROPOSALS,
            "execution_requirements": [
                "Use search_web and reddit_search to gather breadth-first evidence.",
                "Persist each viable arena via create_arena_proposal.",
                "Keep at most max_arena_proposals live proposals.",
            ],
        }
        scout_execution = self.agent_runner.run(
            agent=AgentName.ARENA_SCOUT,
            prompt=build_prompt(
                AgentName.ARENA_SCOUT.value,
                scout_context,
                self.settings,
                available_tool_names=self.tool_runtime.available_tool_names(AgentName.ARENA_SCOUT),
            ),
            response_model=ArenaSearchResult,
            tools=tool_schemas_for_agent(
                AgentName.ARENA_SCOUT,
                available_tool_names=self.tool_runtime.available_tool_names(AgentName.ARENA_SCOUT),
            ),
            tool_executor=self._tool_executor(AgentName.ARENA_SCOUT),
            required_tool_names={"create_arena_proposal"},
        )

        raw_arenas = self.repository.load_arena_proposals(self.candidate_id)
        if not raw_arenas:
            raise ValueError("Arena Scout did not persist any arena proposals.")

        evaluator_context = {
            "candidate_id": self.candidate_id,
            "stage": Stage.ARENA_DISCOVERY.value,
            "output_contract": "ArenaEvaluation",
            "raw_arenas": [arena.model_dump(mode="json") for arena in raw_arenas],
            "founder_constraints": self.request.founder_constraints.model_dump(mode="json"),
        }
        evaluator_execution = self.agent_runner.run(
            agent=AgentName.ARENA_EVALUATOR,
            prompt=build_prompt(
                AgentName.ARENA_EVALUATOR.value,
                evaluator_context,
                self.settings,
            ),
            response_model=ArenaEvaluation,
            tools=None,
            tool_executor=None,
        )
        evaluation = _hydrate_evaluation(evaluator_execution.result, raw_arenas)
        self._selected_arena = evaluation.ranked_arenas[0]
        return ArenaDiscoveryFixture(
            scout_metrics=scout_execution.metrics,
            evaluator_metrics=evaluator_execution.metrics,
            search_result=scout_execution.result,
            raw_arenas=raw_arenas,
            evaluation=evaluation,
        )

    def signal_mining(self, targeted_weakness: str | None = None) -> SignalMiningFixtureRun:
        selected_arena = self._require_selected_arena()
        prompt_context = {
            "candidate_id": self.candidate_id,
            "stage": Stage.SIGNAL_MINING.value,
            "output_contract": "SignalMiningResult",
            "arena": selected_arena.model_dump(mode="json"),
            "source_targets": _source_targets_for_arena(selected_arena),
            "targeted_weakness": targeted_weakness,
            "max_signals": self._MAX_SIGNALS,
            "existing_signal_summary": self.repository.signal_summary(self.candidate_id),
            "execution_requirements": [
                "Persist each signal via add_signal.",
                "Prefer pain, spend, and switching evidence.",
                "Use fetch_page/extract_content or reddit_fetch to inspect concrete sources.",
            ],
        }
        execution = self.agent_runner.run(
            agent=AgentName.SIGNAL_SCOUT,
            prompt=build_prompt(
                AgentName.SIGNAL_SCOUT.value,
                prompt_context,
                self.settings,
                available_tool_names=self.tool_runtime.available_tool_names(AgentName.SIGNAL_SCOUT),
            ),
            response_model=SignalMiningResult,
            tools=tool_schemas_for_agent(
                AgentName.SIGNAL_SCOUT,
                available_tool_names=self.tool_runtime.available_tool_names(AgentName.SIGNAL_SCOUT),
            ),
            tool_executor=self._tool_executor(AgentName.SIGNAL_SCOUT),
            required_tool_names={"add_signal"},
        )
        return SignalMiningFixtureRun(
            targeted_weakness=targeted_weakness,
            metrics=execution.metrics,
            result=execution.result,
            raw_signals=self.repository.list_raw_signals(self.candidate_id),
        )

    def normalization(self) -> NormalizationFixtureRun:
        selected_arena = self._require_selected_arena()
        raw_signals = self.repository.list_raw_signals(self.candidate_id)
        execution = self.agent_runner.run(
            agent=AgentName.NORMALIZER,
            prompt=build_prompt(
                AgentName.NORMALIZER.value,
                {
                    "candidate_id": self.candidate_id,
                    "stage": Stage.NORMALIZATION.value,
                    "output_contract": "NormalizationResult",
                    "arena": selected_arena.model_dump(mode="json"),
                    "raw_signals": [signal.model_dump(mode="json") for signal in raw_signals],
                },
                self.settings,
            ),
            response_model=NormalizationResult,
            tools=None,
            tool_executor=None,
        )
        return NormalizationFixtureRun(metrics=execution.metrics, result=execution.result)

    def landscape_research(self) -> LandscapeResearchFixture:
        selected_arena = self._require_selected_arena()
        problem_units = self.repository.list_problem_units(self.candidate_id)
        execution = self.agent_runner.run(
            agent=AgentName.LANDSCAPE_SCOUT,
            prompt=build_prompt(
                AgentName.LANDSCAPE_SCOUT.value,
                {
                    "candidate_id": self.candidate_id,
                    "stage": Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                    "output_contract": "LandscapeReport",
                    "arena": selected_arena.model_dump(mode="json"),
                    "problem_units": [unit.model_dump(mode="json") for unit in problem_units],
                    "execution_requirements": [
                        "Persist each landscape finding via add_landscape_entry.",
                        "Prioritize active competitors and failed attempts before adjacent tools.",
                    ],
                },
                self.settings,
                available_tool_names=self.tool_runtime.available_tool_names(
                    AgentName.LANDSCAPE_SCOUT
                ),
            ),
            response_model=LandscapeReport,
            tools=tool_schemas_for_agent(
                AgentName.LANDSCAPE_SCOUT,
                available_tool_names=self.tool_runtime.available_tool_names(
                    AgentName.LANDSCAPE_SCOUT
                ),
            ),
            tool_executor=self._tool_executor(AgentName.LANDSCAPE_SCOUT),
            required_tool_names={"add_landscape_entry"},
        )
        self._latest_landscape_report = execution.result
        return LandscapeResearchFixture(
            metrics=execution.metrics,
            result=execution.result,
            entries=self.repository.list_landscape_entries(self.candidate_id),
        )

    def scoring(self) -> ScoringFixtureRun:
        selected_arena = self._require_selected_arena()
        problem_units = self.repository.list_problem_units(self.candidate_id)
        landscape_report = self._require_landscape_report()
        landscape_entries = self.repository.list_landscape_entries(self.candidate_id)
        execution = self.agent_runner.run(
            agent=AgentName.SCORER,
            prompt=build_prompt(
                AgentName.SCORER.value,
                {
                    "candidate_id": self.candidate_id,
                    "stage": Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                    "output_contract": "ScoringResult",
                    "arena": selected_arena.model_dump(mode="json"),
                    "problem_units": [unit.model_dump(mode="json") for unit in problem_units],
                    "landscape_report": landscape_report.model_dump(mode="json"),
                    "landscape_entries": [
                        entry.model_dump(mode="json") for entry in landscape_entries
                    ],
                },
                self.settings,
            ),
            response_model=ScoringResult,
            tools=None,
            tool_executor=None,
        )
        self._latest_scoring_result = execution.result
        return ScoringFixtureRun(metrics=execution.metrics, result=execution.result)

    def skeptic(self) -> SkepticFixtureRun:
        selected_arena = self._require_selected_arena()
        scoring_result = self._require_scoring_result()
        top_candidate = scoring_result.top_candidate
        problem_unit = self._require_problem_unit(top_candidate.problem_unit_id)
        evidence = self.repository.get_raw_signals_by_ids(
            self.candidate_id,
            problem_unit.evidence_ids,
        )
        landscape_entries = self.repository.list_landscape_entries(self.candidate_id)
        execution = self.agent_runner.run(
            agent=AgentName.SKEPTIC,
            prompt=build_prompt(
                AgentName.SKEPTIC.value,
                {
                    "candidate_id": self.candidate_id,
                    "stage": Stage.LANDSCAPE_SCORING_SKEPTIC.value,
                    "output_contract": "SkepticReport",
                    "arena": selected_arena.model_dump(mode="json"),
                    "top_candidate": top_candidate.model_dump(mode="json"),
                    "problem_unit": problem_unit.model_dump(mode="json"),
                    "evidence_items": [item.model_dump(mode="json") for item in evidence],
                    "landscape_report": self._require_landscape_report().model_dump(mode="json"),
                    "landscape_entries": [
                        entry.model_dump(mode="json") for entry in landscape_entries
                    ],
                },
                self.settings,
            ),
            response_model=SkepticReport,
            tools=None,
            tool_executor=None,
        )
        self._latest_skeptic_report = execution.result
        return SkepticFixtureRun(metrics=execution.metrics, result=execution.result)

    def wedge_design(self) -> WedgeDesignFixtureRun:
        selected_arena = self._require_selected_arena()
        scoring_result = self._require_scoring_result()
        top_candidate = scoring_result.top_candidate
        problem_unit = self._require_problem_unit(top_candidate.problem_unit_id)
        skeptic_report = self._require_skeptic_report()
        execution = self.agent_runner.run(
            agent=AgentName.WEDGE_DESIGNER,
            prompt=build_prompt(
                AgentName.WEDGE_DESIGNER.value,
                {
                    "candidate_id": self.candidate_id,
                    "stage": Stage.WEDGE_DESIGN.value,
                    "output_contract": "WedgeProposal",
                    "arena": selected_arena.model_dump(mode="json"),
                    "scored_candidate": top_candidate.model_dump(mode="json"),
                    "problem_unit": problem_unit.model_dump(mode="json"),
                    "skeptic_report": skeptic_report.model_dump(mode="json"),
                },
                self.settings,
            ),
            response_model=WedgeProposal,
            tools=None,
            tool_executor=None,
        )
        self._latest_wedge_proposal = _assign_wedge_ids(execution.result)
        return WedgeDesignFixtureRun(metrics=execution.metrics, result=self._latest_wedge_proposal)

    def wedge_critique(self) -> WedgeCritiqueFixtureRun:
        scoring_result = self._require_scoring_result()
        top_candidate = scoring_result.top_candidate
        problem_unit = self._require_problem_unit(top_candidate.problem_unit_id)
        wedge_proposal = self._require_wedge_proposal()
        execution = self.agent_runner.run(
            agent=AgentName.WEDGE_CRITIC,
            prompt=build_prompt(
                AgentName.WEDGE_CRITIC.value,
                {
                    "candidate_id": self.candidate_id,
                    "stage": Stage.WEDGE_DESIGN.value,
                    "output_contract": "WedgeCritique",
                    "scored_candidate": top_candidate.model_dump(mode="json"),
                    "problem_unit": problem_unit.model_dump(mode="json"),
                    "wedge_proposal": wedge_proposal.model_dump(mode="json"),
                },
                self.settings,
            ),
            response_model=WedgeCritique,
            tools=None,
            tool_executor=None,
        )
        self._latest_wedge_critique = execution.result
        return WedgeCritiqueFixtureRun(metrics=execution.metrics, result=execution.result)

    def channel_validation(self) -> ChannelValidationFixtureRun:
        selected_arena = self._require_selected_arena()
        scoring_result = self._require_scoring_result()
        top_candidate = scoring_result.top_candidate
        problem_unit = self._require_problem_unit(top_candidate.problem_unit_id)
        selected_wedge = self._selected_wedge()
        execution = self.agent_runner.run(
            agent=AgentName.BUYER_CHANNEL_VALIDATOR,
            prompt=build_prompt(
                AgentName.BUYER_CHANNEL_VALIDATOR.value,
                {
                    "candidate_id": self.candidate_id,
                    "stage": Stage.BUYER_CHANNEL.value,
                    "output_contract": "ChannelValidation",
                    "arena": selected_arena.model_dump(mode="json"),
                    "selected_wedge": selected_wedge.model_dump(mode="json"),
                    "problem_unit": problem_unit.model_dump(mode="json"),
                    "scored_candidate": top_candidate.model_dump(mode="json"),
                },
                self.settings,
            ),
            response_model=ChannelValidation,
            tools=None,
            tool_executor=None,
        )
        return ChannelValidationFixtureRun(metrics=execution.metrics, result=execution.result)

    def _tool_executor(self, agent: AgentName) -> Any:
        def execute(tool_name: str, arguments: dict[str, Any]) -> Any:
            payload = _tool_payload(tool_name, self.candidate_id, arguments)
            return self.tool_runtime.invoke(agent, tool_name, payload)

        return execute

    def _require_selected_arena(self) -> EvaluatedArena:
        if self._selected_arena is None:
            raise ValueError("Selected arena is not available yet.")
        return self._selected_arena

    def _require_landscape_report(self) -> LandscapeReport:
        if self._latest_landscape_report is None:
            raise ValueError("Landscape report is not available yet.")
        return self._latest_landscape_report

    def _require_scoring_result(self) -> ScoringResult:
        if self._latest_scoring_result is None:
            raise ValueError("Scoring result is not available yet.")
        return self._latest_scoring_result

    def _require_skeptic_report(self) -> SkepticReport:
        if self._latest_skeptic_report is None:
            raise ValueError("Skeptic report is not available yet.")
        return self._latest_skeptic_report

    def _require_wedge_proposal(self) -> WedgeProposal:
        if self._latest_wedge_proposal is None:
            raise ValueError("Wedge proposal is not available yet.")
        return self._latest_wedge_proposal

    def _selected_wedge(self) -> WedgeHypothesis:
        wedge_proposal = self._require_wedge_proposal()
        critique = self._latest_wedge_critique
        if critique is None:
            raise ValueError("Wedge critique is not available yet.")
        return wedge_proposal.wedges[critique.best_wedge_index]

    def _require_problem_unit(self, problem_unit_id: str) -> ProblemUnit:
        problem_unit = self.repository.get_problem_unit(self.candidate_id, problem_unit_id)
        if problem_unit is None:
            raise ValueError(f"Unknown problem unit: {problem_unit_id}")
        return problem_unit


def _tool_payload(tool_name: str, candidate_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "create_arena_proposal":
        return {"candidate_id": candidate_id, "arena": arguments}
    if tool_name == "add_signal":
        return {"candidate_id": candidate_id, "signal": arguments}
    if tool_name == "add_landscape_entry":
        return {"candidate_id": candidate_id, "entry": arguments}
    if tool_name in {
        "view_arena_proposals",
        "view_signal_summary",
        "view_landscape",
    }:
        return {"candidate_id": candidate_id}
    payload = dict(arguments)
    payload.setdefault("candidate_id", candidate_id)
    return payload


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


def _assign_wedge_ids(proposal: WedgeProposal) -> WedgeProposal:
    wedges = []
    for wedge in proposal.wedges:
        if wedge.id is None:
            wedges.append(wedge.model_copy(update={"id": f"wedge_{uuid4().hex[:12]}"}))
        else:
            wedges.append(wedge)
    return proposal.model_copy(update={"wedges": wedges})


def _source_targets_for_arena(arena: EvaluatedArena) -> list[str]:
    if arena.recommended_first_sources:
        return arena.recommended_first_sources
    return ["reddit", "job_postings", "public_web"]
