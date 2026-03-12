from __future__ import annotations

from pathlib import Path

from truth_engine.prompts.builder import PromptBundle
from truth_engine.services.run_trace import RunTraceWriter


def test_run_trace_writer_appends_markdown_events(tmp_path: Path) -> None:
    writer = RunTraceWriter.create(
        output_dir=tmp_path,
        candidate_id="cand_demo",
        mode="live",
        prompt_version="v-test",
    )

    writer.stage_start(stage="Arena Discovery", agent="arena_scout")
    writer.llm_round(
        agent="arena_scout",
        model="minimax-m2.5",
        round_num=1,
        prompt=PromptBundle(
            system_prompt="system prompt",
            user_prompt="user prompt",
            prompt_version="v-test",
            prompt_hash="hash123",
        ),
        tool_choice="auto",
        tool_names=["search_web", "create_arena_proposal"],
    )
    writer.tool_call(
        agent="arena_scout",
        round_num=1,
        tool_name="search_web",
        arguments={"query": "ops software"},
    )
    writer.tool_result(
        agent="arena_scout",
        round_num=1,
        tool_name="search_web",
        result={"status": "ok", "results": [{"url": "https://example.com"}]},
        status="ok",
    )
    writer.llm_response(
        agent="arena_scout",
        model="minimax-m2.5",
        round_num=1,
        content='{"sources_searched":["serper"],"search_summary":"Done"}',
    )
    writer.outcome(status="passed_gate_b", total_cost_eur=1.25)

    content = writer.path.read_text(encoding="utf-8")
    assert "# Run Trace: cand_demo" in content
    assert "System Prompt" in content
    assert "Tool Call" in content
    assert "Run Outcome" in content


def test_run_trace_writer_handles_embedded_backticks_and_truncation(tmp_path: Path) -> None:
    writer = RunTraceWriter.create(
        output_dir=tmp_path,
        candidate_id="cand_ticks",
        mode="live",
        prompt_version="v-test",
    )

    writer.llm_round(
        agent="arena_scout",
        model="minimax-m2.5",
        round_num=1,
        prompt=PromptBundle(
            system_prompt='Prompt with ```json\n{"ok":true}\n``` inside',
            user_prompt="User text",
            prompt_version="v-test",
            prompt_hash="hash123",
        ),
        tool_choice="none",
        tool_names=[],
    )
    writer.llm_response(
        agent="arena_scout",
        model="minimax-m2.5",
        round_num=1,
        content="Response with ```code``` fence",
    )
    truncated_writer = RunTraceWriter(
        tmp_path / "cand_trunc.trace.md",
        candidate_id="cand_trunc",
        mode="live",
        prompt_version="v-test",
        char_limit=5,
    )
    truncated_writer.llm_response(
        agent="arena_scout",
        model="minimax-m2.5",
        round_num=1,
        content="123456789",
    )

    content = writer.path.read_text(encoding="utf-8")
    truncated_content = truncated_writer.path.read_text(encoding="utf-8")

    assert "````text" in content
    assert "````" in content
    assert "... [truncated]" in truncated_content
    assert "\\n... [truncated]" not in truncated_content
