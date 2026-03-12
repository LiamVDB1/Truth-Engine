from __future__ import annotations

from typing import Any, cast

from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.contracts.models import RawArena, RawSignal
from truth_engine.contracts.stages import LandscapeEntry
from truth_engine.domain.enums import AgentName
from truth_engine.tools.bundles import tool_bundle_for_agent


class RepositoryToolRuntime:
    def __init__(
        self,
        repository: TruthEngineRepository,
        *,
        search_client: Any | None = None,
        page_fetcher: Any | None = None,
        content_extractor: Any | None = None,
        reddit_client: Any | None = None,
    ):
        self.repository = repository
        self.search_client = search_client
        self.page_fetcher = page_fetcher
        self.content_extractor = content_extractor
        self.reddit_client = reddit_client

    def invoke(self, agent: AgentName, tool_name: str, payload: dict[str, Any]) -> Any:
        allowed_tools = self.permitted_tool_names(agent)
        if tool_name not in allowed_tools:
            raise PermissionError(f"{agent.value} is not allowed to call {tool_name}")

        handler = getattr(self, f"_handle_{tool_name}", None)
        if handler is None:
            raise KeyError(f"No handler registered for {tool_name}")
        return handler(payload)

    def permitted_tool_names(self, agent: AgentName) -> set[str]:
        return {tool.name for tool in tool_bundle_for_agent(agent)}

    def available_tool_names(self, agent: AgentName) -> set[str]:
        tool_names = self.permitted_tool_names(agent)
        if self.search_client is None:
            tool_names.discard("search_web")
        if self.page_fetcher is None:
            tool_names.discard("fetch_page")
        if self.content_extractor is None:
            tool_names.discard("extract_content")
        if self.reddit_client is None:
            tool_names.discard("reddit_search")
            tool_names.discard("reddit_fetch")
        return tool_names

    def _handle_create_arena_proposal(self, payload: dict[str, Any]) -> dict[str, str]:
        return self.repository.add_arena_proposal(
            candidate_id=str(payload["candidate_id"]),
            arena=_coerce_model(payload["arena"], RawArena),
        )

    def _handle_edit_arena_proposal(self, payload: dict[str, Any]) -> dict[str, str]:
        return self.repository.update_arena_proposal(
            candidate_id=str(payload["candidate_id"]),
            arena_id=str(payload["arena_id"]),
            changes=dict(payload["changes"]),
        )

    def _handle_remove_arena_proposal(self, payload: dict[str, Any]) -> dict[str, str]:
        return self.repository.remove_arena_proposal(
            candidate_id=str(payload["candidate_id"]),
            arena_id=str(payload["arena_id"]),
        )

    def _handle_view_arena_proposals(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        return self.repository.list_arena_proposals(candidate_id=str(payload["candidate_id"]))

    def _handle_add_signal(self, payload: dict[str, Any]) -> dict[str, str]:
        return self.repository.add_raw_signal(
            candidate_id=str(payload["candidate_id"]),
            signal=_coerce_model(payload["signal"], RawSignal),
        )

    def _handle_view_signal_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.repository.signal_summary(candidate_id=str(payload["candidate_id"]))

    def _handle_add_landscape_entry(self, payload: dict[str, Any]) -> dict[str, str]:
        entry = _coerce_model(payload["entry"], LandscapeEntry)
        return self.repository.add_landscape_entry(
            candidate_id=str(payload["candidate_id"]),
            entry=entry,
        )

    def _handle_view_landscape(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        return self.repository.landscape_summary(candidate_id=str(payload["candidate_id"]))

    def _handle_search_web(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.search_client is None:
            return _unavailable_tool("search_web")
        result = self.search_client.search(
            query=str(payload["query"]),
            limit=int(payload.get("limit", 5)),
        )
        return cast(dict[str, Any], result)

    def _handle_fetch_page(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.page_fetcher is None:
            return _unavailable_tool("fetch_page")
        return cast(dict[str, Any], self.page_fetcher.fetch_page(str(payload["url"])))

    def _handle_extract_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.content_extractor is None:
            return _unavailable_tool("extract_content")
        return cast(dict[str, Any], self.content_extractor.extract_content(str(payload["url"])))

    def _handle_reddit_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.reddit_client is None:
            return _unavailable_tool("reddit_search")
        result = self.reddit_client.search(
            query=str(payload["query"]),
            limit=int(payload.get("limit", 5)),
            subreddit=(str(payload["subreddit"]) if payload.get("subreddit") is not None else None),
        )
        return cast(dict[str, Any], result)

    def _handle_reddit_fetch(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.reddit_client is None:
            return _unavailable_tool("reddit_fetch")
        return cast(dict[str, Any], self.reddit_client.fetch(str(payload["url"])))


def _coerce_model(value: Any, model_type: type[Any]) -> Any:
    if isinstance(value, model_type):
        return value
    return model_type.model_validate(value)


def _unavailable_tool(tool_name: str) -> dict[str, str]:
    return {
        "status": "unavailable",
        "tool": tool_name,
        "reason": "No live adapter is configured for this tool in the current runtime.",
    }
