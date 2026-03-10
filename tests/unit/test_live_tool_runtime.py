from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from truth_engine.adapters.db.migrate import upgrade_database
from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.domain.enums import AgentName
from truth_engine.tools.runtime import RepositoryToolRuntime


class _FakeSearchClient:
    def search(self, query: str, limit: int) -> dict[str, object]:
        return {
            "status": "ok",
            "query": query,
            "results": [
                {
                    "title": "Ops pain thread",
                    "url": "https://example.com/ops",
                    "snippet": "Warehouse managers complain about shipment exceptions.",
                }
            ][:limit],
        }


def test_search_web_uses_live_search_adapter() -> None:
    with TemporaryDirectory() as temp_dir:
        database_path = Path(temp_dir) / "truth_engine.db"
        database_url = f"sqlite:///{database_path}"
        upgrade_database(database_url)
        repository = TruthEngineRepository.from_database_url(database_url)
        runtime = RepositoryToolRuntime(repository, search_client=_FakeSearchClient())

        result = runtime.invoke(
            AgentName.ARENA_SCOUT,
            "search_web",
            {"query": "warehouse ops pain", "limit": 1},
        )

    assert result["status"] == "ok"
    assert result["query"] == "warehouse ops pain"
    assert result["results"][0]["url"] == "https://example.com/ops"


def test_search_web_without_adapter_fails_closed() -> None:
    with TemporaryDirectory() as temp_dir:
        database_path = Path(temp_dir) / "truth_engine.db"
        database_url = f"sqlite:///{database_path}"
        upgrade_database(database_url)
        repository = TruthEngineRepository.from_database_url(database_url)
        runtime = RepositoryToolRuntime(repository)

        result = runtime.invoke(
            AgentName.ARENA_SCOUT,
            "search_web",
            {"query": "warehouse ops pain", "limit": 1},
        )

    assert result["status"] == "unavailable"
    assert result["tool"] == "search_web"
