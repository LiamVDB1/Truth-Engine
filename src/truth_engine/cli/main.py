from __future__ import annotations

import argparse
import json
from pathlib import Path

from truth_engine.activities.fixtures import FixtureActivityBundle
from truth_engine.activities.live import LiveActivityBundle
from truth_engine.adapters.db.migrate import upgrade_database
from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.adapters.llm.litellm_runner import LiteLLMAgentRunner
from truth_engine.adapters.reddit.praw_client import RedditSearchClient
from truth_engine.adapters.scraping.web import WebFetchClient
from truth_engine.adapters.search.serper import SerperSearchClient
from truth_engine.config.settings import Settings
from truth_engine.contracts.live import LiveRunRequest
from truth_engine.prompts.builder import build_prompt
from truth_engine.reporting.dossier import write_dossier_artifacts
from truth_engine.services.logging import configure_logging
from truth_engine.services.run_trace import RunTraceWriter
from truth_engine.tools.runtime import RepositoryToolRuntime
from truth_engine.workflows.candidate import CandidateWorkflowRunner


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
        repository = TruthEngineRepository.from_database_url(settings.database_url)
        fixture_activities = FixtureActivityBundle.from_path(Path(args.fixture))
        trace_writer = RunTraceWriter.create(
            output_dir=Path(args.output_dir),
            candidate_id=fixture_activities.candidate_id,
            mode="fixture",
            prompt_version=settings.prompt_version,
        )
        runner = CandidateWorkflowRunner(
            repository=repository,
            settings=settings,
            trace_writer=trace_writer,
        )
        outcome = runner.run(fixture_activities)
        if outcome.dossier is not None:
            json_path, markdown_path = write_dossier_artifacts(
                outcome.dossier, Path(args.output_dir)
            )
            trace_writer.artifact(label="dossier_json", path=json_path)
            trace_writer.artifact(label="dossier_markdown", path=markdown_path)
        print(f"{outcome.candidate_id}: {outcome.status}")
        return 0

    if args.command == "run-live":
        configure_logging(getattr(args, "log_level", "INFO"))
        settings = Settings(
            database_url=args.database_url,
            prompt_version=args.prompt_version,
        )
        upgrade_database(settings.database_url)
        repository = TruthEngineRepository.from_database_url(settings.database_url)
        tool_runtime = _build_live_tool_runtime(repository, settings)
        request = (
            LiveRunRequest.from_path(Path(args.request_file))
            if args.request_file is not None
            else LiveRunRequest.default()
        )
        trace_writer = RunTraceWriter.create(
            output_dir=Path(args.output_dir),
            candidate_id=request.candidate_id,
            mode="live",
            prompt_version=settings.prompt_version,
        )
        live_activities = LiveActivityBundle(
            request=request,
            repository=repository,
            settings=settings,
            agent_runner=LiteLLMAgentRunner(settings=settings, trace_writer=trace_writer),
            tool_runtime=tool_runtime,
        )
        runner = CandidateWorkflowRunner(
            repository=repository,
            settings=settings,
            tool_runtime=tool_runtime,
            trace_writer=trace_writer,
        )
        outcome = runner.run(live_activities)
        if outcome.dossier is not None:
            json_path, markdown_path = write_dossier_artifacts(
                outcome.dossier, Path(args.output_dir)
            )
            trace_writer.artifact(label="dossier_json", path=json_path)
            trace_writer.artifact(label="dossier_markdown", path=markdown_path)
        print(f"{outcome.candidate_id}: {outcome.status}")
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

    run_live = subparsers.add_parser("run-live")
    run_live.add_argument("--request-file")
    run_live.add_argument("--database-url", default=default_settings.database_url)
    run_live.add_argument("--output-dir", default="./out")
    run_live.add_argument("--prompt-version", default="live-v1")
    run_live.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])

    export_dossier = subparsers.add_parser("export-dossier")
    export_dossier.add_argument("--candidate-id", required=True)
    export_dossier.add_argument("--database-url", default=default_settings.database_url)
    export_dossier.add_argument("--output-dir", default="./out")

    preview_prompt = subparsers.add_parser("preview-prompt")
    preview_prompt.add_argument("--agent", required=True)
    preview_prompt.add_argument("--context-file", required=True)
    preview_prompt.add_argument("--prompt-version", default="live-v1")

    return parser


def _build_live_tool_runtime(
    repository: TruthEngineRepository,
    settings: Settings,
) -> RepositoryToolRuntime:
    fetch_client = WebFetchClient(settings)
    search_client = SerperSearchClient(settings) if settings.has_serper_search() else None
    reddit_client = RedditSearchClient(settings) if settings.has_reddit_tools() else None
    return RepositoryToolRuntime(
        repository,
        search_client=search_client,
        page_fetcher=fetch_client,
        content_extractor=fetch_client,
        reddit_client=reddit_client,
    )
