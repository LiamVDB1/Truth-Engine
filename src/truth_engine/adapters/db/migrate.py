from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from truth_engine.adapters.db.schema import metadata


def upgrade_database(database_url: str) -> None:
    config = Config(str(_repo_root() / "alembic.ini"))
    config.set_main_option("script_location", str(_repo_root() / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    _ensure_runtime_schema(database_url)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _ensure_runtime_schema(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        if "candidate" in inspect(engine).get_table_names():
            return
        metadata.create_all(engine)
    finally:
        engine.dispose()
