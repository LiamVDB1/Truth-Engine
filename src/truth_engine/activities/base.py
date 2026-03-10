from __future__ import annotations

from typing import Protocol

from truth_engine.contracts.fixtures import (
    ArenaDiscoveryFixture,
    ChannelValidationFixtureRun,
    LandscapeResearchFixture,
    NormalizationFixtureRun,
    ScoringFixtureRun,
    SignalMiningFixtureRun,
    SkepticFixtureRun,
    WedgeCritiqueFixtureRun,
    WedgeDesignFixtureRun,
)


class ActivityBundle(Protocol):
    persists_tool_state: bool

    @property
    def candidate_id(self) -> str: ...

    def arena_discovery(self) -> ArenaDiscoveryFixture: ...

    def signal_mining(self, targeted_weakness: str | None = None) -> SignalMiningFixtureRun: ...

    def normalization(self) -> NormalizationFixtureRun: ...

    def landscape_research(self) -> LandscapeResearchFixture: ...

    def scoring(self) -> ScoringFixtureRun: ...

    def skeptic(self) -> SkepticFixtureRun: ...

    def wedge_design(self) -> WedgeDesignFixtureRun: ...

    def wedge_critique(self) -> WedgeCritiqueFixtureRun: ...

    def channel_validation(self) -> ChannelValidationFixtureRun: ...
