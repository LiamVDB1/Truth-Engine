"""Structured logging for the Truth Engine workflow.

Two-tier design:
- INFO level  → clean flow view (one line per stage start, gate decision, outcome)
- DEBUG level → detailed LLM calls, tool executions, token counts, JSON repair

Set TRUTH_ENGINE_LOG_LEVEL=DEBUG to see everything.
Default INFO gives a compact, readable process overview.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_FLOW_PREFIX = "\033[36m⟩\033[0m"  # cyan arrow for flow events
_GATE_ADVANCE = "\033[32m✓\033[0m"  # green check
_GATE_KILL = "\033[31m✗\033[0m"  # red cross
_GATE_INVESTIGATE = "\033[33m?\033[0m"  # yellow question
_GATE_RETRY = "\033[33m↻\033[0m"  # yellow retry
_COST = "\033[90m€\033[0m"  # dim euro

_ACTION_ICONS = {
    "advance": _GATE_ADVANCE,
    "advance_with_caution": "\033[33m✓\033[0m",  # yellow check
    "investigate": _GATE_INVESTIGATE,
    "retry": _GATE_RETRY,
    "revise": _GATE_RETRY,
    "kill": _GATE_KILL,
}


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging for Truth Engine.

    Call once at startup (CLI entry point).
    """
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger("truth_engine")
    if root.handlers:
        return  # already configured

    handler = logging.StreamHandler(sys.stderr)
    if resolved_level <= logging.DEBUG:
        fmt = "%(asctime)s %(levelname)-5s %(name)s │ %(message)s"
    else:
        fmt = "%(message)s"  # flow view: just the message
    handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    root.addHandler(handler)
    root.setLevel(resolved_level)


# ── Flow-level events (INFO) ─────────────────────────────────


def flow_stage_start(
    candidate_id: str,
    stage: str,
    agent: str,
    *,
    attempt: int = 0,
    extra: str = "",
) -> None:
    """Log the start of an agent stage (INFO)."""
    logger = logging.getLogger("truth_engine.flow")
    attempt_str = f" (attempt {attempt + 1})" if attempt > 0 else ""
    suffix = f"  {extra}" if extra else ""
    logger.info(
        "%s %s │ %s │ %s ▶ starting%s%s",
        _FLOW_PREFIX,
        candidate_id,
        stage,
        agent,
        attempt_str,
        suffix,
    )


def flow_stage_done(
    candidate_id: str,
    stage: str,
    agent: str,
    *,
    cost_eur: float = 0.0,
    summary: str = "",
) -> None:
    """Log the completion of an agent stage (INFO)."""
    logger = logging.getLogger("truth_engine.flow")
    cost_str = f"  {_COST}{cost_eur:.4f}" if cost_eur > 0 else ""
    summary_str = f"  {summary}" if summary else ""
    logger.info(
        "%s %s │ %s │ %s %s done%s%s",
        _FLOW_PREFIX,
        candidate_id,
        stage,
        agent,
        _GATE_ADVANCE,
        cost_str,
        summary_str,
    )


def flow_gate_decision(
    candidate_id: str,
    gate: str,
    action: str,
    reason: str,
    *,
    score: int | None = None,
    budget_mode: str = "normal",
) -> None:
    """Log a gate decision (INFO)."""
    logger = logging.getLogger("truth_engine.flow")
    icon = _ACTION_ICONS.get(action, "·")
    score_str = f"  score={score}" if score is not None else ""
    budget_str = f"  [{budget_mode}]" if budget_mode != "normal" else ""
    logger.info(
        "%s %s │ %s │ %s %s%s%s  — %s",
        _FLOW_PREFIX,
        candidate_id,
        gate,
        icon,
        action.upper(),
        score_str,
        budget_str,
        reason,
    )


def flow_outcome(
    candidate_id: str,
    status: str,
    *,
    total_cost_eur: float = 0.0,
) -> None:
    """Log the final workflow outcome (INFO)."""
    logger = logging.getLogger("truth_engine.flow")
    icon = _GATE_ADVANCE if status == "passed_gate_b" else _GATE_KILL
    logger.info("")
    logger.info(
        "%s %s │ %s %s │ total %s%.4f",
        _FLOW_PREFIX,
        candidate_id,
        icon,
        status.upper().replace("_", " "),
        _COST,
        total_cost_eur,
    )
    logger.info("")


def flow_budget_warning(
    candidate_id: str,
    budget_mode: str,
    total_cost_eur: float,
) -> None:
    """Log a budget mode transition (INFO)."""
    logger = logging.getLogger("truth_engine.flow")
    if budget_mode == "degrade":
        logger.info(
            "%s %s │ ⚠ BUDGET DEGRADE │ spent %s%.4f > €5.00 target",
            _FLOW_PREFIX,
            candidate_id,
            _COST,
            total_cost_eur,
        )
    elif budget_mode == "safety_cap":
        logger.info(
            "%s %s │ 🛑 SAFETY CAP │ spent %s%.4f > €7.00 cap",
            _FLOW_PREFIX,
            candidate_id,
            _COST,
            total_cost_eur,
        )


# ── Debug-level events ────────────────────────────────────────


def debug_llm_call(
    agent: str,
    model: str,
    *,
    round_num: int,
    input_tokens: int,
    output_tokens: int,
    cost_eur: float,
    tool_calls: int = 0,
) -> None:
    """Log a single LLM completion call (DEBUG)."""
    logger = logging.getLogger("truth_engine.llm")
    logger.debug(
        "LLM call │ %s │ model=%s round=%d │ in=%d out=%d cost=€%.6f tools=%d",
        agent,
        model,
        round_num,
        input_tokens,
        output_tokens,
        cost_eur,
        tool_calls,
    )


def debug_tool_exec(agent: str, tool_name: str, status: str) -> None:
    """Log a tool execution (DEBUG)."""
    logger = logging.getLogger("truth_engine.tools")
    logger.debug("Tool exec │ %s │ %s → %s", agent, tool_name, status)


def debug_json_repair(agent: str, attempt: int, error: str) -> None:
    """Log a JSON repair attempt (DEBUG)."""
    logger = logging.getLogger("truth_engine.llm")
    logger.debug("JSON repair │ %s │ attempt=%d │ %s", agent, attempt, error)


def debug_adapter(adapter: str, operation: str, **fields: Any) -> None:
    """Log an adapter call (DEBUG)."""
    logger = logging.getLogger("truth_engine.adapters")
    field_str = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.debug("Adapter │ %s │ %s │ %s", adapter, operation, field_str)
