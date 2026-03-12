from __future__ import annotations

import argparse
from pathlib import Path

from truth_engine.adapters.db.migrate import upgrade_database
from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.cli.main import _build_parser, _resolve_live_request
from truth_engine.contracts.live import FounderConstraints, LiveRunRequest


def test_cli_uses_settings_database_default_and_out_dir() -> None:
    parser = _build_parser()

    run_live_args = parser.parse_args(["run-live"])
    run_fixture_args = parser.parse_args(
        [
            "run-fixture",
            "--fixture",
            "tests/fixtures/workflows/gate_b_retry_kill.json",
        ]
    )
    export_args = parser.parse_args(["export-dossier", "--candidate-id", "cand_123"])

    assert run_live_args.database_url
    assert run_fixture_args.database_url != run_live_args.database_url
    assert run_live_args.output_dir == "./out"
    assert export_args.database_url
    assert export_args.output_dir == "./out"


def test_run_live_accepts_candidate_id_override() -> None:
    parser = _build_parser()

    run_live_args = parser.parse_args(["run-live", "--candidate-id", "run_resume_123"])

    assert run_live_args.candidate_id == "run_resume_123"


def test_resolve_live_request_reuses_stored_request_payload(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'truth_engine.db'}"
    upgrade_database(database_url)
    repository = TruthEngineRepository.from_database_url(database_url)
    request = LiveRunRequest(
        candidate_id="run_resume_123",
        founder_constraints=FounderConstraints(geo_preference="DACH"),
    )
    repository.create_candidate(
        "run_resume_123",
        status="running",
        request_payload=request.model_dump(mode="json"),
    )

    resolved = _resolve_live_request(
        argparse.Namespace(request_file=None, candidate_id="run_resume_123"),
        repository,
    )

    assert resolved.candidate_id == "run_resume_123"
    assert resolved.founder_constraints.geo_preference == "DACH"
