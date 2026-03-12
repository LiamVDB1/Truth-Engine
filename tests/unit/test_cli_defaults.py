from __future__ import annotations

from truth_engine.cli.main import _build_parser


def test_cli_uses_settings_database_default_and_out_dir() -> None:
    parser = _build_parser()

    run_live_args = parser.parse_args(["run-live"])
    export_args = parser.parse_args(["export-dossier", "--candidate-id", "cand_123"])

    assert run_live_args.database_url
    assert run_live_args.output_dir == "./out"
    assert export_args.database_url
    assert export_args.output_dir == "./out"
