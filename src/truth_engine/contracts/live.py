from __future__ import annotations

from pathlib import Path

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
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    focus: str
    founder_constraints: FounderConstraints = Field(default_factory=FounderConstraints)
    seed_queries: list[str] = Field(default_factory=list)
    source_targets: list[str] = Field(
        default_factory=lambda: ["reddit", "job_postings", "public_web"]
    )
    max_arena_proposals: int = Field(default=6, ge=1, le=8)
    max_signals: int = Field(default=60, ge=10, le=200)
    search_results_per_query: int = Field(default=5, ge=1, le=10)
    notes: str | None = None

    @classmethod
    def from_path(cls, path: Path) -> LiveRunRequest:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
