"""Extract structured learnings from completed candidates.

Each candidate — whether killed or passed — teaches something reusable.
Learnings are persisted and fed into future Scout prompt contexts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from truth_engine.contracts.stages import (
    CandidateDossier,
    EvaluatedArena,
    ScoredCandidate,
    SkepticReport,
)


@dataclass(frozen=True, slots=True)
class LearningEntry:
    """A single learning extracted from a candidate run."""

    candidate_id: str
    insight: str
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def extract_kill_learnings(
    candidate_id: str,
    kill_reason: str,
    *,
    arena: EvaluatedArena | None = None,
    scoring: ScoredCandidate | None = None,
    skeptic: SkepticReport | None = None,
) -> list[LearningEntry]:
    """Extract 2-4 learnings from a killed candidate."""
    entries: list[LearningEntry] = []

    arena_domain = arena.arena.domain if arena else "unknown arena"
    entries.append(
        LearningEntry(
            candidate_id=candidate_id,
            insight=(
                f"Candidate in '{arena_domain}' was killed: {kill_reason}. "
                "Consider pre-filtering arenas with similar traits."
            ),
            tags=["kill", "arena_filter"],
        )
    )

    if scoring and scoring.total_score < 40:
        weak_dims = [
            dim_name for dim_name, dim_score in scoring.dimension_scores.items() if dim_score <= 3
        ]
        if weak_dims:
            entries.append(
                LearningEntry(
                    candidate_id=candidate_id,
                    insight=(
                        f"Scored {scoring.total_score}/100 with weak dimensions: "
                        f"{', '.join(weak_dims)}. "
                        "These signal areas need stronger evidence before advancing."
                    ),
                    tags=["kill", "scoring", "weak_dimensions"],
                )
            )

    if skeptic:
        if skeptic.risk_flags:
            entries.append(
                LearningEntry(
                    candidate_id=candidate_id,
                    insight=(
                        f"Skeptic flagged: {'; '.join(skeptic.risk_flags[:3])}. "
                        "Watch for these patterns in similar arenas."
                    ),
                    tags=["kill", "skeptic_flags"],
                )
            )
        if skeptic.primary_weakness:
            entries.append(
                LearningEntry(
                    candidate_id=candidate_id,
                    insight=(
                        f"Primary weakness at kill: {skeptic.primary_weakness}. "
                        "Future candidates in this space should validate this early."
                    ),
                    tags=["kill", "primary_weakness"],
                )
            )

    return entries[:4]


def extract_pass_learnings(
    candidate_id: str,
    dossier: CandidateDossier,
) -> list[LearningEntry]:
    """Extract 2-4 learnings from a candidate that passed Gate B."""
    entries: list[LearningEntry] = []

    entries.append(
        LearningEntry(
            candidate_id=candidate_id,
            insight=(
                f"Candidate in '{dossier.arena.arena.domain}' passed Gate B "
                f"with score {dossier.scoring.total_score}/100. "
                f"Wedge: {dossier.selected_wedge.wedge_promise[:80]}."
            ),
            tags=["pass", "success_pattern"],
        )
    )

    strong_dims = [
        dim_name
        for dim_name, dim_score in dossier.scoring.dimension_scores.items()
        if dim_score >= 8
    ]
    if strong_dims:
        entries.append(
            LearningEntry(
                candidate_id=candidate_id,
                insight=(
                    f"Strongest dimensions: {', '.join(strong_dims)}. "
                    "Arenas with similar strength profiles may be worth prioritizing."
                ),
                tags=["pass", "strong_dimensions"],
            )
        )

    channel_names = [ch.channel for ch in dossier.channel_validation.channels[:3]]
    if channel_names:
        entries.append(
            LearningEntry(
                candidate_id=candidate_id,
                insight=(
                    f"Reachable via channels: {', '.join(channel_names)} "
                    f"with {dossier.channel_validation.total_reachable_leads} leads. "
                    "This channel mix worked for this ICP."
                ),
                tags=["pass", "channels"],
            )
        )

    return entries[:4]
