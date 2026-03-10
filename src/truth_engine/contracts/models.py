from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from truth_engine.domain.enums import AgentName, Stage
from truth_engine.services.dedup import arena_fingerprint, canonicalize_source_url


class RawArena(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str | None = None
    domain: str
    icp_user_role: str
    icp_buyer_role: str
    geo: str
    channel_surface: list[str]
    solution_modality: str
    market_signals: list[str]
    signal_sources: list[str]
    market_size_signal: str
    expected_sales_cycle: str
    rationale: str

    def fingerprint(self) -> str:
        return arena_fingerprint(self.domain, self.icp_user_role)


class RawSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str | None = None
    source_type: str
    source_url: str
    source_url_hash: str | None = None
    verbatim_quote: str
    persona: str | None
    inferred_pain: str
    inferred_frequency: str
    proof_of_spend: bool
    switching_signal: bool
    tags: list[str]
    reliability_score: float = Field(ge=0.0, le=1.0)
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="before")
    @classmethod
    def ensure_source_url_hash(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if data.get("source_url_hash") is not None:
            return data

        source_url = data.get("source_url")
        if isinstance(source_url, str):
            data = dict(data)
            canonical_url = canonicalize_source_url(source_url)
            data["source_url_hash"] = sha256(canonical_url.encode()).hexdigest()[:16]
        return data


class ProblemUnit(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    job_to_be_done: str
    trigger_event: str
    frequency: str
    severity: int = Field(ge=1, le=10)
    urgency: str
    cost_of_failure: str
    current_workaround: str
    proof_of_spend: str
    switching_friction: int = Field(ge=1, le=10)
    buyer_authority: str
    evidence_ids: list[str]
    signal_count: int = Field(ge=0)
    source_diversity: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)


class CostRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    stage: Stage
    agent: AgentName
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    cost_eur: float = Field(ge=0.0)
    timestamp: datetime

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, value: str | datetime) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
