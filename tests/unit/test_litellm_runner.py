from __future__ import annotations

from typing import Any

from truth_engine.adapters.llm.litellm_runner import LiteLLMAgentRunner
from truth_engine.config.settings import Settings
from truth_engine.contracts.stages import ArenaSearchResult
from truth_engine.domain.enums import AgentName
from truth_engine.prompts.builder import PromptBundle
from truth_engine.tools.schemas import tool_schemas_for_agent


class _FakeCompletionSequence:
    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("No remaining fake responses.")
        return self._responses.pop(0)


def test_litellm_runner_executes_tool_calls_and_parses_json() -> None:
    completion = _FakeCompletionSequence(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_web",
                                        "arguments": '{"query":"warehouse ops pain","limit":1}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"sources_searched":["serper"],'
                                '"search_summary":"Found one promising arena."}'
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 13, "completion_tokens": 9},
            },
        ]
    )
    observed_tools: list[tuple[str, dict[str, Any]]] = []

    def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, object]:
        observed_tools.append((name, arguments))
        return {
            "status": "ok",
            "results": [{"title": "Ops pain", "url": "https://example.com"}],
        }

    runner = LiteLLMAgentRunner(
        settings=Settings(),
        completion_fn=completion,
        cost_calculator=lambda _response, _model: 0.05,
    )
    prompt = PromptBundle(
        system_prompt="system",
        user_prompt="user",
        prompt_version="v-test",
        prompt_hash="abc123",
    )

    execution = runner.run(
        agent=AgentName.ARENA_SCOUT,
        prompt=prompt,
        response_model=ArenaSearchResult,
        tools=tool_schemas_for_agent(AgentName.ARENA_SCOUT),
        tool_executor=execute_tool,
    )

    assert execution.result.search_summary == "Found one promising arena."
    assert execution.metrics.tool_calls == 1
    assert execution.metrics.input_tokens == 24
    assert execution.metrics.output_tokens == 16
    assert execution.metrics.cost_eur == 0.1
    assert observed_tools == [("search_web", {"query": "warehouse ops pain", "limit": 1})]


def test_litellm_runner_repairs_invalid_json_once() -> None:
    completion = _FakeCompletionSequence(
        [
            {
                "choices": [{"message": {"role": "assistant", "content": "not-json"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"sources_searched":["serper"],'
                                '"search_summary":"Repaired output."}'
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
            },
        ]
    )
    runner = LiteLLMAgentRunner(
        settings=Settings(),
        completion_fn=completion,
        cost_calculator=lambda _response, _model: 0.0,
    )

    execution = runner.run(
        agent=AgentName.ARENA_SCOUT,
        prompt=PromptBundle(
            system_prompt="system",
            user_prompt="user",
            prompt_version="v-test",
            prompt_hash="abc123",
        ),
        response_model=ArenaSearchResult,
        tools=None,
        tool_executor=None,
    )

    assert execution.result.search_summary == "Repaired output."
    assert len(completion.calls) == 2
    assert "Return valid JSON" in completion.calls[1]["messages"][-1]["content"]
