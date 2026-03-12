from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TruthEngineRunInput:
    mode: str
    candidate_id: str
    database_url: str
    output_dir: str
    prompt_version: str
    fixture_path: str | None = None
    request_payload: dict[str, Any] | None = None

    def trace_path(self) -> str:
        return str(Path(self.output_dir) / f"{self.candidate_id}.trace.md")


@dataclass(frozen=True)
class StageExecutionInput:
    run_input: TruthEngineRunInput
    attempt_index: int = 0
    targeted_weakness: str | None = None


@dataclass(frozen=True)
class StageExecutionResult:
    ok: bool
    payload: dict[str, Any] | None = None
    safety_cap_stage: str | None = None
    safety_cap_attempt_index: int = 0


@dataclass(frozen=True)
class DecisionActivityInput:
    run_input: TruthEngineRunInput
    stage: str
    gate: str
    action: str
    reason: str
    iteration: int = 0
    score: int | None = None


@dataclass(frozen=True)
class KillActivityInput:
    run_input: TruthEngineRunInput
    decision_payload: dict[str, Any]
    arena_payload: dict[str, Any] | None = None
    scoring_payload: dict[str, Any] | None = None
    skeptic_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class SuccessActivityInput:
    run_input: TruthEngineRunInput
    arena_payload: dict[str, Any]
    scoring_payload: dict[str, Any]
    skeptic_payload: dict[str, Any]
    selected_wedge_payload: dict[str, Any]
    channel_validation_payload: dict[str, Any]


@dataclass(frozen=True)
class TruthEngineWorkflowSnapshot:
    candidate_id: str
    status: str
    current_stage: str | None
    budget_mode: str
    trace_path: str
    gate_a_iteration: int = 0
    wedge_iteration: int = 0
    gate_b_retry_index: int = 0
    last_decision_action: str | None = None
    last_decision_reason: str | None = None
    dossier_json_path: str | None = None
    dossier_markdown_path: str | None = None


@dataclass(frozen=True)
class TruthEngineRunResult:
    candidate_id: str
    status: str
    final_decision_payload: dict[str, Any]
    trace_path: str
    dossier_json_path: str | None = None
    dossier_markdown_path: str | None = None
