from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from truth_engine.config.model_routing import resolve_agent_model
from truth_engine.config.settings import Settings
from truth_engine.contracts.stages import ActivityMetrics
from truth_engine.domain.enums import AgentName
from truth_engine.prompts.builder import PromptBundle
from truth_engine.services.logging import debug_json_repair, debug_llm_call, debug_tool_exec

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
        completion_fn: Callable[..., Any] | None = None,
        cost_calculator: Callable[[Any, str], float] | None = None,
    ):
        self.settings = settings
        self._completion_fn = completion_fn
        self._cost_calculator = cost_calculator

    def run(
        self,
        *,
        agent: AgentName,
        prompt: PromptBundle,
        response_model: type[T],
        tools: list[dict[str, Any]] | None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None,
    ) -> AgentExecution[T]:
        model = resolve_agent_model(agent, self.settings)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": prompt.system_prompt},
            {"role": "user", "content": prompt.user_prompt},
        ]

        input_tokens = 0
        output_tokens = 0
        cost_eur = 0.0
        tool_calls = 0
        repair_attempts = 0

        max_rounds = self.settings.agent_max_tool_rounds + self.settings.llm_max_retries + 1
        for _round in range(max_rounds):
            response = self._completion()(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto" if tools else None,
                temperature=self.settings.llm_temperature,
                max_retries=self.settings.llm_max_retries,
                **self._completion_auth_kwargs(),
            )
            input_tokens += int(_usage_value(response, "prompt_tokens"))
            output_tokens += int(_usage_value(response, "completion_tokens"))
            round_cost = self._completion_cost(response, model)
            cost_eur += round_cost

            message = _choice_message(response)
            parsed_tool_calls = _message_tool_calls(message)
            if parsed_tool_calls:
                if tool_executor is None:
                    raise ValueError("Tool calls were returned without a tool executor.")
                messages.append(_assistant_message_payload(message))
                for tool_call in parsed_tool_calls:
                    arguments = json.loads(tool_call["function"]["arguments"])
                    tool_name = tool_call["function"]["name"]
                    tool_result = tool_executor(tool_name, arguments)
                    tool_calls += 1
                    debug_tool_exec(agent.value, tool_name, "ok")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": tool_name,
                            "content": json.dumps(tool_result, ensure_ascii=True),
                        }
                    )
                debug_llm_call(
                    agent.value,
                    model,
                    round_num=_round + 1,
                    input_tokens=int(_usage_value(response, "prompt_tokens")),
                    output_tokens=int(_usage_value(response, "completion_tokens")),
                    cost_eur=round_cost,
                    tool_calls=len(parsed_tool_calls),
                )
                continue

            content = _message_content(message)
            try:
                parsed = _parse_response_model(content, response_model)
                debug_llm_call(
                    agent.value,
                    model,
                    round_num=_round + 1,
                    input_tokens=int(_usage_value(response, "prompt_tokens")),
                    output_tokens=int(_usage_value(response, "completion_tokens")),
                    cost_eur=round_cost,
                )
                return AgentExecution(
                    result=parsed,
                    metrics=ActivityMetrics(
                        cost_eur=round(cost_eur, 6),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        tool_calls=tool_calls,
                    ),
                )
            except (ValidationError, ValueError, json.JSONDecodeError) as error:
                if repair_attempts >= self.settings.llm_max_retries:
                    raise ValueError(
                        f"{agent.value} did not return valid {response_model.__name__} JSON."
                    ) from error
                repair_attempts += 1
                debug_json_repair(agent.value, repair_attempts, str(error))
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

        raise RuntimeError(f"{agent.value} exceeded the allowed completion rounds.")

    def _completion(self) -> Callable[..., Any]:
        if self._completion_fn is not None:
            return self._completion_fn
        try:
            from litellm import completion
        except ImportError as error:
            raise RuntimeError(
                "LiteLLM is not installed. Run `pip install -e .[dev]` after syncing dependencies."
            ) from error
        return cast(Callable[..., Any], completion)

    def _completion_cost(self, response: Any, model: str) -> float:
        if self._cost_calculator is not None:
            return self._cost_calculator(response, model)
        try:
            from litellm import completion_cost
        except ImportError:
            return 0.0
        try:
            return float(completion_cost(completion_response=response, model=model))
        except Exception:
            return 0.0

    def _completion_auth_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.settings.litellm_api_key is not None:
            kwargs["api_key"] = self.settings.litellm_api_key.get_secret_value()
        elif self.settings.openai_api_key is not None:
            api_key = self.settings.openai_api_key.get_secret_value()
            kwargs["api_key"] = api_key
            os.environ.setdefault("OPENAI_API_KEY", api_key)
        if self.settings.litellm_api_base is not None:
            kwargs["api_base"] = self.settings.litellm_api_base
        return kwargs


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
