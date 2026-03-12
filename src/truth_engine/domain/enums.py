from __future__ import annotations

from enum import StrEnum


class AgentName(StrEnum):
    ARENA_SCOUT = "arena_scout"
    ARENA_EVALUATOR = "arena_evaluator"
    SIGNAL_SCOUT = "signal_scout"
    NORMALIZER = "normalizer"
    LANDSCAPE_SCOUT = "landscape_scout"
    SCORER = "scorer"
    SKEPTIC = "skeptic"
    WEDGE_DESIGNER = "wedge_designer"
    WEDGE_CRITIC = "wedge_critic"
    BUYER_CHANNEL_VALIDATOR = "buyer_channel_validator"
    OUTREACH_OPERATOR = "outreach_operator"
    CONVERSATION_AGENT = "conversation_agent"
    COMMITMENT_CLOSER = "commitment_closer"
    ANALYST = "analyst"


class Stage(StrEnum):
    ARENA_DISCOVERY = "arena_discovery"
    SIGNAL_MINING = "signal_mining"
    NORMALIZATION = "normalization"
    LANDSCAPE_SCORING_SKEPTIC = "landscape_scoring_skeptic"
    WEDGE_DESIGN = "wedge_design"
    BUYER_CHANNEL = "buyer_channel"
    OUTREACH_CONVERSATIONS = "outreach_conversations"
    COMMITMENT = "commitment"
    ANALYST = "analyst"


class BudgetMode(StrEnum):
    NORMAL = "normal"
    DEGRADE = "degrade"
    SAFETY_CAP = "safety_cap"


class SkepticRecommendation(StrEnum):
    ADVANCE = "advance"
    INVESTIGATE = "investigate"
    KILL = "kill"


class ChannelVerdict(StrEnum):
    REACHABLE = "reachable"
    MARGINAL = "marginal"
    UNREACHABLE = "unreachable"


class WedgeVerdict(StrEnum):
    STRONG = "strong"
    VIABLE = "viable"
    NEEDS_WORK = "needs_work"
    WEAK = "weak"


class GateAction(StrEnum):
    ADVANCE = "advance"
    ADVANCE_WITH_CAUTION = "advance_with_caution"
    INVESTIGATE = "investigate"
    RETRY = "retry"
    REVISE = "revise"
    KILL = "kill"


class WorkflowStep(StrEnum):
    ARENA_DISCOVERY = "arena_discovery"
    SIGNAL_MINING = "signal_mining"
    NORMALIZATION = "normalization"
    LANDSCAPE_RESEARCH = "landscape_research"
    SCORING = "scoring"
    SKEPTIC = "skeptic"
    WEDGE_DESIGN = "wedge_design"
    WEDGE_CRITIQUE = "wedge_critique"
    CHANNEL_VALIDATION = "channel_validation"


class AgentCheckpointStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ToolSideEffectLevel(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"
    NETWORK = "network"


class ToolCostClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
