from __future__ import annotations

from functools import lru_cache

from truth_engine.domain.enums import ToolCostClass, ToolSideEffectLevel
from truth_engine.tools.specs import ToolSpec


def _tool(
    name: str,
    description: str,
    side_effect_level: ToolSideEffectLevel,
    cost_class: ToolCostClass,
    adapter_key: str,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        side_effect_level=side_effect_level,
        cost_class=cost_class,
        adapter_key=adapter_key,
    )


@lru_cache(maxsize=1)
def tool_registry() -> dict[str, ToolSpec]:
    tools = [
        _tool(
            "create_arena_proposal",
            "Persist a new arena proposal and apply v0.1 fingerprint dedup.",
            ToolSideEffectLevel.WRITE,
            ToolCostClass.LOW,
            "arena_repository.create",
        ),
        _tool(
            "edit_arena_proposal",
            "Update an existing arena proposal.",
            ToolSideEffectLevel.WRITE,
            ToolCostClass.LOW,
            "arena_repository.update",
        ),
        _tool(
            "remove_arena_proposal",
            "Delete an arena proposal from the working set.",
            ToolSideEffectLevel.WRITE,
            ToolCostClass.LOW,
            "arena_repository.delete",
        ),
        _tool(
            "view_arena_proposals",
            "Read current arena proposals.",
            ToolSideEffectLevel.READ_ONLY,
            ToolCostClass.LOW,
            "arena_repository.list",
        ),
        _tool(
            "add_signal",
            "Persist a raw signal with URL dedup enforcement.",
            ToolSideEffectLevel.WRITE,
            ToolCostClass.LOW,
            "signal_repository.add",
        ),
        _tool(
            "view_signal_summary",
            "Read signal counts and emerging themes.",
            ToolSideEffectLevel.READ_ONLY,
            ToolCostClass.LOW,
            "signal_repository.summary",
        ),
        _tool(
            "add_landscape_entry",
            "Persist a landscape finding.",
            ToolSideEffectLevel.WRITE,
            ToolCostClass.LOW,
            "landscape_repository.add",
        ),
        _tool(
            "view_landscape",
            "Read the current landscape findings.",
            ToolSideEffectLevel.READ_ONLY,
            ToolCostClass.LOW,
            "landscape_repository.summary",
        ),
        _tool(
            "search_web",
            "Run a web search for an arena, signal, or landscape query.",
            ToolSideEffectLevel.NETWORK,
            ToolCostClass.MEDIUM,
            "search.serper",
        ),
        _tool(
            "fetch_page",
            "Fetch a page from the public web.",
            ToolSideEffectLevel.NETWORK,
            ToolCostClass.MEDIUM,
            "scraping.fetch",
        ),
        _tool(
            "extract_content",
            "Extract main content from HTML.",
            ToolSideEffectLevel.NETWORK,
            ToolCostClass.LOW,
            "scraping.extract",
        ),
        _tool(
            "reddit_search",
            "Discover Reddit posts and threads relevant to a query.",
            ToolSideEffectLevel.NETWORK,
            ToolCostClass.MEDIUM,
            "reddit.search",
        ),
        _tool(
            "reddit_fetch",
            "Fetch Reddit thread or post details.",
            ToolSideEffectLevel.NETWORK,
            ToolCostClass.MEDIUM,
            "reddit.fetch",
        ),
    ]
    return {tool.name: tool for tool in tools}
