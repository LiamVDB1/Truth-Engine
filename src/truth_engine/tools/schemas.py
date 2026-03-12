from __future__ import annotations

from copy import deepcopy
from typing import Any

from truth_engine.config.settings import Settings
from truth_engine.contracts.models import RawArena, RawSignal
from truth_engine.contracts.stages import LandscapeEntry
from truth_engine.domain.enums import AgentName
from truth_engine.tools.bundles import tool_bundle_for_agent
from truth_engine.tools.registry import tool_registry


def tool_schemas_for_agent(
    agent: AgentName,
    *,
    settings: Settings | None = None,
    available_tool_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    allowed_tool_names = {
        tool.name
        for tool in tool_bundle_for_agent(
            agent,
            settings=settings,
            available_tool_names=available_tool_names,
        )
    }
    return [_tool_schema(name) for name in _ORDERED_TOOL_NAMES if name in allowed_tool_names]


def _tool_schema(name: str) -> dict[str, Any]:
    registry = tool_registry()
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": registry[name].description,
            "parameters": _tool_parameters(name),
        },
    }


def _tool_parameters(name: str) -> dict[str, Any]:
    if name == "create_arena_proposal":
        return _schema_without(RawArena.model_json_schema(), {"id"})
    if name == "edit_arena_proposal":
        return {
            "type": "object",
            "properties": {
                "arena_id": {"type": "string"},
                "changes": {"type": "object"},
            },
            "required": ["arena_id", "changes"],
            "additionalProperties": False,
        }
    if name == "remove_arena_proposal":
        return _string_arg_schema("arena_id")
    if name == "view_arena_proposals":
        return _empty_object_schema()
    if name == "add_signal":
        return _schema_without(
            RawSignal.model_json_schema(),
            {"id", "source_url_hash", "extracted_at"},
        )
    if name == "view_signal_summary":
        return _empty_object_schema()
    if name == "add_landscape_entry":
        return _schema_without(LandscapeEntry.model_json_schema(), {"id"})
    if name == "view_landscape":
        return _empty_object_schema()
    if name == "search_web":
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    if name in {"fetch_page", "extract_content", "reddit_fetch"}:
        return _string_arg_schema("url")
    if name == "reddit_search":
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                "subreddit": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    raise KeyError(f"Unsupported tool schema: {name}")


def _schema_without(schema: dict[str, Any], dropped_fields: set[str]) -> dict[str, Any]:
    result = deepcopy(schema)
    properties = dict(result.get("properties", {}))
    for field_name in dropped_fields:
        properties.pop(field_name, None)
    result["properties"] = properties
    required = [field for field in result.get("required", []) if field not in dropped_fields]
    result["required"] = required
    return result


def _string_arg_schema(argument_name: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {argument_name: {"type": "string"}},
        "required": [argument_name],
        "additionalProperties": False,
    }


def _empty_object_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


_ORDERED_TOOL_NAMES = (
    "create_arena_proposal",
    "edit_arena_proposal",
    "remove_arena_proposal",
    "view_arena_proposals",
    "add_signal",
    "view_signal_summary",
    "add_landscape_entry",
    "view_landscape",
    "search_web",
    "fetch_page",
    "extract_content",
    "reddit_search",
    "reddit_fetch",
)
