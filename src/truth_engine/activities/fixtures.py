from __future__ import annotations

from pathlib import Path

from truth_engine.contracts.fixtures import (
    ArenaDiscoveryFixture,
    ChannelValidationFixtureRun,
    FixtureScenario,
    LandscapeResearchFixture,
    NormalizationFixtureRun,
    ScoringFixtureRun,
    SignalMiningFixtureRun,
    SkepticFixtureRun,
    WedgeCritiqueFixtureRun,
    WedgeDesignFixtureRun,
)


class FixtureActivityBundle:
    persists_tool_state = False

    def __init__(self, scenario: FixtureScenario):
        self.scenario = scenario
        self._signal_index = 0
        self._normalization_index = 0
        self._scoring_index = 0
        self._skeptic_index = 0
        self._wedge_design_index = 0
        self._wedge_critique_index = 0
        self._channel_validation_index = 0
        self._landscape_consumed = False

    @classmethod
    def from_path(cls, path: Path) -> FixtureActivityBundle:
        return cls(FixtureScenario.from_path(path))

    @property
    def candidate_id(self) -> str:
        return self.scenario.candidate_id

    def arena_discovery(self) -> ArenaDiscoveryFixture:
        return self.scenario.arena_discovery

    def signal_mining(self, targeted_weakness: str | None = None) -> SignalMiningFixtureRun:
        run = self._take(self.scenario.signal_mining_runs, self._signal_index, "signal")
        expected = run.targeted_weakness
        if expected != targeted_weakness:
            raise ValueError(
                "Signal run "
                f"{self._signal_index} expected weakness {expected!r}, "
                f"got {targeted_weakness!r}"
            )
        self._signal_index += 1
        return run

    def normalization(self) -> NormalizationFixtureRun:
        run = self._take(
            self.scenario.normalization_runs,
            self._normalization_index,
            "normalization",
        )
        self._normalization_index += 1
        return run

    def landscape_research(self) -> LandscapeResearchFixture:
        if self._landscape_consumed:
            raise ValueError("Landscape research fixture can only be consumed once.")
        self._landscape_consumed = True
        return self.scenario.landscape_research

    def scoring(self) -> ScoringFixtureRun:
        run = self._take(self.scenario.scoring_runs, self._scoring_index, "scoring")
        self._scoring_index += 1
        return run

    def skeptic(self) -> SkepticFixtureRun:
        run = self._take(self.scenario.skeptic_runs, self._skeptic_index, "skeptic")
        self._skeptic_index += 1
        return run

    def wedge_design(self) -> WedgeDesignFixtureRun:
        run = self._take(
            self.scenario.wedge_design_runs,
            self._wedge_design_index,
            "wedge_design",
        )
        self._wedge_design_index += 1
        return run

    def wedge_critique(self) -> WedgeCritiqueFixtureRun:
        run = self._take(
            self.scenario.wedge_critique_runs, self._wedge_critique_index, "wedge_critique"
        )
        self._wedge_critique_index += 1
        return run

    def channel_validation(self) -> ChannelValidationFixtureRun:
        run = self._take(
            self.scenario.channel_validation_runs,
            self._channel_validation_index,
            "channel_validation",
        )
        self._channel_validation_index += 1
        return run

    @staticmethod
    def _take[T](items: list[T], index: int, name: str) -> T:
        if index >= len(items):
            raise ValueError(f"No remaining {name} fixture at index {index}")
        return items[index]
