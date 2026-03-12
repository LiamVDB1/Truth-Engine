from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from truth_engine.adapters.db.migrate import upgrade_database
from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.cli.main import main
from truth_engine.contracts.models import RawArena


def test_cli_db_clear_unexplored_arenas_removes_only_proposed_rows(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)
    repository.create_candidate("cand_db", status="running")

    repository.add_arena_proposal("cand_db", _arena("arena_proposed", "Queued arena"))
    repository.add_arena_proposal(
        "cand_db",
        _arena("arena_selected", "Selected arena"),
        status="selected",
    )

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "db-clear-unexplored-arenas",
                "--database-url",
                database_url,
            ]
        )

    remaining = repository.load_arena_proposals("cand_db")

    assert exit_code == 0
    assert "Removed 1 unexplored arena" in stdout.getvalue()
    assert [arena.domain for arena in remaining] == ["Selected arena"]


def test_cli_db_reset_clears_runtime_tables(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)
    repository.create_candidate("cand_reset", status="running")
    repository.add_arena_proposal("cand_reset", _arena("arena_reset", "Reset arena"))

    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "db-reset",
                "--database-url",
                database_url,
                "--yes",
            ]
        )

    assert exit_code == 0
    assert "Reset runtime tables" in stdout.getvalue()
    assert repository.get_candidate("cand_reset") is None
    assert repository.load_arena_proposals("cand_reset") == []


def _arena(arena_id: str, domain: str) -> RawArena:
    return RawArena(
        id=arena_id,
        domain=domain,
        icp_user_role="Operations Manager",
        icp_buyer_role="VP Operations",
        geo="EU + US",
        channel_surface=["email"],
        solution_modality="saas",
        market_signals=["Strong pain"],
        signal_sources=["https://example.com/arena"],
        market_size_signal="Large market",
        expected_sales_cycle="2-4 weeks",
        rationale="Useful test arena.",
    )
