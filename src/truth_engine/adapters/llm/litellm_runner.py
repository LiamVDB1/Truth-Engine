from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from truth_engine.adapters.db.repositories import TruthEngineRepository
from truth_engine.config.model_routing import resolve_agent_model
from truth_engine.config.settings import Settings
from truth_engine.contracts.checkpoints import AgentCheckpointRecord, AgentCheckpointState
from truth_engine.contracts.stages import ActivityMetrics
from truth_engine.domain.enums import AgentCheckpointStatus, AgentName, Stage
from truth_engine.prompts.builder import PromptBundle
from truth_engine.services.logging import debug_json_repair, debug_llm_call, log_tool_exec
from truth_engine.services.run_trace import RunTraceWriter

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class AgentExecution[T: BaseModel]:
    result: T
    metrics: ActivityMetrics


class LiteLLMAgentRunner:
    def __init__(
        self,
        settings: Settings,
        *,
        repository: TruthEngineRepository | None = None,
        completion_fn: Callable[..., Any] | None = None,
        proxy_completion_fn: Callable[..., Any] | None = None,
        cost_calculator: Callable[[Any, str], float] | None = None,
        trace_writer: RunTraceWriter | None = None,
    ):
        self.settings = settings
        self.repository = repository
        self._completion_fn = completion_fn
        self._proxy_completion_fn = proxy_completion_fn
        self._cost_calculator = cost_calculator
        self.trace_writer = trace_writer
        self._response_schema_support_cache: dict[str, bool] = {}

    def run(
        self,
        *,
        agent: AgentName,
        prompt: PromptBundle,
        response_model: type[T],
        tools: list[dict[str, Any]] | None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None,
        required_tool_names: set[str] | None = None,
        checkpoint_candidate_id: str | None = None,
        checkpoint_stage: Stage | None = None,
        checkpoint_attempt_index: int = 0,
    ) -> AgentExecution[T]:
        _configure_litellm_runtime()
        model = resolve_agent_model(agent, self.settings)
        required_tools = required_tool_names or set()
        checkpoint = self._load_checkpoint(
            candidate_id=checkpoint_candidate_id,
            stage=checkpoint_stage,
            agent=agent,
            attempt_index=checkpoint_attempt_index,
            prompt_hash=prompt.prompt_hash,
        )
        if checkpoint is not None and checkpoint.status is AgentCheckpointStatus.COMPLETED:
            result_payload = checkpoint.state.result_payload
            if result_payload is None:
                raise ValueError("Completed agent checkpoint is missing a result payload.")
            return AgentExecution(
                result=response_model.model_validate(result_payload),
                metrics=checkpoint.state.metrics(),
            )

        if checkpoint is None:
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": prompt.system_prompt},
                {"role": "user", "content": prompt.user_prompt},
            ]
            input_tokens = 0
            output_tokens = 0
            cost_eur = 0.0
            tool_calls = 0
            tool_rounds_used = 0
            repair_attempts = 0
            finalization_prompt_sent = False
            seen_tool_signatures: dict[str, int] = {}
            executed_tool_names: set[str] = set()
            pending_tool_calls: list[dict[str, Any]] = []
            pending_tool_index = 0
        else:
            state = checkpoint.state
            messages = list(state.messages)
            input_tokens = state.input_tokens
            output_tokens = state.output_tokens
            cost_eur = state.cost_eur
            tool_calls = state.tool_calls
            tool_rounds_used = state.tool_rounds_used
            repair_attempts = state.repair_attempts
            finalization_prompt_sent = state.finalization_prompt_sent
            seen_tool_signatures = dict(state.seen_tool_signatures)
            executed_tool_names = set(state.executed_tool_names)
            pending_tool_calls = list(state.pending_tool_calls)
            pending_tool_index = state.pending_tool_index

        max_rounds = self.settings.agent_max_tool_rounds + self.settings.llm_max_retries + 1
        completion_rounds_used = 0
        while completion_rounds_used < max_rounds:
            if pending_tool_calls:
                if tool_executor is None:
                    raise ValueError("Tool calls were returned without a tool executor.")
                (
                    messages,
                    tool_calls,
                    pending_tool_calls,
                    pending_tool_index,
                ) = self._process_pending_tool_calls(
                    agent=agent,
                    round_num=max(1, completion_rounds_used),
                    messages=messages,
                    tool_executor=tool_executor,
                    pending_tool_calls=pending_tool_calls,
                    pending_tool_index=pending_tool_index,
                    seen_tool_signatures=seen_tool_signatures,
                    executed_tool_names=executed_tool_names,
                    tool_calls=tool_calls,
                )
                missing_required_tools = sorted(required_tools - executed_tool_names)
                if (
                    missing_required_tools
                    and tool_rounds_used < self.settings.agent_max_tool_rounds
                    and tool_rounds_used % self.settings.required_tool_reminder_interval == 0
                ):
                    if self.trace_writer is not None:
                        self.trace_writer.required_tool_reminder(
                            agent=agent.value,
                            missing_tools=missing_required_tools,
                            tool_rounds_used=tool_rounds_used,
                        )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"You have used {tool_rounds_used} tool rounds without calling "
                                "the required persistence tool(s): "
                                f"{', '.join(missing_required_tools)}. "
                                "Persist the strongest qualifying finding now. "
                                "Keep exploring only when it directly improves coverage or "
                                "fills a known evidence gap."
                            ),
                        }
                    )
                self._store_checkpoint(
                    candidate_id=checkpoint_candidate_id,
                    stage=checkpoint_stage,
                    agent=agent,
                    attempt_index=checkpoint_attempt_index,
                    prompt=prompt,
                    model_alias=model,
                    response_model=response_model,
                    status=AgentCheckpointStatus.IN_PROGRESS,
                    messages=messages,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_eur=cost_eur,
                    tool_calls=tool_calls,
                    tool_rounds_used=tool_rounds_used,
                    repair_attempts=repair_attempts,
                    finalization_prompt_sent=finalization_prompt_sent,
                    seen_tool_signatures=seen_tool_signatures,
                    executed_tool_names=executed_tool_names,
                    pending_tool_calls=pending_tool_calls,
                    pending_tool_index=pending_tool_index,
                )
                continue

            tool_choice: str | None = None
            if tools is not None:
                if tool_rounds_used < self.settings.agent_max_tool_rounds:
                    tool_choice = "auto"
                else:
                    tool_choice = "none"
                    if not finalization_prompt_sent:
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Tool budget is exhausted. Return the final JSON output now. "
                                    "Do not call any more tools."
                                ),
                            }
                        )
                        finalization_prompt_sent = True
                        self._store_checkpoint(
                            candidate_id=checkpoint_candidate_id,
                            stage=checkpoint_stage,
                            agent=agent,
                            attempt_index=checkpoint_attempt_index,
                            prompt=prompt,
                            model_alias=model,
                            response_model=response_model,
                            status=AgentCheckpointStatus.IN_PROGRESS,
                            messages=messages,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cost_eur=cost_eur,
                            tool_calls=tool_calls,
                            tool_rounds_used=tool_rounds_used,
                            repair_attempts=repair_attempts,
                            finalization_prompt_sent=finalization_prompt_sent,
                            seen_tool_signatures=seen_tool_signatures,
                            executed_tool_names=executed_tool_names,
                            pending_tool_calls=pending_tool_calls,
                            pending_tool_index=pending_tool_index,
                        )
            completion_rounds_used += 1
            if self.trace_writer is not None:
                self.trace_writer.llm_round(
                    agent=agent.value,
                    model=model,
                    round_num=completion_rounds_used,
                    prompt=prompt if completion_rounds_used == 1 and checkpoint is None else None,
                    tool_choice=tool_choice,
                    tool_names=_tool_names(tools),
                )
            request_kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "max_retries": self.settings.llm_max_retries,
            }
            reasoning_effort = _reasoning_effort_for_model(
                model=model,
                configured_effort=self.settings.llm_reasoning_effort,
            )
            if reasoning_effort is not None:
                request_kwargs["reasoning_effort"] = reasoning_effort
            if not _should_omit_temperature(model=model, reasoning_effort=reasoning_effort):
                request_kwargs["temperature"] = self.settings.llm_temperature
            response = self._request_completion(
                model=model,
                request_kwargs=request_kwargs,
                response_model=response_model,
            )
            input_tokens += int(_usage_value(response, "prompt_tokens"))
            output_tokens += int(_usage_value(response, "completion_tokens"))
            round_cost = self._completion_cost(response, model, request_kwargs)
            cost_eur += round_cost

            message = _choice_message(response)
            parsed_tool_calls = _message_tool_calls(message)
            if parsed_tool_calls:
                tool_rounds_used += 1
                messages.append(_assistant_message_payload(message))
                pending_tool_calls = parsed_tool_calls
                pending_tool_index = 0
                self._store_checkpoint(
                    candidate_id=checkpoint_candidate_id,
                    stage=checkpoint_stage,
                    agent=agent,
                    attempt_index=checkpoint_attempt_index,
                    prompt=prompt,
                    model_alias=model,
                    response_model=response_model,
                    status=AgentCheckpointStatus.IN_PROGRESS,
                    messages=messages,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_eur=cost_eur,
                    tool_calls=tool_calls,
                    tool_rounds_used=tool_rounds_used,
                    repair_attempts=repair_attempts,
                    finalization_prompt_sent=finalization_prompt_sent,
                    seen_tool_signatures=seen_tool_signatures,
                    executed_tool_names=executed_tool_names,
                    pending_tool_calls=pending_tool_calls,
                    pending_tool_index=pending_tool_index,
                )
                debug_llm_call(
                    agent.value,
                    model,
                    round_num=completion_rounds_used,
                    input_tokens=int(_usage_value(response, "prompt_tokens")),
                    output_tokens=int(_usage_value(response, "completion_tokens")),
                    cost_eur=round_cost,
                    tool_calls=len(parsed_tool_calls),
                )
                continue

            content = _message_content(message)
            if self.trace_writer is not None:
                self.trace_writer.llm_response(
                    agent=agent.value,
                    model=model,
                    round_num=completion_rounds_used,
                    content=content,
                )
            try:
                parsed = _parse_response_model(content, response_model)
                missing_required_tools = sorted(required_tools - executed_tool_names)
                if missing_required_tools:
                    if tool_rounds_used >= self.settings.agent_max_tool_rounds:
                        raise RuntimeError(
                            f"{agent.value} exhausted its tool budget before calling the "
                            f"required tool(s): {', '.join(missing_required_tools)}."
                        )
                    if self.trace_writer is not None:
                        self.trace_writer.required_tools_missing(
                            agent=agent.value,
                            missing_tools=missing_required_tools,
                        )
                    messages.append(_assistant_message_payload(message))
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Do not finalize yet. Before returning the final JSON, "
                                "you must call these required tool(s): "
                                f"{', '.join(missing_required_tools)}. "
                                "Persist the required records first, then return the final JSON."
                            ),
                        }
                    )
                    self._store_checkpoint(
                        candidate_id=checkpoint_candidate_id,
                        stage=checkpoint_stage,
                        agent=agent,
                        attempt_index=checkpoint_attempt_index,
                        prompt=prompt,
                        model_alias=model,
                        response_model=response_model,
                        status=AgentCheckpointStatus.IN_PROGRESS,
                        messages=messages,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_eur=cost_eur,
                        tool_calls=tool_calls,
                        tool_rounds_used=tool_rounds_used,
                        repair_attempts=repair_attempts,
                        finalization_prompt_sent=finalization_prompt_sent,
                        seen_tool_signatures=seen_tool_signatures,
                        executed_tool_names=executed_tool_names,
                        pending_tool_calls=pending_tool_calls,
                        pending_tool_index=pending_tool_index,
                    )
                    continue
                metrics = ActivityMetrics(
                    cost_eur=round(cost_eur, 6),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    tool_calls=tool_calls,
                )
                debug_llm_call(
                    agent.value,
                    model,
                    round_num=completion_rounds_used,
                    input_tokens=int(_usage_value(response, "prompt_tokens")),
                    output_tokens=int(_usage_value(response, "completion_tokens")),
                    cost_eur=round_cost,
                )
                self._store_checkpoint(
                    candidate_id=checkpoint_candidate_id,
                    stage=checkpoint_stage,
                    agent=agent,
                    attempt_index=checkpoint_attempt_index,
                    prompt=prompt,
                    model_alias=model,
                    response_model=response_model,
                    status=AgentCheckpointStatus.COMPLETED,
                    messages=messages,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_eur=cost_eur,
                    tool_calls=tool_calls,
                    tool_rounds_used=tool_rounds_used,
                    repair_attempts=repair_attempts,
                    finalization_prompt_sent=finalization_prompt_sent,
                    seen_tool_signatures=seen_tool_signatures,
                    executed_tool_names=executed_tool_names,
                    pending_tool_calls=pending_tool_calls,
                    pending_tool_index=pending_tool_index,
                    result_payload=parsed.model_dump(mode="json"),
                    metrics=metrics,
                )
                return AgentExecution(result=parsed, metrics=metrics)
            except (ValidationError, ValueError, json.JSONDecodeError) as error:
                if repair_attempts >= self.settings.llm_max_retries:
                    raise ValueError(
                        f"{agent.value} did not return valid {response_model.__name__} JSON."
                    ) from error
                repair_attempts += 1
                debug_json_repair(agent.value, repair_attempts, str(error))
                if self.trace_writer is not None:
                    self.trace_writer.json_repair(
                        agent=agent.value,
                        attempt=repair_attempts,
                        error=str(error),
                    )
                messages.append(_assistant_message_payload(message))
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Return valid JSON only. "
                            f"The response must match {response_model.__name__}. "
                            f"Validation error: {error}"
                        ),
                    }
                )
                self._store_checkpoint(
                    candidate_id=checkpoint_candidate_id,
                    stage=checkpoint_stage,
                    agent=agent,
                    attempt_index=checkpoint_attempt_index,
                    prompt=prompt,
                    model_alias=model,
                    response_model=response_model,
                    status=AgentCheckpointStatus.IN_PROGRESS,
                    messages=messages,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_eur=cost_eur,
                    tool_calls=tool_calls,
                    tool_rounds_used=tool_rounds_used,
                    repair_attempts=repair_attempts,
                    finalization_prompt_sent=finalization_prompt_sent,
                    seen_tool_signatures=seen_tool_signatures,
                    executed_tool_names=executed_tool_names,
                    pending_tool_calls=pending_tool_calls,
                    pending_tool_index=pending_tool_index,
                )

        raise RuntimeError(
            f"{agent.value} exceeded the allowed completion rounds "
            f"after {tool_rounds_used} tool rounds and {tool_calls} tool calls."
        )

    def _load_checkpoint(
        self,
        *,
        candidate_id: str | None,
        stage: Stage | None,
        agent: AgentName,
        attempt_index: int,
        prompt_hash: str,
    ) -> AgentCheckpointRecord | None:
        if self.repository is None or candidate_id is None or stage is None:
            return None
        checkpoint = self.repository.load_agent_checkpoint(
            candidate_id=candidate_id,
            stage=stage,
            agent=agent,
            attempt_index=attempt_index,
        )
        if checkpoint is None:
            return None
        if checkpoint.prompt_hash != prompt_hash:
            return None
        return checkpoint

    def _store_checkpoint(
        self,
        *,
        candidate_id: str | None,
        stage: Stage | None,
        agent: AgentName,
        attempt_index: int,
        prompt: PromptBundle,
        model_alias: str,
        response_model: type[BaseModel],
        status: AgentCheckpointStatus,
        messages: list[dict[str, Any]],
        input_tokens: int,
        output_tokens: int,
        cost_eur: float,
        tool_calls: int,
        tool_rounds_used: int,
        repair_attempts: int,
        finalization_prompt_sent: bool,
        seen_tool_signatures: dict[str, int],
        executed_tool_names: set[str],
        pending_tool_calls: list[dict[str, Any]],
        pending_tool_index: int,
        result_payload: dict[str, Any] | None = None,
        metrics: ActivityMetrics | None = None,
    ) -> None:
        if self.repository is None or candidate_id is None or stage is None:
            return
        now = _now_utc()
        self.repository.store_agent_checkpoint(
            AgentCheckpointRecord(
                candidate_id=candidate_id,
                stage=stage,
                agent=agent,
                attempt_index=attempt_index,
                status=status,
                prompt_version=prompt.prompt_version,
                prompt_hash=prompt.prompt_hash,
                model_alias=model_alias,
                response_model=response_model.__name__,
                state=AgentCheckpointState(
                    messages=messages,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_eur=round(cost_eur, 6),
                    tool_calls=tool_calls,
                    tool_rounds_used=tool_rounds_used,
                    repair_attempts=repair_attempts,
                    finalization_prompt_sent=finalization_prompt_sent,
                    seen_tool_signatures=seen_tool_signatures,
                    executed_tool_names=sorted(executed_tool_names),
                    pending_tool_calls=pending_tool_calls,
                    pending_tool_index=pending_tool_index,
                    result_payload=result_payload,
                    metrics_payload=metrics.model_dump(mode="json") if metrics else None,
                ),
                created_at=now,
                updated_at=now,
            )
        )

    def _process_pending_tool_calls(
        self,
        *,
        agent: AgentName,
        round_num: int,
        messages: list[dict[str, Any]],
        tool_executor: Callable[[str, dict[str, Any]], Any],
        pending_tool_calls: list[dict[str, Any]],
        pending_tool_index: int,
        seen_tool_signatures: dict[str, int],
        executed_tool_names: set[str],
        tool_calls: int,
    ) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]], int]:
        while pending_tool_index < len(pending_tool_calls):
            tool_call = pending_tool_calls[pending_tool_index]
            arguments = json.loads(tool_call["function"]["arguments"])
            tool_name = tool_call["function"]["name"]
            tool_signature = _tool_signature(tool_name, arguments)
            if self.trace_writer is not None:
                self.trace_writer.tool_call(
                    agent=agent.value,
                    round_num=round_num,
                    tool_name=tool_name,
                    arguments=arguments,
                )
            seen_count = seen_tool_signatures.get(tool_signature, 0)
            if seen_count >= 1:
                tool_result = {
                    "status": "duplicate_call_blocked",
                    "tool": tool_name,
                    "reason": (
                        "This exact tool call was already executed. "
                        "Review the prior result and finalize unless a materially "
                        "different call is necessary."
                    ),
                }
                log_tool_exec(
                    agent.value,
                    tool_name,
                    "duplicate_call_blocked",
                    arguments=arguments,
                )
            else:
                try:
                    tool_result = tool_executor(tool_name, arguments)
                except Exception as error:
                    log_tool_exec(agent.value, tool_name, "error", arguments=arguments)
                    if self.trace_writer is not None:
                        self.trace_writer.tool_result(
                            agent=agent.value,
                            round_num=round_num,
                            tool_name=tool_name,
                            result={"error": str(error)},
                            status="error",
                        )
                    raise
                tool_status = (
                    str(tool_result.get("status", "ok"))
                    if isinstance(tool_result, dict)
                    else "ok"
                )
                log_tool_exec(
                    agent.value,
                    tool_name,
                    tool_status,
                    arguments=arguments,
                )
            seen_tool_signatures[tool_signature] = seen_count + 1
            executed_tool_names.add(tool_name)
            tool_calls += 1
            if self.trace_writer is not None:
                self.trace_writer.tool_result(
                    agent=agent.value,
                    round_num=round_num,
                    tool_name=tool_name,
                    result=tool_result,
                    status=str(tool_result.get("status", "ok"))
                    if isinstance(tool_result, dict)
                    else "ok",
                )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": tool_name,
                    "content": json.dumps(tool_result, ensure_ascii=True),
                }
            )
            pending_tool_index += 1
        return messages, tool_calls, [], 0

    def _completion(self, model: str) -> Callable[..., Any]:
        if self._completion_fn is not None:
            return self._completion_fn
        if self._should_use_proxy_mode(model):
            if self._proxy_completion_fn is not None:
                return self._proxy_completion_fn
            return self._proxy_completion()
        _configure_litellm_runtime()
        try:
            from litellm import completion
        except ImportError as error:
            raise RuntimeError(
                "LiteLLM is not installed. Run `pip install -e .[dev]` after syncing dependencies."
            ) from error
        direct_completion = cast(Callable[..., Any], completion)

        def call_direct(**kwargs: Any) -> Any:
            return direct_completion(
                **kwargs,
                **self._completion_auth_kwargs(),
            )

        return call_direct

    def _proxy_completion(self) -> Callable[..., Any]:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError(
                "openai is not installed. Run `pip install -e .[dev]` after syncing dependencies."
            ) from error

        client = OpenAI(
            api_key=self._proxy_api_key(),
            base_url=self._proxy_base_url(),
        )

        def call_proxy(**kwargs: Any) -> Any:
            proxy_kwargs = dict(kwargs)
            proxy_kwargs.pop("max_retries", None)
            return client.chat.completions.create(**proxy_kwargs)

        return call_proxy

    def _request_completion[TResponse: BaseModel](
        self,
        *,
        model: str,
        request_kwargs: dict[str, Any],
        response_model: type[TResponse],
    ) -> Any:
        completion = self._completion(model)
        if not self._should_attempt_response_schema(model, request_kwargs):
            return completion(**request_kwargs)

        schema_kwargs = dict(request_kwargs)
        schema_kwargs["response_format"] = _response_format_for_model(response_model)
        try:
            response = completion(**schema_kwargs)
            self._response_schema_support_cache[model] = True
            return response
        except Exception as error:
            if not _looks_like_response_schema_support_error(error):
                raise
            self._response_schema_support_cache[model] = False
            return completion(**request_kwargs)

    def _should_attempt_response_schema(
        self,
        model: str,
        request_kwargs: dict[str, Any],
    ) -> bool:
        if not self.settings.enable_response_schema:
            return False
        tools = request_kwargs.get("tools")
        tool_choice = request_kwargs.get("tool_choice")
        if tools is not None and tool_choice == "auto":
            return False
        cached_support = self._response_schema_support_cache.get(model)
        if cached_support is not None:
            return cached_support
        if self._should_use_proxy_mode(model):
            return True
        _configure_litellm_runtime()
        try:
            from litellm import get_llm_provider, supports_response_schema
        except ImportError:
            return False
        provider: str | None = None
        try:
            _, provider, _, _ = get_llm_provider(
                model=model,
                api_base=self.settings.litellm_api_base,
            )
        except Exception:
            provider = None
        try:
            supported = bool(supports_response_schema(model=model, custom_llm_provider=provider))
            self._response_schema_support_cache[model] = supported
            return supported
        except Exception:
            return False

    def _completion_cost(self, response: Any, model: str, request_kwargs: dict[str, Any]) -> float:
        if self._cost_calculator is not None:
            return self._cost_calculator(response, model)
        _configure_litellm_runtime()
        try:
            from litellm import completion_cost, get_llm_provider, response_cost_calculator
        except ImportError:
            return 0.0
        optional_params = _cost_optional_params(request_kwargs)
        provider: str | None = None
        try:
            _, provider, _, _ = get_llm_provider(
                model=model,
                api_base=self.settings.litellm_api_base,
            )
        except Exception:
            provider = None
        try:
            response_cost = float(
                response_cost_calculator(
                    response_object=response,
                    model=model,
                    custom_llm_provider=provider,
                    call_type="completion",
                    optional_params=optional_params,
                )
            )
            if response_cost > 0:
                return response_cost
        except Exception:
            pass
        try:
            return float(
                completion_cost(
                    completion_response=response,
                    model=model,
                    call_type="completion",
                    custom_llm_provider=provider,
                    optional_params=optional_params,
                )
            )
        except Exception:
            return 0.0

    def _completion_auth_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.settings.litellm_api_key is not None:
            kwargs["api_key"] = self.settings.litellm_api_key.get_secret_value()
        if self.settings.litellm_api_base is not None:
            kwargs["api_base"] = self.settings.litellm_api_base
        return kwargs

    def _should_use_proxy_mode(self, model: str) -> bool:
        return self.settings.litellm_api_base is not None and "/" not in model

    def _proxy_api_key(self) -> str:
        if self.settings.litellm_api_key is not None:
            return self.settings.litellm_api_key.get_secret_value()
        return "anything"

    def _proxy_base_url(self) -> str:
        api_base = self.settings.litellm_api_base
        if api_base is None:
            raise ValueError("TRUTH_ENGINE_LITELLM_API_BASE is required for proxy mode.")
        if api_base.rstrip("/").endswith("/v1"):
            return api_base
        return f"{api_base.rstrip('/')}/v1"


def _usage_value(response: Any, key: str) -> int:
    usage = (
        response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
    )
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return int(usage.get(key, 0))
    return int(getattr(usage, key, 0))


def _choice_message(response: Any) -> Any:
    if isinstance(response, dict):
        return response["choices"][0]["message"]
    return response.choices[0].message


def _assistant_message_payload(message: Any) -> dict[str, Any]:
    if hasattr(message, "model_dump"):
        payload = message.model_dump(exclude_none=True)
        if isinstance(payload, dict):
            return payload
    if isinstance(message, dict):
        return dict(message)
    return {
        "role": getattr(message, "role", "assistant"),
        "content": getattr(message, "content", None),
        "tool_calls": getattr(message, "tool_calls", None),
    }


def _message_tool_calls(message: Any) -> list[dict[str, Any]]:
    tool_calls = (
        message.get("tool_calls")
        if isinstance(message, dict)
        else getattr(message, "tool_calls", None)
    )
    if tool_calls is None:
        return []
    normalized: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        if hasattr(tool_call, "model_dump"):
            payload = tool_call.model_dump(exclude_none=True)
        else:
            payload = dict(tool_call)
        normalized.append(payload)
    return normalized


def _message_content(message: Any) -> str:
    content = (
        message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    )
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _parse_response_model[T: BaseModel](content: str, response_model: type[T]) -> T:
    json_text = _extract_json_text(content)
    payload = json.loads(json_text)
    return response_model.model_validate(payload)


def _extract_json_text(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    start = min(
        [index for index in (stripped.find("{"), stripped.find("[")) if index != -1],
        default=-1,
    )
    if start == -1:
        raise ValueError("No JSON object found in model response.")
    return stripped[start:]


def _tool_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    return f"{tool_name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=True)}"


def _tool_names(tools: list[dict[str, Any]] | None) -> list[str]:
    if tools is None:
        return []
    names: list[str] = []
    for tool in tools:
        function_block = tool.get("function")
        if isinstance(function_block, dict):
            name = function_block.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def _reasoning_effort_for_model(
    *,
    model: str,
    configured_effort: str | None,
) -> str | None:
    if configured_effort is None:
        return None
    normalized = model.lower()
    supported_prefixes = (
        "gpt-5",
        "openai/gpt-5",
        "openai/responses/gpt-5",
        "o1",
        "openai/o1",
        "o3",
        "openai/o3",
        "o4",
        "openai/o4",
        "claude-3.7",
        "anthropic/claude-3.7",
        "claude-4",
        "anthropic/claude-4",
        "magistral",
        "mistral/magistral",
    )
    return configured_effort if normalized.startswith(supported_prefixes) else None


def _should_omit_temperature(
    *,
    model: str,
    reasoning_effort: str | None,
) -> bool:
    if reasoning_effort is None:
        return False
    normalized = model.lower()
    return normalized.startswith(("gpt-5", "openai/gpt-5", "openai/responses/gpt-5"))


def _response_format_for_model[TResponse: BaseModel](
    response_model: type[TResponse],
) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_model.__name__,
            "schema": response_model.model_json_schema(),
            "strict": True,
        },
    }


def _looks_like_response_schema_support_error(error: BaseException) -> bool:
    message = str(error).lower()
    response_schema_markers = (
        "json_schema",
        "json schema",
        "response_format",
        "response schema",
        "response_schema",
        "structured outputs",
    )
    support_failure_markers = (
        "invalid parameter",
        "not supported",
        "unsupported",
        "unknown parameter",
        "unrecognized request argument",
    )
    return any(marker in message for marker in response_schema_markers) and any(
        marker in message for marker in support_failure_markers
    )


def _cost_optional_params(request_kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in request_kwargs.items()
        if key not in {"max_retries", "messages", "model"} and value is not None
    }


def _configure_litellm_runtime() -> None:
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    os.environ.setdefault("LITELLM_LOG", "ERROR")
    try:
        import litellm
    except ImportError:
        return

    litellm.suppress_debug_info = True
    litellm.turn_off_message_logging = True
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
    logging.getLogger("LiteLLM Router").setLevel(logging.ERROR)
    logging.getLogger("LiteLLM Proxy").setLevel(logging.ERROR)


def _now_utc() -> datetime:
    return datetime.now(UTC)
