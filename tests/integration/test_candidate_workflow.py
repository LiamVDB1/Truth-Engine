from __future__ import annotations

import json
import socket
from collections import Counter
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import cast

import pytest

from truth_engine.activities.fixtures import FixtureActivityBundle
from truth_engine.adapters.db.migrate import upgrade_database
from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.cli.main import main
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
from truth_engine.domain.enums import AgentName, GateAction
from truth_engine.workflows.candidate import CandidateWorkflowRunner

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "workflows"


def test_cli_run_fixture_generates_dossier_and_persists_gate_b_candidate(tmp_path: Path) -> None:
    try:
        with socket.create_connection(("localhost", 7233), timeout=0.2):
            pass
    except OSError:
        pytest.skip("Temporal server is not running on localhost:7233")

    database_path = tmp_path / "truth_engine.db"
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "run-fixture",
            "--fixture",
            str(FIXTURE_ROOT / "investigate_revise_reachable.json"),
            "--database-url",
            f"sqlite:///{database_path}",
            "--output-dir",
            str(output_dir),
            "--prompt-version",
            "test-suite",
        ]
    )

    assert exit_code == 0

    dossier_json = output_dir / "cand_logistics_ops.json"
    dossier_markdown = output_dir / "cand_logistics_ops.md"
    assert dossier_json.exists()
    assert dossier_markdown.exists()

    payload = json.loads(dossier_json.read_text(encoding="utf-8"))
    markdown = dossier_markdown.read_text(encoding="utf-8")
    assert payload["candidate_id"] == "cand_logistics_ops"
    assert payload["channel_validation"]["verdict"] == "reachable"
    assert payload["selected_wedge"]["wedge_promise"].startswith("We")
    assert "First 20 Conversations" in markdown
    assert "Start with 20 Heads of Ops" in markdown
    assert "**Procurement Notes:**" in markdown

    from truth_engine.adapters.db.repositories import TruthEngineRepository

    repository = TruthEngineRepository.from_database_url(f"sqlite:///{database_path}")
    candidate = repository.get_candidate("cand_logistics_ops")
    assert candidate is not None
    assert candidate.status == "passed_gate_b"

    decisions = repository.list_decision_events("cand_logistics_ops")
    assert [decision.action for decision in decisions] == [
        GateAction.INVESTIGATE,
        GateAction.ADVANCE,
        GateAction.REVISE,
        GateAction.ADVANCE,
        GateAction.RETRY,
        GateAction.ADVANCE,
    ]

    assert repository.count_stage_runs("cand_logistics_ops", agent=AgentName.SIGNAL_SCOUT) == 2
    assert repository.count_stage_runs("cand_logistics_ops", agent=AgentName.WEDGE_DESIGNER) == 2
    assert (
        repository.count_stage_runs("cand_logistics_ops", agent=AgentName.BUYER_CHANNEL_VALIDATOR)
        == 2
    )


def test_fixture_workflow_kills_candidate_after_gate_b_retry_exhaustion(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"

    from truth_engine.activities.fixtures import FixtureActivityBundle
    from truth_engine.adapters.db.migrate import upgrade_database
    from truth_engine.adapters.db.repositories import TruthEngineRepository
    from truth_engine.workflows.candidate import CandidateWorkflowRunner

    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)
    activities = FixtureActivityBundle.from_path(FIXTURE_ROOT / "gate_b_retry_kill.json")
    runner = CandidateWorkflowRunner(
        repository=repository,
        settings=Settings(database_url=database_url),
    )

    outcome = runner.run(activities)

    assert outcome.status == "killed"
    assert outcome.final_decision.action is GateAction.KILL
    assert outcome.dossier is None

    decisions = repository.list_decision_events("cand_procurement_ops")
    assert [decision.action for decision in decisions][-2:] == [GateAction.RETRY, GateAction.KILL]


def test_budget_degrade_mode_skips_optional_gate_b_retry(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"

    from truth_engine.activities.fixtures import FixtureActivityBundle
    from truth_engine.adapters.db.migrate import upgrade_database
    from truth_engine.adapters.db.repositories import TruthEngineRepository
    from truth_engine.workflows.candidate import CandidateWorkflowRunner

    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)
    activities = FixtureActivityBundle.from_path(FIXTURE_ROOT / "budget_degrade_gate_b_kill.json")
    runner = CandidateWorkflowRunner(
        repository=repository,
        settings=Settings(database_url=database_url),
    )

    outcome = runner.run(activities)

    assert outcome.status == "killed"
    assert outcome.final_decision.action is GateAction.KILL
    assert (
        repository.count_stage_runs("cand_budget_pressure", agent=AgentName.BUYER_CHANNEL_VALIDATOR)
        == 1
    )


def test_budget_safety_cap_kills_candidate_when_cost_exceeds_limit(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"

    from truth_engine.activities.fixtures import FixtureActivityBundle
    from truth_engine.adapters.db.migrate import upgrade_database
    from truth_engine.adapters.db.repositories import TruthEngineRepository
    from truth_engine.workflows.candidate import CandidateWorkflowRunner

    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)
    activities = FixtureActivityBundle.from_path(FIXTURE_ROOT / "safety_cap_gate_b_kill.json")
    runner = CandidateWorkflowRunner(
        repository=repository,
        settings=Settings(database_url=database_url),
    )

    outcome = runner.run(activities)

    assert outcome.status == "killed"
    assert outcome.final_decision.action is GateAction.KILL
    assert "safety cap" in outcome.final_decision.reason.lower()


def test_workflow_resume_skips_completed_steps_after_interruption(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)
    fixture_path = FIXTURE_ROOT / "investigate_revise_reachable.json"

    first_attempt = _InterruptingFixtureBundle(
        FixtureActivityBundle.from_path(fixture_path),
        fail_on="landscape_research",
    )
    runner = CandidateWorkflowRunner(
        repository=repository,
        settings=Settings(database_url=database_url),
    )

    with pytest.raises(RuntimeError, match="synthetic interruption"):
        runner.run(first_attempt)

    resumed_attempt = _InterruptingFixtureBundle(first_attempt.delegate)
    resumed_runner = CandidateWorkflowRunner(
        repository=repository,
        settings=Settings(database_url=database_url),
    )

    outcome = resumed_runner.run(resumed_attempt)

    assert outcome.status == "passed_gate_b"
    assert resumed_attempt.calls["arena_discovery"] == 0
    assert resumed_attempt.calls["landscape_research"] == 1
    assert resumed_attempt.calls["signal_mining"] == 1
    assert resumed_attempt.calls["normalization"] == 1
    assert resumed_attempt.calls["scoring"] == 2
    assert resumed_attempt.calls["skeptic"] == 2
    assert resumed_attempt.calls["wedge_design"] == 2
    assert resumed_attempt.calls["wedge_critique"] == 2
    assert resumed_attempt.calls["channel_validation"] == 2


def test_cli_preview_prompt_renders_compiled_prompt(tmp_path: Path) -> None:
    context_file = tmp_path / "context.json"
    context_file.write_text(
        json.dumps(
            {
                "candidate_id": "cand_prompt",
                "stage": "signal_mining",
                "output_contract": "SignalMiningResult",
                "source_targets": ["reddit", "job_postings"],
            }
        ),
        encoding="utf-8",
    )

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "preview-prompt",
                "--agent",
                "signal_scout",
                "--context-file",
                str(context_file),
                "--prompt-version",
                "preview-test",
            ]
        )

    output = stdout.getvalue()
    assert exit_code == 0
    assert "Prompt version: preview-test" in output
    assert "=== SYSTEM PROMPT ===" in output
    assert "`add_signal`" in output
    assert "Return exactly one JSON object matching `SignalMiningResult`." in output
    assert "=== USER PROMPT ===" in output
    assert '"candidate_id": "cand_prompt"' in output


class _InterruptingFixtureBundle:
    persists_tool_state = False

    def __init__(
        self,
        delegate: FixtureActivityBundle,
        *,
        fail_on: str | None = None,
    ) -> None:
        self.delegate = delegate
        self.fail_on = fail_on
        self.calls: Counter[str] = Counter()

    @property
    def candidate_id(self) -> str:
        return self.delegate.candidate_id

    def arena_discovery(self) -> ArenaDiscoveryFixture:
        return cast(ArenaDiscoveryFixture, self._call("arena_discovery"))

    def signal_mining(self, targeted_weakness: str | None = None) -> SignalMiningFixtureRun:
        return cast(SignalMiningFixtureRun, self._call("signal_mining", targeted_weakness))

    def normalization(self) -> NormalizationFixtureRun:
        return cast(NormalizationFixtureRun, self._call("normalization"))

    def landscape_research(self) -> LandscapeResearchFixture:
        return cast(LandscapeResearchFixture, self._call("landscape_research"))

    def scoring(self) -> ScoringFixtureRun:
        return cast(ScoringFixtureRun, self._call("scoring"))

    def skeptic(self) -> SkepticFixtureRun:
        return cast(SkepticFixtureRun, self._call("skeptic"))

    def wedge_design(self) -> WedgeDesignFixtureRun:
        return cast(WedgeDesignFixtureRun, self._call("wedge_design"))

    def wedge_critique(self) -> WedgeCritiqueFixtureRun:
        return cast(WedgeCritiqueFixtureRun, self._call("wedge_critique"))

    def channel_validation(self) -> ChannelValidationFixtureRun:
        return cast(ChannelValidationFixtureRun, self._call("channel_validation"))

    def _call(self, name: str, *args: object) -> object:
        self.calls[name] += 1
        if self.fail_on == name:
            raise RuntimeError("synthetic interruption")
        return getattr(self.delegate, name)(*args)
