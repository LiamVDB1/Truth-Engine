from __future__ import annotations

from truth_engine.config.settings import Settings
from truth_engine.domain.enums import AgentName
from truth_engine.tools.registry import tool_registry
from truth_engine.tools.specs import ToolSpec

_AGENT_TOOL_NAMES: dict[AgentName, tuple[str, ...]] = {
    AgentName.ARENA_SCOUT: (
        "create_arena_proposal",
        "edit_arena_proposal",
        "remove_arena_proposal",
        "view_arena_proposals",
        "search_web",
        "reddit_search",
    ),
    AgentName.SIGNAL_SCOUT: (
        "add_signal",
        "view_signal_summary",
        "search_web",
        "fetch_page",
        "extract_content",
        "reddit_search",
        "reddit_fetch",
    ),
    AgentName.LANDSCAPE_SCOUT: (
        "add_landscape_entry",
        "view_landscape",
        "search_web",
        "fetch_page",
        "extract_content",
    ),
}


def tool_bundle_for_agent(
    agent_name: AgentName,
    *,
    settings: Settings | None = None,
    available_tool_names: set[str] | None = None,
) -> tuple[ToolSpec, ...]:
    registry = tool_registry()
    tool_names = _AGENT_TOOL_NAMES.get(agent_name, ())
    if available_tool_names is not None:
        tool_names = tuple(name for name in tool_names if name in available_tool_names)
    elif settings is not None:
        tool_names = tuple(name for name in tool_names if _tool_enabled_in_settings(name, settings))
    return tuple(registry[name] for name in tool_names)


def _tool_enabled_in_settings(tool_name: str, settings: Settings) -> bool:
    if tool_name == "search_web":
        return settings.has_serper_search()
    if tool_name in {"reddit_search", "reddit_fetch"}:
        return settings.has_reddit_tools()
    return True
