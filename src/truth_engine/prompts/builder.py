from __future__ import annotations

import json
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel, ConfigDict

from truth_engine.config.settings import Settings
from truth_engine.contracts.stages import (
    ArenaEvaluation,
    ArenaSearchResult,
    ChannelValidation,
    LandscapeEntry,
    LandscapeReport,
    NormalizationResult,
    ScoredCandidate,
    ScoringResult,
    SignalMiningResult,
    SkepticReport,
    WedgeCritique,
    WedgeEvaluation,
    WedgeHypothesis,
    WedgeProposal,
)
from truth_engine.domain.enums import AgentName
from truth_engine.tools.bundles import tool_bundle_for_agent

_SHARED_FILES = (
    "invariants.md",
    "evidence_policy.md",
    "tool_policy.md",
    "output_policy.md",
)

_CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "ArenaEvaluation": ArenaEvaluation,
    "ArenaSearchResult": ArenaSearchResult,
    "ChannelValidation": ChannelValidation,
    "LandscapeEntry": LandscapeEntry,
    "LandscapeReport": LandscapeReport,
    "NormalizationResult": NormalizationResult,
    "ScoredCandidate": ScoredCandidate,
    "ScoringResult": ScoringResult,
    "SignalMiningResult": SignalMiningResult,
    "SkepticReport": SkepticReport,
    "WedgeCritique": WedgeCritique,
    "WedgeEvaluation": WedgeEvaluation,
    "WedgeHypothesis": WedgeHypothesis,
    "WedgeProposal": WedgeProposal,
}


class PromptBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    system_prompt: str
    user_prompt: str
    prompt_version: str
    prompt_hash: str


def build_prompt(
    agent_id: str,
    context: dict[str, Any],
    settings: Settings | None = None,
    available_tool_names: set[str] | None = None,
) -> PromptBundle:
    prompt_root = Path(__file__).resolve().parent
    agent_name = AgentName(agent_id)
    active_settings = settings or Settings()

    shared_sections = [
        _read_text(prompt_root / "shared" / file_name) for file_name in _SHARED_FILES
    ]
    role_text = _read_text(prompt_root / "agents" / agent_id / "role.md")
    founder_constraints_section = _build_founder_constraints_section(
        context.get("founder_constraints")
    )
    output_contract = context.get("output_contract")
    tools = tool_bundle_for_agent(
        agent_name,
        settings=active_settings,
        available_tool_names=available_tool_names,
    )
    role_text = _adapt_role_text(role_text, {tool.name for tool in tools})

    system_sections = [
        "# Truth Engine V0.1",
        *shared_sections,
        "## Agent Role",
        role_text,
        founder_constraints_section,
        _build_tool_manifest(tools),
        _build_output_contract_section(output_contract),
    ]
    system_prompt = "\n\n".join(section.strip() for section in system_sections if section.strip())
    user_prompt = _build_user_prompt(agent_id=agent_id, context=context)
    prompt_hash = sha256(f"{system_prompt}\n\n{user_prompt}".encode()).hexdigest()[:16]

    return PromptBundle(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        prompt_version=active_settings.prompt_version,
        prompt_hash=prompt_hash,
    )


def _build_user_prompt(*, agent_id: str, context: dict[str, Any]) -> str:
    runtime_context = _normalize_for_prompt(context)
    candidate_id = runtime_context.get("candidate_id", "unknown")
    stage = runtime_context.get("stage", "unknown")
    output_contract = runtime_context.get("output_contract", "unknown")

    sections = [
        "# Assignment",
        f"You are executing `{agent_id}` for candidate `{candidate_id}` at stage `{stage}`.",
        f"Produce exactly one `{output_contract}` payload.",
    ]

    budget_mode = runtime_context.get("budget_mode")
    if budget_mode == "degrade":
        sections.append(
            "## ⚠️ Budget Pressure\n"
            "This candidate is **over the €5 target budget**. "
            "Produce tighter, more focused output. "
            "Skip marginal searches and low-confidence exploration. "
            "Prioritize the highest-signal evidence you already have."
        )
    elif budget_mode == "safety_cap":
        sections.append(
            "## 🛑 Critical Budget — Safety Cap\n"
            "This candidate is **approaching the €7 safety cap**. "
            "Produce the absolute minimum viable output. "
            "Do NOT run any optional tool calls. "
            "Work only from existing context."
        )

    past_learnings = runtime_context.get("past_learnings")
    if isinstance(past_learnings, list) and past_learnings:
        learning_lines = "\n".join(f"- {entry}" for entry in past_learnings[:5])
        sections.append(
            "## Past Learnings\n"
            "These insights were extracted from previous candidates. "
            "Use them to avoid repeating mistakes:\n"
            f"{learning_lines}"
        )

    sections.extend(
        [
            "## Runtime Context (JSON)",
            "```json\n"
            + json.dumps(runtime_context, indent=2, sort_keys=True, ensure_ascii=True)
            + "\n```",
        ]
    )
    return "\n\n".join(sections)


def _build_tool_manifest(tools: tuple[Any, ...]) -> str:
    if not tools:
        return (
            "## Allowed Tools\n"
            "This agent has no direct tool access. Work only from the provided context."
        )

    lines = ["## Allowed Tools", "Call only the tools listed below when they are necessary."]
    for tool in tools:
        lines.append(
            "- "
            f"`{tool.name}`: {tool.description} "
            f"(side_effect={tool.side_effect_level.value}, cost={tool.cost_class.value})"
        )
    return "\n".join(lines)


def _build_founder_constraints_section(founder_constraints: Any) -> str:
    normalized = _normalize_for_prompt(founder_constraints)
    if not isinstance(normalized, dict) or not normalized:
        return ""

    lines = [
        "## Founder Constraint Interpretation",
        (
            "Treat the founder constraints as constraints on the solution we build, "
            "not on the customer's industry."
        ),
    ]

    v1_filter = normalized.get("v1_filter")
    if v1_filter == "software_first":
        lines.append(
            "- `software_first` means the proposed outcome must be a software product, "
            "software tool, or software-led automation."
        )

    solution_modalities = _format_constraint_list(normalized.get("solution_modalities"))
    if solution_modalities:
        lines.append(f"- Preferred solution modalities: {solution_modalities}.")

    excluded_business_models = _format_constraint_list(normalized.get("excluded_business_models"))
    if excluded_business_models:
        lines.append(f"- Excluded business models: {excluded_business_models}.")

    if normalized.get("target_market") == "any":
        lines.append(
            "- The target market is unrestricted. Restaurants, retail, healthcare, "
            "logistics, construction, and other non-software verticals are valid "
            "when the delivered solution is software."
        )

    lines.extend(
        [
            '- Valid example: "software for connecting restaurant owners with suppliers."',
            '- Invalid example: "run a restaurant at this location."',
        ]
    )
    return "\n".join(lines)


def _format_constraint_list(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    return ", ".join(f"`{item}`" for item in value if isinstance(item, str) and item)


def _adapt_role_text(role_text: str, available_tool_names: set[str]) -> str:
    adapted = role_text
    if "reddit_search" not in available_tool_names:
        adapted = adapted.replace(
            _ARENA_REDDIT_SEARCH_BLOCK,
            _ARENA_WEB_ONLY_SEARCH_BLOCK,
        )
        adapted = adapted.replace(
            _SIGNAL_REDDIT_LINE,
            _SIGNAL_WEB_ONLY_LINE,
        )
        adapted = adapted.replace(
            "4. Use `reddit_fetch` for Reddit threads with rich discussion.\n",
            "",
        )
        adapted = adapted.replace(
            "The ICP is reachable through public channels (Reddit, LinkedIn, email)",
            "The ICP is reachable through public channels (LinkedIn, email, forums, communities)",
        )
    return adapted


_ARENA_REDDIT_SEARCH_BLOCK = "\n".join(
    [
        "1. **Reddit** (`reddit_search`): subreddits where the ICP discusses operational pain,",
        "tool complaints, workflow frustrations.",
        "2. **Web search** (`search_web`): job postings for the ICP role",
        "(reveals tooling and budget), industry forums, community discussions.",
        "3. **Web search**: G2/Capterra/review sites for existing tools in the space",
        "(reveals spend and dissatisfaction).",
    ]
)

_ARENA_WEB_ONLY_SEARCH_BLOCK = "\n".join(
    [
        "Search breadth-first across public web sources in this priority order:",
        "1. **Web search** (`search_web`): job postings for the ICP role",
        "(reveals tooling and budget), industry forums, community discussions.",
        "2. **Web search**: G2/Capterra/review sites for existing tools in the space",
        "(reveals spend and dissatisfaction).",
        "3. **Public communities** reachable from web search results when available.",
    ]
)

_SIGNAL_REDDIT_LINE = (
    "2. Use `search_web` and `reddit_search` to find relevant discussions, complaints, "
    "tool reviews, job postings."
)

_SIGNAL_WEB_ONLY_LINE = (
    "2. Use `search_web` to find relevant discussions, complaints, tool reviews, job postings."
)


def _build_output_contract_section(contract_name: Any) -> str:
    if not isinstance(contract_name, str) or not contract_name:
        return "## Output Contract\nNo explicit output contract was provided."

    contract_model = _CONTRACT_MODELS.get(contract_name)
    if contract_model is None:
        return f"## Output Contract\nReturn exactly one JSON object matching `{contract_name}`."

    lines = [
        "## Output Contract",
        f"Return exactly one JSON object matching `{contract_name}`.",
        "Do not wrap the response in Markdown.",
        "",
        "### Top-level Fields",
    ]
    lines.extend(_describe_model_fields(contract_model))

    nested_models = _nested_contract_models(contract_model)
    if nested_models:
        lines.extend(["", "### Referenced Nested Models"])
        for nested_model in nested_models:
            lines.append(f"`{nested_model.__name__}`")
            lines.extend(_describe_model_fields(nested_model))

    return "\n".join(lines)


def _describe_model_fields(model_type: type[BaseModel]) -> list[str]:
    lines: list[str] = []
    for field_name, field_info in model_type.model_fields.items():
        lines.append(f"- `{field_name}`: {_type_name(field_info.annotation)}")
    return lines


def _nested_contract_models(model_type: type[BaseModel]) -> list[type[BaseModel]]:
    nested: list[type[BaseModel]] = []
    seen: set[type[BaseModel]] = {model_type}
    for field_info in model_type.model_fields.values():
        for nested_model in _extract_model_types(field_info.annotation):
            if nested_model not in seen:
                seen.add(nested_model)
                nested.append(nested_model)
    return nested


def _extract_model_types(annotation: Any) -> list[type[BaseModel]]:
    origin = get_origin(annotation)
    if origin is None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return [annotation]
        return []
    nested: list[type[BaseModel]] = []
    for arg in get_args(annotation):
        nested.extend(_extract_model_types(arg))
    return nested


def _type_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is None:
        if annotation is type(None):
            return "None"
        if isinstance(annotation, type):
            return annotation.__name__
        return str(annotation)

    args = [arg for arg in get_args(annotation) if arg is not type(None)]
    if origin in (list, tuple, set):
        inner = _type_name(args[0]) if args else "Any"
        return f"{origin.__name__}[{inner}]"
    if origin is dict:
        key_name = _type_name(args[0]) if len(args) > 0 else "Any"
        value_name = _type_name(args[1]) if len(args) > 1 else "Any"
        return f"dict[{key_name}, {value_name}]"

    union_name = getattr(origin, "__name__", str(origin))
    if union_name == "Union" or "UnionType" in union_name:
        return " | ".join(_type_name(arg) for arg in get_args(annotation))

    inner = ", ".join(_type_name(arg) for arg in args)
    return f"{union_name}[{inner}]"


def _normalize_for_prompt(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize_for_prompt(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _normalize_for_prompt(value[key]) for key in sorted(value)}
    if isinstance(value, list | tuple):
        return [_normalize_for_prompt(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()
