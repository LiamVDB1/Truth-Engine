from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from truth_engine.adapters.db.migrate import upgrade_database
from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.config.settings import Settings
from truth_engine.contracts.fixtures import FixtureScenario
from truth_engine.contracts.live import LiveRunRequest
from truth_engine.contracts.temporal import TruthEngineRunInput
from truth_engine.prompts.builder import build_prompt
from truth_engine.reporting.dossier import write_dossier_artifacts
from truth_engine.services.logging import configure_logging
from truth_engine.temporal.runtime import execute_truth_engine_run, run_worker


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "init-db":
        upgrade_database(args.database_url)
        print(f"Initialized schema at {args.database_url}")
        return 0

    if args.command == "run-fixture":
        configure_logging(getattr(args, "log_level", "INFO"))
        settings = Settings(
            database_url=args.database_url,
            prompt_version=args.prompt_version,
        )
        upgrade_database(settings.database_url)
        candidate_id = FixtureScenario.from_path(Path(args.fixture)).candidate_id
        run_input = TruthEngineRunInput(
            mode="fixture",
            candidate_id=candidate_id,
            database_url=settings.database_url,
            output_dir=args.output_dir,
            prompt_version=settings.prompt_version,
            fixture_path=args.fixture,
        )
        wait_for_result = not args.no_wait
        inline_worker = False if args.no_wait else not args.no_inline_worker
        result = asyncio.run(
            execute_truth_engine_run(
                settings,
                run_input,
                inline_worker=inline_worker,
                wait_for_result=wait_for_result,
            )
        )
        if isinstance(result, str):
            print(f"Submitted workflow {result} for {candidate_id}")
            return 0
        print(f"{result.candidate_id}: {result.status}")
        return 0

    if args.command == "run-live":
        configure_logging(getattr(args, "log_level", "INFO"))
        settings = Settings(
            database_url=args.database_url,
            prompt_version=args.prompt_version,
        )
        upgrade_database(settings.database_url)
        repository = TruthEngineRepository.from_database_url(settings.database_url)
        request = _resolve_live_request(args, repository)
        run_input = TruthEngineRunInput(
            mode="live",
            candidate_id=request.candidate_id,
            database_url=settings.database_url,
            output_dir=args.output_dir,
            prompt_version=settings.prompt_version,
            request_payload=request.model_dump(mode="json"),
        )
        wait_for_result = not args.no_wait
        inline_worker = False if args.no_wait else not args.no_inline_worker
        result = asyncio.run(
            execute_truth_engine_run(
                settings,
                run_input,
                inline_worker=inline_worker,
                wait_for_result=wait_for_result,
            )
        )
        if isinstance(result, str):
            print(f"Submitted workflow {result} for {request.candidate_id}")
            return 0
        print(f"{result.candidate_id}: {result.status}")
        return 0

    if args.command == "run-worker":
        configure_logging(getattr(args, "log_level", "INFO"))
        settings = Settings(
            database_url=args.database_url,
            prompt_version=args.prompt_version,
        )
        asyncio.run(run_worker(settings))
        return 0

    if args.command == "export-dossier":
        repository = TruthEngineRepository.from_database_url(args.database_url)
        dossier = repository.load_dossier(args.candidate_id)
        if dossier is None:
            print(f"No dossier stored for {args.candidate_id}")
            return 1
        write_dossier_artifacts(dossier, Path(args.output_dir))
        print(f"Exported dossier for {args.candidate_id}")
        return 0

    if args.command == "preview-prompt":
        with Path(args.context_file).open(encoding="utf-8") as handle:
            context = json.load(handle)
        settings = Settings(prompt_version=args.prompt_version)
        bundle = build_prompt(args.agent, context=context, settings=settings)
        print(f"Prompt version: {bundle.prompt_version}")
        print(f"Prompt hash: {bundle.prompt_hash}")
        print("=== SYSTEM PROMPT ===")
        print(bundle.system_prompt)
        print("=== USER PROMPT ===")
        print(bundle.user_prompt)
        return 0

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    default_settings = Settings()
    parser = argparse.ArgumentParser(prog="truth-engine")
    subparsers = parser.add_subparsers(dest="command")

    init_db = subparsers.add_parser("init-db")
    init_db.add_argument("--database-url", default=default_settings.database_url)

    run_fixture = subparsers.add_parser("run-fixture")
    run_fixture.add_argument("--fixture", required=True)
    run_fixture.add_argument("--database-url", default=default_settings.database_url)
    run_fixture.add_argument("--output-dir", default="./out")
    run_fixture.add_argument("--prompt-version", default="live-v1")
    run_fixture.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    run_fixture.add_argument("--no-inline-worker", action="store_true")
    run_fixture.add_argument("--no-wait", action="store_true")

    run_live = subparsers.add_parser("run-live")
    run_live.add_argument("--request-file")
    run_live.add_argument("--candidate-id")
    run_live.add_argument("--database-url", default=default_settings.database_url)
    run_live.add_argument("--output-dir", default="./out")
    run_live.add_argument("--prompt-version", default="live-v1")
    run_live.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    run_live.add_argument("--no-inline-worker", action="store_true")
    run_live.add_argument("--no-wait", action="store_true")

    run_worker_parser = subparsers.add_parser("run-worker")
    run_worker_parser.add_argument("--database-url", default=default_settings.database_url)
    run_worker_parser.add_argument("--prompt-version", default="live-v1")
    run_worker_parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING"],
    )

    export_dossier = subparsers.add_parser("export-dossier")
    export_dossier.add_argument("--candidate-id", required=True)
    export_dossier.add_argument("--database-url", default=default_settings.database_url)
    export_dossier.add_argument("--output-dir", default="./out")

    preview_prompt = subparsers.add_parser("preview-prompt")
    preview_prompt.add_argument("--agent", required=True)
    preview_prompt.add_argument("--context-file", required=True)
    preview_prompt.add_argument("--prompt-version", default="live-v1")

    return parser


def _resolve_live_request(
    args: argparse.Namespace,
    repository: TruthEngineRepository,
) -> LiveRunRequest:
    if args.request_file is not None:
        request = LiveRunRequest.from_path(Path(args.request_file))
    elif args.candidate_id is not None:
        candidate = repository.get_candidate(args.candidate_id)
        if candidate is not None and candidate.request_payload is not None:
            request = LiveRunRequest.model_validate(candidate.request_payload)
        else:
            request = LiveRunRequest(candidate_id=args.candidate_id)
    else:
        request = LiveRunRequest.default()

    if args.candidate_id is not None and request.candidate_id != args.candidate_id:
        request = request.model_copy(update={"candidate_id": args.candidate_id})
    return request
