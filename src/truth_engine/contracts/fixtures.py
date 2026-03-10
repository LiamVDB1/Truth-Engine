from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .models import RawArena, RawSignal
from .stages import (
    ActivityMetrics,
    ArenaEvaluation,
    ArenaSearchResult,
    ChannelValidation,
    LandscapeEntry,
    LandscapeReport,
    NormalizationResult,
    ScoringResult,
    SignalMiningResult,
    SkepticReport,
    WedgeCritique,
    WedgeProposal,
)


class ArenaDiscoveryFixture(BaseModel):
    model_config = ConfigDict(frozen=True)

    scout_metrics: ActivityMetrics
    evaluator_metrics: ActivityMetrics
    search_result: ArenaSearchResult
    raw_arenas: list[RawArena]
    evaluation: ArenaEvaluation


class SignalMiningFixtureRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    targeted_weakness: str | None = None
    metrics: ActivityMetrics
    result: SignalMiningResult
    raw_signals: list[RawSignal]


class NormalizationFixtureRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    metrics: ActivityMetrics
    result: NormalizationResult


class LandscapeResearchFixture(BaseModel):
    model_config = ConfigDict(frozen=True)

    metrics: ActivityMetrics
    result: LandscapeReport
    entries: list[LandscapeEntry]


class ScoringFixtureRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    metrics: ActivityMetrics
    result: ScoringResult


class SkepticFixtureRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    metrics: ActivityMetrics
    result: SkepticReport


class WedgeDesignFixtureRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    metrics: ActivityMetrics
    result: WedgeProposal


class WedgeCritiqueFixtureRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    metrics: ActivityMetrics
    result: WedgeCritique


class ChannelValidationFixtureRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    metrics: ActivityMetrics
    result: ChannelValidation


class FixtureScenario(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str
    arena_discovery: ArenaDiscoveryFixture
    signal_mining_runs: list[SignalMiningFixtureRun]
    normalization_runs: list[NormalizationFixtureRun]
    landscape_research: LandscapeResearchFixture
    scoring_runs: list[ScoringFixtureRun]
    skeptic_runs: list[SkepticFixtureRun]
    wedge_design_runs: list[WedgeDesignFixtureRun]
    wedge_critique_runs: list[WedgeCritiqueFixtureRun]
    channel_validation_runs: list[ChannelValidationFixtureRun]

    @classmethod
    def from_path(cls, path: Path) -> FixtureScenario:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
