from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from truth_engine.domain.enums import (
    ChannelVerdict,
    GateAction,
    SkepticRecommendation,
    WedgeVerdict,
)


class CandidateScoreSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_score: int = Field(ge=0, le=100)


class SkepticSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    recommendation: SkepticRecommendation


class ChannelValidationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: ChannelVerdict
    total_reachable_leads: int = Field(ge=0)
    channel_count: int = Field(ge=0)
    user_role: str
    buyer_role: str
    buyer_is_user: bool
    estimated_cost_per_conversation: float = Field(ge=0.0)


class WedgeSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: WedgeVerdict


class GateDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: GateAction
    reason: str
