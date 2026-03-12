from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from truth_engine.contracts.stages import ActivityMetrics
from truth_engine.domain.enums import AgentCheckpointStatus, AgentName, Stage


class CandidateStageRunRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    stage: Stage
    agent: AgentName
    attempt_index: int = Field(default=0, ge=0)
    prompt_version: str
    prompt_hash: str
    model_alias: str
    payload: dict[str, Any]
    metrics: ActivityMetrics
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentCheckpointState(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: list[dict[str, Any]]
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_eur: float = Field(default=0.0, ge=0.0)
    tool_calls: int = Field(default=0, ge=0)
    tool_rounds_used: int = Field(default=0, ge=0)
    repair_attempts: int = Field(default=0, ge=0)
    finalization_prompt_sent: bool = False
    seen_tool_signatures: dict[str, int] = Field(default_factory=dict)
    executed_tool_names: list[str] = Field(default_factory=list)
    pending_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    pending_tool_index: int = Field(default=0, ge=0)
    result_payload: dict[str, Any] | None = None
    metrics_payload: dict[str, Any] | None = None

    def metrics(self) -> ActivityMetrics:
        payload = self.metrics_payload or {
            "cost_eur": self.cost_eur,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls": self.tool_calls,
        }
        return ActivityMetrics.model_validate(payload)


class AgentCheckpointRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    stage: Stage
    agent: AgentName
    attempt_index: int = Field(default=0, ge=0)
    status: AgentCheckpointStatus
    prompt_version: str
    prompt_hash: str
    model_alias: str
    response_model: str
    state: AgentCheckpointState
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
