from __future__ import annotations

import copy
import logging
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from truth_engine.adapters.db.migrate import upgrade_database
from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.adapters.llm.litellm_runner import LiteLLMAgentRunner
from truth_engine.config.settings import Settings
from truth_engine.contracts.stages import ArenaSearchResult
from truth_engine.domain.enums import AgentName, Stage
from truth_engine.prompts.builder import PromptBundle
from truth_engine.services.logging import configure_logging
from truth_engine.tools.schemas import tool_schemas_for_agent


class _FakeCompletionSequence:
    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(copy.deepcopy(kwargs))
        if not self._responses:
            raise AssertionError("No remaining fake responses.")
        return self._responses.pop(0)


class _FakeLiteLLMModule:
    def __init__(
        self,
        *,
        supports_response_schema: bool = False,
        response_cost: float = 0.0,
        completion_cost: float = 0.0,
    ) -> None:
        self.suppress_debug_info = False
        self.turn_off_message_logging = False
        self._supports_response_schema = supports_response_schema
        self._response_cost = response_cost
        self._completion_cost = completion_cost

    def supports_response_schema(
        self,
        model: str,
        custom_llm_provider: str | None = None,
    ) -> bool:
        del model, custom_llm_provider
        return self._supports_response_schema

    def get_llm_provider(
        self,
        model: str,
        custom_llm_provider: str | None = None,
        api_base: str | None = None,
        api_key: str | None = None,
        litellm_params: Any | None = None,
    ) -> tuple[str, str, None, None]:
        del api_base, api_key, litellm_params
        return model, custom_llm_provider or "openai", None, None

    def response_cost_calculator(self, **_kwargs: Any) -> float:
        return self._response_cost

    def completion_cost(self, **_kwargs: Any) -> float:
        return self._completion_cost


class _ResponseFormatRejectingCompletion:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(copy.deepcopy(kwargs))
        if len(self.calls) == 1 and "response_format" in kwargs:
            raise ValueError("response_format is not supported for this model")
        return self.response


def _reset_truth_engine_logger() -> None:
    names = [
        name
        for name in logging.Logger.manager.loggerDict
        if name == "truth_engine" or name.startswith("truth_engine.")
    ]
    for name in ["truth_engine", *sorted(names)]:
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(logging.NOTSET)
        logger.propagate = True


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


def test_litellm_runner_uses_proxy_mode_for_alias_models() -> None:
    proxy_completion = _FakeCompletionSequence(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"sources_searched":["serper"],'
                                '"search_summary":"Proxy alias worked."}'
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3},
            }
        ]
    )
    runner = LiteLLMAgentRunner(
        settings=Settings(
            litellm_api_base="http://localhost:4000",
            litellm_api_key=SecretStr("proxy-key"),
            tier1_model="minimax-m2.5",
        ),
        proxy_completion_fn=proxy_completion,
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

    assert execution.result.search_summary == "Proxy alias worked."
    assert len(proxy_completion.calls) == 1


def test_litellm_runner_uses_json_schema_response_format_for_no_tool_agents() -> None:
    completion = _FakeCompletionSequence(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"sources_searched":["serper"],'
                                '"search_summary":"Structured output worked."}'
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3},
            }
        ]
    )
    fake_module = _FakeLiteLLMModule(supports_response_schema=True)
    with patch.dict("sys.modules", {"litellm": fake_module}):
        runner = LiteLLMAgentRunner(
            settings=Settings(tier1_model="openai/gpt-4.1-mini"),
            completion_fn=completion,
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

    assert execution.result.search_summary == "Structured output worked."
    assert completion.calls[0]["response_format"]["type"] == "json_schema"
    assert completion.calls[0]["response_format"]["json_schema"]["name"] == "ArenaSearchResult"


def test_litellm_runner_falls_back_when_response_format_is_rejected() -> None:
    completion = _ResponseFormatRejectingCompletion(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"sources_searched":["serper"],'
                            '"search_summary":"Fallback path worked."}'
                        ),
                    }
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 3},
        }
    )
    fake_module = _FakeLiteLLMModule(supports_response_schema=True)
    with patch.dict("sys.modules", {"litellm": fake_module}):
        runner = LiteLLMAgentRunner(
            settings=Settings(tier1_model="openai/gpt-4.1-mini"),
            completion_fn=completion,
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

    assert execution.result.search_summary == "Fallback path worked."
    assert "response_format" in completion.calls[0]
    assert "response_format" not in completion.calls[1]


def test_litellm_runner_prefers_response_cost_before_completion_cost() -> None:
    fake_module = _FakeLiteLLMModule(
        supports_response_schema=False,
        response_cost=0.12,
        completion_cost=0.34,
    )
    with patch.dict("sys.modules", {"litellm": fake_module}):
        runner = LiteLLMAgentRunner(
            settings=Settings(),
            completion_fn=lambda **_kwargs: {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"sources_searched":["serper"],'
                                '"search_summary":"Cost path worked."}'
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
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

    assert execution.metrics.cost_eur == 0.12


def test_litellm_runner_resumes_interrupted_tool_session_without_replaying_tools() -> None:
    with TemporaryDirectory() as temp_dir:
        database_path = Path(temp_dir) / "truth_engine.db"
        database_url = f"sqlite:///{database_path}"
        upgrade_database(database_url)
        repository = TruthEngineRepository.from_database_url(database_url)
        repository.create_schema()
        repository.create_candidate("cand_resume_agent", status="running")

        first_completion = _FakeCompletionSequence(
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
                }
            ]
        )
        tool_invocations: list[tuple[str, dict[str, Any]]] = []

        def interrupted_completion(**kwargs: Any) -> dict[str, Any]:
            if first_completion._responses:
                return first_completion(**kwargs)
            raise RuntimeError("synthetic interruption")

        def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, object]:
            tool_invocations.append((name, arguments))
            return {
                "status": "ok",
                "results": [{"title": "Ops pain", "url": "https://example.com"}],
            }

        prompt = PromptBundle(
            system_prompt="system",
            user_prompt="user",
            prompt_version="v-test",
            prompt_hash="resume123",
        )

        interrupted_runner = LiteLLMAgentRunner(
            settings=Settings(database_url=database_url),
            completion_fn=interrupted_completion,
            cost_calculator=lambda _response, _model: 0.05,
            repository=repository,
        )

        with pytest.raises(RuntimeError, match="synthetic interruption"):
            interrupted_runner.run(
                agent=AgentName.ARENA_SCOUT,
                prompt=prompt,
                response_model=ArenaSearchResult,
                tools=tool_schemas_for_agent(AgentName.ARENA_SCOUT),
                tool_executor=execute_tool,
                checkpoint_candidate_id="cand_resume_agent",
                checkpoint_stage=Stage.ARENA_DISCOVERY,
                checkpoint_attempt_index=0,
            )

        resumed_completion = _FakeCompletionSequence(
            [
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": (
                                    '{"sources_searched":["serper"],'
                                    '"search_summary":"Resumed without replaying the tool."}'
                                ),
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 13, "completion_tokens": 9},
                }
            ]
        )
        resumed_runner = LiteLLMAgentRunner(
            settings=Settings(database_url=database_url),
            completion_fn=resumed_completion,
            cost_calculator=lambda _response, _model: 0.05,
            repository=repository,
        )

        execution = resumed_runner.run(
            agent=AgentName.ARENA_SCOUT,
            prompt=prompt,
            response_model=ArenaSearchResult,
            tools=tool_schemas_for_agent(AgentName.ARENA_SCOUT),
            tool_executor=execute_tool,
            checkpoint_candidate_id="cand_resume_agent",
            checkpoint_stage=Stage.ARENA_DISCOVERY,
            checkpoint_attempt_index=0,
        )

    assert execution.result.search_summary == "Resumed without replaying the tool."
    assert tool_invocations == [("search_web", {"query": "warehouse ops pain", "limit": 1})]
    assert execution.metrics.input_tokens == 24
    assert execution.metrics.output_tokens == 16
    assert execution.metrics.cost_eur == 0.1
    assert resumed_completion.calls[0]["messages"][-1]["role"] == "tool"
    assert "https://example.com" in resumed_completion.calls[0]["messages"][-1]["content"]


def test_litellm_runner_forces_finalization_after_tool_budget() -> None:
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
                                        "arguments": '{"query":"ops pain","limit":1}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"sources_searched":["serper"],'
                                '"search_summary":"Stopped after the tool budget."}'
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4},
            },
        ]
    )
    runner = LiteLLMAgentRunner(
        settings=Settings(agent_max_tool_rounds=1),
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
        tools=tool_schemas_for_agent(AgentName.ARENA_SCOUT),
        tool_executor=lambda _name, _arguments: {"status": "ok"},
    )

    assert execution.result.search_summary == "Stopped after the tool budget."
    assert completion.calls[0]["tool_choice"] == "auto"
    assert completion.calls[1]["tool_choice"] == "none"


def test_litellm_runner_requires_persistence_tool_before_finalizing() -> None:
    completion = _FakeCompletionSequence(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"sources_searched":["serper"],"search_summary":"Found a wedge."}'
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4},
            },
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
                                        "name": "create_arena_proposal",
                                        "arguments": (
                                            '{"candidate_id":"cand_123",'
                                            '"arena":{"domain":"Returns Ops",'
                                            '"icp_user_role":"Ops Lead",'
                                            '"icp_buyer_role":"Head of Ops",'
                                            '"geo":"EU/US",'
                                            '"channel_surface":["linkedin"],'
                                            '"solution_modality":"software",'
                                            '"market_signals":["complaints"],'
                                            '"signal_sources":["reddit"],'
                                            '"market_size_signal":"large",'
                                            '"expected_sales_cycle":"30-60 days",'
                                            '"rationale":"Good fit"}}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 5},
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"sources_searched":["serper","reddit"],'
                                '"search_summary":"Persisted the arena."}'
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 6},
            },
        ]
    )
    observed_tools: list[str] = []

    def execute_tool(name: str, _arguments: dict[str, Any]) -> dict[str, str]:
        observed_tools.append(name)
        return {"status": "ok"}

    runner = LiteLLMAgentRunner(
        settings=Settings(agent_max_tool_rounds=3),
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
        tools=tool_schemas_for_agent(AgentName.ARENA_SCOUT),
        tool_executor=execute_tool,
        required_tool_names={"create_arena_proposal"},
    )

    assert execution.result.search_summary == "Persisted the arena."
    assert observed_tools == ["create_arena_proposal"]
    assert "must call these required tool(s)" in completion.calls[1]["messages"][-1]["content"]


def test_litellm_runner_reminds_when_required_tool_is_missing_mid_run() -> None:
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
                                        "arguments": '{"query":"ops pain","limit":1}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {
                                        "name": "search_web",
                                        "arguments": '{"query":"switching pain","limit":1}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4},
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_3",
                                    "type": "function",
                                    "function": {
                                        "name": "create_arena_proposal",
                                        "arguments": (
                                            '{"candidate_id":"cand_123",'
                                            '"arena":{"domain":"Returns Ops",'
                                            '"icp_user_role":"Ops Lead",'
                                            '"icp_buyer_role":"Head of Ops",'
                                            '"geo":"EU/US",'
                                            '"channel_surface":["linkedin"],'
                                            '"solution_modality":"software",'
                                            '"market_signals":["complaints"],'
                                            '"signal_sources":["reddit"],'
                                            '"market_size_signal":"large",'
                                            '"expected_sales_cycle":"30-60 days",'
                                            '"rationale":"Good fit"}}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5},
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"sources_searched":["serper"],'
                                '"search_summary":"Persisted after reminder."}'
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 6},
            },
        ]
    )
    runner = LiteLLMAgentRunner(
        settings=Settings(
            agent_max_tool_rounds=4,
            required_tool_reminder_interval=2,
        ),
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
        tools=tool_schemas_for_agent(AgentName.ARENA_SCOUT),
        tool_executor=lambda _name, _arguments: {"status": "ok"},
        required_tool_names={"create_arena_proposal"},
    )

    assert execution.result.search_summary == "Persisted after reminder."
    assert (
        "without calling the required persistence tool"
        in completion.calls[2]["messages"][-1]["content"]
    )


def test_litellm_runner_suppresses_litellm_debug_info() -> None:
    class _FakeLiteLLMModule:
        def __init__(self) -> None:
            self.suppress_debug_info = False
            self.turn_off_message_logging = False

    fake_module = _FakeLiteLLMModule()
    with patch.dict("sys.modules", {"litellm": fake_module}):
        runner = LiteLLMAgentRunner(
            settings=Settings(),
            completion_fn=lambda **_kwargs: {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": ('{"sources_searched":["serper"],"search_summary":"Done."}'),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            cost_calculator=lambda _response, _model: 0.0,
        )
        runner.run(
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

    assert fake_module.suppress_debug_info is True
    assert fake_module.turn_off_message_logging is True


def test_litellm_runner_logs_write_tool_calls_in_terminal_output() -> None:
    _reset_truth_engine_logger()
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
                                        "name": "create_arena_proposal",
                                        "arguments": (
                                            '{"candidate_id":"cand_123",'
                                            '"arena":{"domain":"Returns Ops",'
                                            '"icp_user_role":"Ops Lead",'
                                            '"icp_buyer_role":"Head of Ops",'
                                            '"geo":"EU/US",'
                                            '"channel_surface":["linkedin"],'
                                            '"solution_modality":"software",'
                                            '"market_signals":["complaints"],'
                                            '"signal_sources":["reddit"],'
                                            '"market_size_signal":"large",'
                                            '"expected_sales_cycle":"30-60 days",'
                                            '"rationale":"Good fit"}}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 5},
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"sources_searched":["serper"],'
                                '"search_summary":"Persisted the arena."}'
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 6},
            },
        ]
    )
    runner = LiteLLMAgentRunner(
        settings=Settings(agent_max_tool_rounds=2),
        completion_fn=completion,
        cost_calculator=lambda _response, _model: 0.0,
    )

    with patch("truth_engine.adapters.llm.litellm_runner.log_tool_exec") as log_tool_exec_mock:
        runner.run(
            agent=AgentName.ARENA_SCOUT,
            prompt=PromptBundle(
                system_prompt="system",
                user_prompt="user",
                prompt_version="v-test",
                prompt_hash="abc123",
            ),
            response_model=ArenaSearchResult,
            tools=tool_schemas_for_agent(AgentName.ARENA_SCOUT),
            tool_executor=lambda _name, _arguments: {
                "status": "saved",
                "arena_id": "arena_123",
            },
        )

    assert log_tool_exec_mock.call_count >= 1
    assert (
        "arena_scout",
        "create_arena_proposal",
        "saved",
    ) == log_tool_exec_mock.call_args_list[0].args[:3]
    assert log_tool_exec_mock.call_args_list[0].kwargs["arguments"]["candidate_id"] == "cand_123"
    _reset_truth_engine_logger()


def test_litellm_runner_keeps_network_tool_logs_out_of_info_terminal_output() -> None:
    _reset_truth_engine_logger()
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
    runner = LiteLLMAgentRunner(
        settings=Settings(),
        completion_fn=completion,
        cost_calculator=lambda _response, _model: 0.0,
    )

    stderr = StringIO()
    with patch("truth_engine.services.logging.sys.stderr", stderr):
        configure_logging("INFO")
        runner.run(
            agent=AgentName.ARENA_SCOUT,
            prompt=PromptBundle(
                system_prompt="system",
                user_prompt="user",
                prompt_version="v-test",
                prompt_hash="abc123",
            ),
            response_model=ArenaSearchResult,
            tools=tool_schemas_for_agent(AgentName.ARENA_SCOUT),
            tool_executor=lambda _name, _arguments: {"status": "ok"},
        )

    assert "search_web" not in stderr.getvalue()
    _reset_truth_engine_logger()
