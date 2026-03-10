from __future__ import annotations

from dataclasses import dataclass

from truth_engine.domain.enums import ToolCostClass, ToolSideEffectLevel


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    side_effect_level: ToolSideEffectLevel
    cost_class: ToolCostClass
    adapter_key: str
