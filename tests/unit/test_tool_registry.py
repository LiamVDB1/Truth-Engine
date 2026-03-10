from truth_engine.domain.enums import AgentName
from truth_engine.tools.bundles import tool_bundle_for_agent
from truth_engine.tools.registry import tool_registry


def test_registry_contains_concrete_v0_tools() -> None:
    registry = tool_registry()

    assert "create_arena_proposal" in registry
    assert "add_signal" in registry
    assert "add_landscape_entry" in registry
    assert "search_web" in registry


def test_arena_scout_bundle_contains_only_expected_tools() -> None:
    bundle = tool_bundle_for_agent(AgentName.ARENA_SCOUT)

    assert [tool.name for tool in bundle] == [
        "create_arena_proposal",
        "edit_arena_proposal",
        "remove_arena_proposal",
        "view_arena_proposals",
        "search_web",
        "reddit_search",
    ]


def test_landscape_scout_bundle_includes_landscape_tools() -> None:
    bundle = tool_bundle_for_agent(AgentName.LANDSCAPE_SCOUT)

    names = {tool.name for tool in bundle}
    assert {
        "add_landscape_entry",
        "view_landscape",
        "search_web",
        "fetch_page",
        "extract_content",
    } <= names
