from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class FounderConstraints(BaseModel):
    model_config = ConfigDict(frozen=True)

    solution_modalities: list[str] = Field(
        default_factory=lambda: [
            "saas",
            "api",
            "tool",
            "browser_extension",
            "automation",
            "integration",
        ]
    )
    excluded_business_models: list[str] = Field(
        default_factory=lambda: [
            "physical_operations",
            "manual_service_delivery",
            "brick_and_mortar_ownership",
        ]
    )
    target_market: str = "any"
    geo_preference: str = "EU + US"
    v1_filter: str = "software_first"


class LiveRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:10]}")
    founder_constraints: FounderConstraints = Field(default_factory=FounderConstraints)

    @classmethod
    def from_path(cls, path: Path) -> LiveRunRequest:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    @classmethod
    def default(cls) -> LiveRunRequest:
        return cls()
