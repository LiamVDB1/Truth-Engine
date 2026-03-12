from __future__ import annotations

from truth_engine.cli.main import _build_parser


def test_cli_exposes_temporal_worker_command() -> None:
    parser = _build_parser()

    args = parser.parse_args(["run-worker"])

    assert args.command == "run-worker"
