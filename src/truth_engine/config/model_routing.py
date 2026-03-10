from __future__ import annotations

from truth_engine.config.settings import Settings
from truth_engine.domain.enums import AgentName

AGENT_TIER_MAP: dict[AgentName, int] = {
    AgentName.ARENA_SCOUT: 1,
    AgentName.SIGNAL_SCOUT: 1,
    AgentName.LANDSCAPE_SCOUT: 1,
    AgentName.ARENA_EVALUATOR: 2,
    AgentName.NORMALIZER: 2,
    AgentName.SCORER: 2,
    AgentName.WEDGE_DESIGNER: 2,
    AgentName.BUYER_CHANNEL_VALIDATOR: 2,
    AgentName.OUTREACH_OPERATOR: 2,
    AgentName.ANALYST: 2,
    AgentName.SKEPTIC: 3,
    AgentName.WEDGE_CRITIC: 3,
    AgentName.CONVERSATION_AGENT: 3,
    AgentName.COMMITMENT_CLOSER: 3,
}


def resolve_agent_model(agent: AgentName, settings: Settings) -> str:
    override = settings.agent_model_overrides.get(agent.value)
    if override is not None:
        return override
    tier = AGENT_TIER_MAP[agent]
    if tier == 1:
        return settings.tier1_model
    if tier == 2:
        return settings.tier2_model
    return settings.tier3_model
