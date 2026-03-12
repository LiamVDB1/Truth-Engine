from __future__ import annotations

from typing import Any, cast

from pydantic import ValidationError

from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.contracts.models import RawArena, RawSignal
from truth_engine.contracts.stages import LandscapeEntry
from truth_engine.domain.enums import AgentName
from truth_engine.tools.bundles import tool_bundle_for_agent

_SIGNAL_SOURCE_TYPE_ALIASES = {
    "g2_review": "review_site",
    "capterra_review": "review_site",
    "job_post": "job_posting",
    "job_postings": "job_posting",
    "forums": "forum",
    "docs": "documentation",
}

_SIGNAL_RELIABILITY_CAPS = {
    "app_review": 0.40,
    "blog": 0.35,
    "documentation": 0.30,
    "forum": 0.40,
    "github_issue": 0.30,
    "job_posting": 0.50,
    "news": 0.45,
    "reddit": 0.40,
    "review_site": 0.40,
    "youtube": 0.30,
}

_SPEND_EVIDENCE_HINTS = (
    "$",
    "budget",
    "consultant",
    "contractor",
    "cost us",
    "hiring",
    "license",
    "paid",
    "paying",
    "payroll",
    "pricing",
    "salary",
    "seat",
    "spend",
    "subscription",
    "vendor",
)


class RepositoryToolRuntime:
    def __init__(
        self,
        repository: TruthEngineRepository,
        *,
        search_client: Any | None = None,
        web_client: Any | None = None,
        reddit_client: Any | None = None,
    ):
        self.repository = repository
        self.search_client = search_client
        self.web_client = web_client
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
        if self.web_client is None:
            tool_names.discard("read_page")
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

    def _handle_add_signal(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            signal = _coerce_model(payload["signal"], RawSignal)
            normalized_signal, warnings = _normalize_raw_signal(signal)
        except (ValidationError, ValueError) as error:
            return {
                "status": "invalid",
                "reason": str(error),
            }

        result: dict[str, Any] = dict(
            self.repository.add_raw_signal(
                candidate_id=str(payload["candidate_id"]),
                signal=normalized_signal,
            )
        )
        result["applied_source_type"] = normalized_signal.source_type
        result["applied_reliability_score"] = normalized_signal.reliability_score
        result["proof_of_spend"] = normalized_signal.proof_of_spend
        if warnings:
            result["warnings"] = warnings
        return result

    def _handle_view_signal_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.repository.signal_summary(candidate_id=str(payload["candidate_id"]))

    def _handle_add_landscape_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            entry = _coerce_model(payload["entry"], LandscapeEntry)
        except (ValidationError, ValueError) as error:
            return {
                "status": "invalid",
                "reason": str(error),
            }
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

    def _handle_read_page(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.web_client is None:
            return _unavailable_tool("read_page")
        return cast(
            dict[str, Any],
            self.web_client.read_page(
                str(payload["url"]),
                include_raw_html=bool(payload.get("include_raw_html", False)),
            ),
        )

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


def _normalize_raw_signal(signal: RawSignal) -> tuple[RawSignal, list[str]]:
    source_type = _normalize_signal_source_type(signal.source_type)
    warnings: list[str] = []
    updates: dict[str, Any] = {}

    if source_type != signal.source_type:
        updates["source_type"] = source_type
        warnings.append(f"Normalized source_type from `{signal.source_type}` to `{source_type}`.")

    reliability_cap = _SIGNAL_RELIABILITY_CAPS[source_type]
    if signal.reliability_score > reliability_cap:
        updates["reliability_score"] = reliability_cap
        warnings.append(
            f"Capped reliability_score at {reliability_cap:.2f} for source_type `{source_type}`."
        )

    if signal.proof_of_spend and not _has_explicit_spend_evidence(signal.verbatim_quote):
        updates["proof_of_spend"] = False
        warnings.append(
            "Downgraded proof_of_spend to false because the quote does not "
            "explicitly indicate spending."
        )

    if not updates:
        return signal, warnings
    return signal.model_copy(update=updates), warnings


def _normalize_signal_source_type(source_type: str) -> str:
    normalized = source_type.strip().lower().replace("-", "_").replace(" ", "_")
    canonical = _SIGNAL_SOURCE_TYPE_ALIASES.get(normalized, normalized)
    if canonical not in _SIGNAL_RELIABILITY_CAPS:
        supported = ", ".join(sorted(_SIGNAL_RELIABILITY_CAPS))
        raise ValueError(f"Unsupported source_type `{source_type}`. Supported values: {supported}.")
    return canonical


def _has_explicit_spend_evidence(verbatim_quote: str) -> bool:
    quote_lower = verbatim_quote.lower()
    return any(hint in quote_lower for hint in _SPEND_EVIDENCE_HINTS)


def _unavailable_tool(tool_name: str) -> dict[str, str]:
    return {
        "status": "unavailable",
        "tool": tool_name,
        "reason": "No live adapter is configured for this tool in the current runtime.",
    }
