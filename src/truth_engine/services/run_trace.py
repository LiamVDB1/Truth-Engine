from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from truth_engine.prompts.builder import PromptBundle


class RunTraceWriter:
    def __init__(
        self,
        path: Path,
        *,
        candidate_id: str,
        mode: str,
        prompt_version: str,
        char_limit: int = 6000,
    ):
        self.path = path
        self.candidate_id = candidate_id
        self.mode = mode
        self.prompt_version = prompt_version
        self.char_limit = char_limit
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self._header(), encoding="utf-8")

    @classmethod
    def create(
        cls,
        *,
        output_dir: Path,
        candidate_id: str,
        mode: str,
        prompt_version: str,
    ) -> RunTraceWriter:
        return cls(
            output_dir / f"{candidate_id}.trace.md",
            candidate_id=candidate_id,
            mode=mode,
            prompt_version=prompt_version,
        )

    def stage_start(
        self,
        *,
        stage: str,
        agent: str,
        attempt: int = 0,
        extra: str = "",
    ) -> None:
        lines = [
            self._event_heading("Stage Start"),
            f"- stage: `{stage}`",
            f"- agent: `{agent}`",
            f"- attempt: `{attempt + 1}`",
        ]
        if extra:
            lines.append(f"- extra: {extra}")
        self._append_lines(lines)

    def stage_done(
        self,
        *,
        stage: str,
        agent: str,
        cost_eur: float = 0.0,
        summary: str = "",
    ) -> None:
        lines = [
            self._event_heading("Stage Done"),
            f"- stage: `{stage}`",
            f"- agent: `{agent}`",
            f"- cost_eur: `{cost_eur:.6f}`",
        ]
        if summary:
            lines.append(f"- summary: {summary}")
        self._append_lines(lines)

    def gate_decision(
        self,
        *,
        gate: str,
        action: str,
        reason: str,
        score: int | None = None,
        budget_mode: str = "normal",
    ) -> None:
        lines = [
            self._event_heading("Gate Decision"),
            f"- gate: `{gate}`",
            f"- action: `{action}`",
            f"- budget_mode: `{budget_mode}`",
            f"- reason: {reason}",
        ]
        if score is not None:
            lines.insert(4, f"- score: `{score}`")
        self._append_lines(lines)

    def budget_warning(self, *, budget_mode: str, total_cost_eur: float) -> None:
        self._append_lines(
            [
                self._event_heading("Budget Warning"),
                f"- budget_mode: `{budget_mode}`",
                f"- total_cost_eur: `{total_cost_eur:.6f}`",
            ]
        )

    def llm_round(
        self,
        *,
        agent: str,
        model: str,
        round_num: int,
        prompt: PromptBundle | None,
        tool_choice: str | None,
        tool_names: list[str],
    ) -> None:
        lines = [
            self._event_heading("LLM Round"),
            f"- agent: `{agent}`",
            f"- model: `{model}`",
            f"- round: `{round_num}`",
            f"- tool_choice: `{tool_choice or 'n/a'}`",
        ]
        if tool_names:
            lines.append(f"- tools: `{', '.join(tool_names)}`")
        if prompt is not None:
            lines.extend(
                [
                    f"- prompt_version: `{prompt.prompt_version}`",
                    f"- prompt_hash: `{prompt.prompt_hash}`",
                    "<details><summary>System Prompt</summary>",
                    "",
                    self._code_block(self._truncate(prompt.system_prompt), "text"),
                    "",
                    "</details>",
                    "",
                    "<details><summary>User Prompt</summary>",
                    "",
                    self._code_block(self._truncate(prompt.user_prompt), "text"),
                    "",
                    "</details>",
                ]
            )
        self._append_lines(lines)

    def llm_response(
        self,
        *,
        agent: str,
        model: str,
        round_num: int,
        content: str,
    ) -> None:
        self._append_lines(
            [
                self._event_heading("LLM Response"),
                f"- agent: `{agent}`",
                f"- model: `{model}`",
                f"- round: `{round_num}`",
                self._code_block(self._truncate(content or "[empty response]"), "text"),
            ]
        )

    def tool_call(
        self,
        *,
        agent: str,
        round_num: int,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        self._append_lines(
            [
                self._event_heading("Tool Call"),
                f"- agent: `{agent}`",
                f"- round: `{round_num}`",
                f"- tool: `{tool_name}`",
                self._code_block(self._truncate_json(arguments), "json"),
            ]
        )

    def tool_result(
        self,
        *,
        agent: str,
        round_num: int,
        tool_name: str,
        result: Any,
        status: str,
    ) -> None:
        self._append_lines(
            [
                self._event_heading("Tool Result"),
                f"- agent: `{agent}`",
                f"- round: `{round_num}`",
                f"- tool: `{tool_name}`",
                f"- status: `{status}`",
                self._code_block(self._truncate_json(result), "json"),
            ]
        )

    def json_repair(self, *, agent: str, attempt: int, error: str) -> None:
        self._append_lines(
            [
                self._event_heading("JSON Repair"),
                f"- agent: `{agent}`",
                f"- attempt: `{attempt}`",
                f"- error: {self._truncate(error)}",
            ]
        )

    def required_tools_missing(
        self,
        *,
        agent: str,
        missing_tools: list[str],
    ) -> None:
        self._append_lines(
            [
                self._event_heading("Required Tool Retry"),
                f"- agent: `{agent}`",
                f"- missing_tools: `{', '.join(missing_tools)}`",
                "- reason: Final JSON arrived before the required persistence tool calls.",
            ]
        )

    def error(self, *, stage: str, error: BaseException) -> None:
        self._append_lines(
            [
                self._event_heading("Run Error"),
                f"- stage: `{stage}`",
                f"- type: `{type(error).__name__}`",
                f"- message: {self._truncate(str(error))}",
            ]
        )

    def outcome(self, *, status: str, total_cost_eur: float) -> None:
        self._append_lines(
            [
                self._event_heading("Run Outcome"),
                f"- status: `{status}`",
                f"- total_cost_eur: `{total_cost_eur:.6f}`",
            ]
        )

    def artifact(self, *, label: str, path: Path) -> None:
        self._append_lines(
            [
                self._event_heading("Artifact"),
                f"- {label}: `{path}`",
            ]
        )

    def _header(self) -> str:
        started_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        return "\n".join(
            [
                f"# Run Trace: {self.candidate_id}",
                f"- mode: `{self.mode}`",
                f"- prompt_version: `{self.prompt_version}`",
                f"- started_at: `{started_at}`",
                "",
                "This file is appended while the workflow runs.",
                "",
            ]
        )

    def _event_heading(self, title: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        return f"## {timestamp} · {title}"

    def _truncate_json(self, value: Any) -> str:
        try:
            text = json.dumps(value, indent=2, ensure_ascii=True, default=str)
        except TypeError:
            text = repr(value)
        return self._truncate(text)

    def _truncate(self, value: str) -> str:
        if len(value) <= self.char_limit:
            return value
        return f"{value[: self.char_limit]}\n... [truncated]"

    def _code_block(self, content: str, language: str) -> str:
        fence = _markdown_fence(content)
        return f"{fence}{language}\n{content}\n{fence}"

    def _append_lines(self, lines: list[str]) -> None:
        payload = "\n".join(lines) + "\n\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()


def _markdown_fence(content: str) -> str:
    longest_run = 0
    current_run = 0
    for char in content:
        if char == "`":
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0
    return "`" * max(3, longest_run + 1)
