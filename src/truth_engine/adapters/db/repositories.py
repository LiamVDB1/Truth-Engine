from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, create_engine, delete, func, insert, select, update
from sqlalchemy.engine import Connection, RowMapping

from truth_engine.contracts.checkpoints import (
    AgentCheckpointRecord,
    CandidateStageRunRecord,
)
from truth_engine.contracts.models import CostRecord, ProblemUnit, RawArena, RawSignal
from truth_engine.contracts.stages import (
    ActivityMetrics,
    ArenaEvaluation,
    CandidateDossier,
    CandidateRecord,
    DecisionEvent,
    EvaluatedArena,
    LandscapeEntry,
)
from truth_engine.domain.enums import (
    AgentCheckpointStatus,
    AgentName,
    GateAction,
    Stage,
)

from .schema import (
    agent_checkpoint_table,
    candidate_stage_run_table,
    candidate_table,
    channel_plan_table,
    cost_log_table,
    decision_event_table,
    landscape_entry_table,
    learning_entry_table,
    metadata,
    problem_unit_evidence_table,
    problem_unit_table,
    processed_source_table,
    raw_arena_table,
    raw_signal_table,
    wedge_hypothesis_table,
)


class TruthEngineRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    @classmethod
    def from_database_url(cls, database_url: str) -> TruthEngineRepository:
        return cls(create_engine(database_url, future=True))

    def create_schema(self) -> None:
        metadata.create_all(self.engine)

    def create_candidate(
        self,
        candidate_id: str,
        status: str,
        *,
        request_payload: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now()
        payload = {
            "candidate_id": candidate_id,
            "status": status,
            "current_stage": None,
            "caution_flag": False,
            "selected_arena_id": None,
            "selected_problem_unit_id": None,
            "selected_wedge_id": None,
            "total_cost_eur": 0.0,
            "dossier_payload": None,
            "request_payload": request_payload,
            "created_at": now,
            "updated_at": now,
        }
        with self.engine.begin() as connection:
            connection.execute(insert(candidate_table).values(**payload))

    def get_candidate(self, candidate_id: str) -> CandidateRecord | None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(candidate_table).where(candidate_table.c.candidate_id == candidate_id)
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _candidate_from_row(row)

    def update_candidate(self, candidate_id: str, **fields: Any) -> None:
        fields["updated_at"] = _utc_now()
        with self.engine.begin() as connection:
            connection.execute(
                update(candidate_table)
                .where(candidate_table.c.candidate_id == candidate_id)
                .values(**fields)
            )

    def increment_candidate_cost(self, candidate_id: str, amount: float) -> None:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Unknown candidate: {candidate_id}")
        self.update_candidate(candidate_id, total_cost_eur=candidate.total_cost_eur + amount)

    def add_arena_proposal(
        self,
        candidate_id: str,
        arena: RawArena,
        status: str = "proposed",
    ) -> dict[str, str]:
        arena_id = arena.id or _new_id("arena")
        now = _utc_now()
        with self.engine.begin() as connection:
            existing_match = (
                connection.execute(
                    select(raw_arena_table.c.id).where(
                        raw_arena_table.c.candidate_id == candidate_id,
                        raw_arena_table.c.fingerprint == arena.fingerprint(),
                    )
                )
                .scalars()
                .first()
            )
            if existing_match is not None:
                return {"status": "exists", "arena_id": str(existing_match)}
            killed_match = connection.execute(
                select(raw_arena_table.c.id).where(
                    raw_arena_table.c.fingerprint == arena.fingerprint(),
                    raw_arena_table.c.status == "killed",
                )
            ).scalar_one_or_none()
            if killed_match is not None:
                return {"status": "blocked", "arena_id": str(killed_match)}

            connection.execute(
                insert(raw_arena_table).values(
                    id=arena_id,
                    candidate_id=candidate_id,
                    fingerprint=arena.fingerprint(),
                    status=status,
                    payload=arena.model_copy(update={"id": arena_id}).model_dump(mode="json"),
                    created_at=now,
                    updated_at=now,
                )
            )
        return {"status": "created", "arena_id": arena_id}

    def update_arena_proposal(
        self,
        candidate_id: str,
        arena_id: str,
        changes: dict[str, Any],
    ) -> dict[str, str]:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(raw_arena_table).where(
                        raw_arena_table.c.candidate_id == candidate_id,
                        raw_arena_table.c.id == arena_id,
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ValueError(f"Unknown arena proposal: {arena_id}")
            payload = dict(row["payload"])
            payload.update(changes)
            arena = RawArena.model_validate(payload)
            connection.execute(
                update(raw_arena_table)
                .where(
                    raw_arena_table.c.candidate_id == candidate_id,
                    raw_arena_table.c.id == arena_id,
                )
                .values(
                    fingerprint=arena.fingerprint(),
                    payload=arena.model_dump(mode="json"),
                    updated_at=_utc_now(),
                )
            )
        return {"status": "updated", "arena_id": arena_id}

    def remove_arena_proposal(self, candidate_id: str, arena_id: str) -> dict[str, str]:
        with self.engine.begin() as connection:
            connection.execute(
                delete(raw_arena_table).where(
                    raw_arena_table.c.candidate_id == candidate_id,
                    raw_arena_table.c.id == arena_id,
                )
            )
        return {"status": "removed", "arena_id": arena_id}

    def list_arena_proposals(self, candidate_id: str) -> list[dict[str, str]]:
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(raw_arena_table.c.payload).where(
                        raw_arena_table.c.candidate_id == candidate_id
                    )
                )
                .scalars()
                .all()
            )
        summaries: list[dict[str, str]] = []
        for payload in rows:
            arena = RawArena.model_validate(payload)
            summaries.append(
                {
                    "id": arena.id or "",
                    "domain": arena.domain,
                    "icp_user_role": arena.icp_user_role,
                    "rationale": arena.rationale,
                }
            )
        return summaries

    def load_arena_proposals(self, candidate_id: str) -> list[RawArena]:
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(raw_arena_table.c.payload).where(
                        raw_arena_table.c.candidate_id == candidate_id
                    )
            )
                .scalars()
                .all()
            )
        return [RawArena.model_validate(payload) for payload in rows]

    def claim_next_unexplored_arena(self) -> QueuedArenaSeed | None:
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(
                        raw_arena_table.c.id,
                        raw_arena_table.c.candidate_id,
                        raw_arena_table.c.payload,
                        raw_arena_table.c.created_at,
                    )
                    .where(raw_arena_table.c.status == "proposed")
                    .order_by(raw_arena_table.c.created_at, raw_arena_table.c.id)
                )
                .mappings()
                .all()
            )
            if not rows:
                return None

            rows_by_candidate: dict[str, list[RowMapping]] = {}
            ordered_candidate_ids: list[str] = []
            for row in rows:
                candidate_id = str(row["candidate_id"])
                if candidate_id not in rows_by_candidate:
                    rows_by_candidate[candidate_id] = []
                    ordered_candidate_ids.append(candidate_id)
                rows_by_candidate[candidate_id].append(row)

            for candidate_id in ordered_candidate_ids:
                candidate_rows = rows_by_candidate[candidate_id]
                chosen_row, evaluation = _pick_seeded_arena(
                    connection,
                    candidate_id,
                    candidate_rows,
                )
                claimed = connection.execute(
                    update(raw_arena_table)
                    .where(
                        raw_arena_table.c.id == chosen_row["id"],
                        raw_arena_table.c.status == "proposed",
                    )
                    .values(status="transferred", updated_at=_utc_now())
                )
                if claimed.rowcount != 1:
                    continue

                request_payload = connection.execute(
                    select(candidate_table.c.request_payload).where(
                        candidate_table.c.candidate_id == candidate_id
                    )
                ).scalar_one_or_none()
                return QueuedArenaSeed(
                    arena=RawArena.model_validate(chosen_row["payload"]),
                    evaluated_arena=evaluation,
                    request_payload=(
                        dict(request_payload) if isinstance(request_payload, dict) else None
                    ),
                )
        return None

    def set_selected_arena(self, candidate_id: str, arena_id: str) -> None:
        self.update_candidate(candidate_id, selected_arena_id=arena_id)
        with self.engine.begin() as connection:
            connection.execute(
                update(raw_arena_table)
                .where(
                    raw_arena_table.c.candidate_id == candidate_id,
                    raw_arena_table.c.id == arena_id,
                )
                .values(status="selected", updated_at=_utc_now())
            )

    def add_raw_signal(self, candidate_id: str, signal: RawSignal) -> dict[str, str]:
        signal_id = signal.id or _new_id("sig")
        now = _utc_now()
        assert signal.source_url_hash is not None
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(processed_source_table.c.source_url_hash).where(
                    processed_source_table.c.source_url_hash == signal.source_url_hash
                )
            ).scalar_one_or_none()
            if existing is not None:
                return {"status": "duplicate", "signal_id": signal_id}

            connection.execute(
                insert(processed_source_table).values(
                    source_url_hash=signal.source_url_hash,
                    source_url=signal.source_url,
                    created_at=now,
                )
            )
            connection.execute(
                insert(raw_signal_table).values(
                    id=signal_id,
                    candidate_id=candidate_id,
                    source_type=signal.source_type,
                    source_url_hash=signal.source_url_hash,
                    payload=signal.model_copy(update={"id": signal_id}).model_dump(mode="json"),
                    created_at=now,
                )
            )
        return {"status": "created", "signal_id": signal_id}

    def count_raw_signals(self, candidate_id: str) -> int:
        with self.engine.begin() as connection:
            count = connection.execute(
                select(func.count())
                .select_from(raw_signal_table)
                .where(raw_signal_table.c.candidate_id == candidate_id)
            ).scalar_one()
        return int(count)

    def list_raw_signals(self, candidate_id: str) -> list[RawSignal]:
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(raw_signal_table.c.payload).where(
                        raw_signal_table.c.candidate_id == candidate_id
                    )
                )
                .scalars()
                .all()
            )
        return [RawSignal.model_validate(payload) for payload in rows]

    def get_raw_signals_by_ids(self, candidate_id: str, signal_ids: list[str]) -> list[RawSignal]:
        if not signal_ids:
            return []
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(raw_signal_table.c.payload).where(
                        raw_signal_table.c.candidate_id == candidate_id,
                        raw_signal_table.c.id.in_(signal_ids),
                    )
                )
                .scalars()
                .all()
            )
        payloads = [RawSignal.model_validate(payload) for payload in rows]
        order = {signal_id: index for index, signal_id in enumerate(signal_ids)}
        return sorted(payloads, key=lambda payload: order.get(payload.id or "", 0))

    def signal_summary(self, candidate_id: str) -> dict[str, Any]:
        signals = self.list_raw_signals(candidate_id)
        breakdown = Counter(signal.source_type for signal in signals)
        top_tags = Counter(tag for signal in signals for tag in signal.tags).most_common(5)
        return {
            "signal_count": len(signals),
            "source_breakdown": dict(breakdown),
            "top_pain_themes": [tag for tag, _count in top_tags],
        }

    def replace_problem_units(self, candidate_id: str, problem_units: list[ProblemUnit]) -> None:
        now = _utc_now()
        with self.engine.begin() as connection:
            existing_rows = (
                connection.execute(
                    select(problem_unit_table.c.id).where(
                        problem_unit_table.c.candidate_id == candidate_id
                    )
                )
                .scalars()
                .all()
            )
            for existing_id in existing_rows:
                connection.execute(
                    delete(problem_unit_evidence_table).where(
                        problem_unit_evidence_table.c.problem_unit_id == existing_id
                    )
                )
            connection.execute(
                delete(problem_unit_table).where(problem_unit_table.c.candidate_id == candidate_id)
            )
            for problem_unit in problem_units:
                connection.execute(
                    insert(problem_unit_table).values(
                        id=problem_unit.id,
                        candidate_id=candidate_id,
                        payload=problem_unit.model_dump(mode="json"),
                        updated_at=now,
                    )
                )
                for signal_id in problem_unit.evidence_ids:
                    connection.execute(
                        insert(problem_unit_evidence_table).values(
                            id=_new_id("pue"),
                            candidate_id=candidate_id,
                            problem_unit_id=problem_unit.id,
                            raw_signal_id=signal_id,
                        )
                    )

    def get_problem_unit(self, candidate_id: str, problem_unit_id: str) -> ProblemUnit | None:
        with self.engine.begin() as connection:
            payload = connection.execute(
                select(problem_unit_table.c.payload).where(
                    problem_unit_table.c.candidate_id == candidate_id,
                    problem_unit_table.c.id == problem_unit_id,
                )
            ).scalar_one_or_none()
        if payload is None:
            return None
        return ProblemUnit.model_validate(payload)

    def list_problem_units(self, candidate_id: str) -> list[ProblemUnit]:
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(problem_unit_table.c.payload).where(
                        problem_unit_table.c.candidate_id == candidate_id
                    )
                )
                .scalars()
                .all()
            )
        return [ProblemUnit.model_validate(payload) for payload in rows]

    def replace_landscape_entries(self, candidate_id: str, entries: list[LandscapeEntry]) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                delete(landscape_entry_table).where(
                    landscape_entry_table.c.candidate_id == candidate_id
                )
            )
            for entry in entries:
                self._insert_landscape_entry(connection, candidate_id, entry)

    def add_landscape_entry(self, candidate_id: str, entry: LandscapeEntry) -> dict[str, str]:
        entry_id = entry.id or _new_id("land")
        with self.engine.begin() as connection:
            self._insert_landscape_entry(
                connection,
                candidate_id,
                entry.model_copy(update={"id": entry_id}),
            )
        return {"status": "created", "entry_id": entry_id}

    def landscape_summary(self, candidate_id: str) -> list[dict[str, str]]:
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(landscape_entry_table.c.payload).where(
                        landscape_entry_table.c.candidate_id == candidate_id
                    )
                )
                .scalars()
                .all()
            )
        entries = [LandscapeEntry.model_validate(payload) for payload in rows]
        return [
            {
                "id": entry.id or "",
                "name": entry.name,
                "status": entry.status,
                "type": entry.type,
                "relevance": entry.relevance,
            }
            for entry in entries
        ]

    def list_landscape_entries(self, candidate_id: str) -> list[LandscapeEntry]:
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(landscape_entry_table.c.payload).where(
                        landscape_entry_table.c.candidate_id == candidate_id
                    )
                )
                .scalars()
                .all()
            )
        return [LandscapeEntry.model_validate(payload) for payload in rows]

    def replace_wedges(
        self,
        candidate_id: str,
        wedges: list[dict[str, Any]],
        selected_wedge_id: str | None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                delete(wedge_hypothesis_table).where(
                    wedge_hypothesis_table.c.candidate_id == candidate_id
                )
            )
            for wedge in wedges:
                wedge_id = str(wedge["id"])
                connection.execute(
                    insert(wedge_hypothesis_table).values(
                        id=wedge_id,
                        candidate_id=candidate_id,
                        is_selected=wedge_id == selected_wedge_id,
                        payload=wedge,
                        updated_at=_utc_now(),
                    )
                )

    def list_wedges(self, candidate_id: str) -> list[dict[str, Any]]:
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(wedge_hypothesis_table.c.payload)
                    .where(wedge_hypothesis_table.c.candidate_id == candidate_id)
                    .order_by(wedge_hypothesis_table.c.updated_at, wedge_hypothesis_table.c.id)
                )
                .scalars()
                .all()
            )
        return [dict(row) for row in rows]

    def get_selected_wedge(self, candidate_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as connection:
            payload = connection.execute(
                select(wedge_hypothesis_table.c.payload).where(
                    wedge_hypothesis_table.c.candidate_id == candidate_id,
                    wedge_hypothesis_table.c.is_selected.is_(True),
                )
            ).scalar_one_or_none()
        if payload is None:
            return None
        return dict(payload)

    def replace_channel_plans(
        self, candidate_id: str, attempt_index: int, channel_payloads: list[dict[str, Any]]
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                delete(channel_plan_table).where(
                    channel_plan_table.c.candidate_id == candidate_id,
                    channel_plan_table.c.attempt_index == attempt_index,
                )
            )
            for payload in channel_payloads:
                connection.execute(
                    insert(channel_plan_table).values(
                        id=_new_id("chan"),
                        candidate_id=candidate_id,
                        attempt_index=attempt_index,
                        payload=payload,
                        created_at=_utc_now(),
                    )
                )

    def append_decision_event(self, event: DecisionEvent) -> DecisionEvent:
        with self.engine.begin() as connection:
            connection.execute(
                insert(decision_event_table).values(
                    id=_new_id("decision"),
                    candidate_id=event.candidate_id,
                    stage=event.stage.value,
                    action=event.action.value,
                    reason=event.reason,
                    iteration=event.iteration,
                    metadata=event.metadata,
                    created_at=event.timestamp,
                )
            )
        return event

    def list_decision_events(self, candidate_id: str) -> list[DecisionEvent]:
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(decision_event_table)
                    .where(decision_event_table.c.candidate_id == candidate_id)
                    .order_by(decision_event_table.c.created_at, decision_event_table.c.id)
                )
                .mappings()
                .all()
            )
        return [
            DecisionEvent(
                candidate_id=row["candidate_id"],
                stage=Stage(row["stage"]),
                action=GateAction(row["action"]),
                reason=row["reason"],
                iteration=row["iteration"],
                metadata=row["metadata"],
                timestamp=row["created_at"],
            )
            for row in rows
        ]

    def get_decision_event(
        self,
        candidate_id: str,
        stage: Stage,
        iteration: int,
    ) -> DecisionEvent | None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(decision_event_table)
                    .where(
                        decision_event_table.c.candidate_id == candidate_id,
                        decision_event_table.c.stage == stage.value,
                        decision_event_table.c.iteration == iteration,
                    )
                    .order_by(
                        decision_event_table.c.created_at.desc(),
                        decision_event_table.c.id.desc(),
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return DecisionEvent(
            candidate_id=row["candidate_id"],
            stage=Stage(row["stage"]),
            action=GateAction(row["action"]),
            reason=row["reason"],
            iteration=row["iteration"],
            metadata=row["metadata"],
            timestamp=row["created_at"],
        )

    def store_stage_run(
        self,
        *,
        candidate_id: str,
        stage: Stage,
        agent: AgentName,
        attempt_index: int,
        prompt_version: str,
        prompt_hash: str,
        model_alias: str,
        payload: dict[str, Any],
        metrics: dict[str, Any],
    ) -> None:
        created_at = _utc_now()
        with self.engine.begin() as connection:
            connection.execute(
                insert(candidate_stage_run_table).values(
                    id=_new_id("stage"),
                    candidate_id=candidate_id,
                    stage=stage.value,
                    agent=agent.value,
                    attempt_index=attempt_index,
                    prompt_version=prompt_version,
                    prompt_hash=prompt_hash,
                    model_alias=model_alias,
                    payload=payload,
                    input_tokens=int(metrics.get("input_tokens", 0)),
                    output_tokens=int(metrics.get("output_tokens", 0)),
                    tool_calls=int(metrics.get("tool_calls", 0)),
                    cost_eur=float(metrics.get("cost_eur", 0.0)),
                    created_at=created_at,
                )
            )

    def get_stage_run(
        self,
        candidate_id: str,
        agent: AgentName,
        attempt_index: int,
    ) -> CandidateStageRunRecord | None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(candidate_stage_run_table)
                    .where(
                        candidate_stage_run_table.c.candidate_id == candidate_id,
                        candidate_stage_run_table.c.agent == agent.value,
                        candidate_stage_run_table.c.attempt_index == attempt_index,
                    )
                    .order_by(
                        candidate_stage_run_table.c.created_at.desc(),
                        candidate_stage_run_table.c.id.desc(),
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _stage_run_from_row(row)

    def latest_stage_run(
        self,
        candidate_id: str,
        agent: AgentName,
    ) -> CandidateStageRunRecord | None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(candidate_stage_run_table)
                    .where(
                        candidate_stage_run_table.c.candidate_id == candidate_id,
                        candidate_stage_run_table.c.agent == agent.value,
                    )
                    .order_by(
                        candidate_stage_run_table.c.attempt_index.desc(),
                        candidate_stage_run_table.c.created_at.desc(),
                        candidate_stage_run_table.c.id.desc(),
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _stage_run_from_row(row)

    def count_stage_runs(self, candidate_id: str, agent: AgentName | None = None) -> int:
        statement = (
            select(func.count())
            .select_from(candidate_stage_run_table)
            .where(candidate_stage_run_table.c.candidate_id == candidate_id)
        )
        if agent is not None:
            statement = statement.where(candidate_stage_run_table.c.agent == agent.value)
        with self.engine.begin() as connection:
            count = connection.execute(statement).scalar_one()
        return int(count)

    def store_agent_checkpoint(self, checkpoint: AgentCheckpointRecord) -> None:
        checkpoint_id = _agent_checkpoint_id(
            checkpoint.candidate_id,
            checkpoint.stage,
            checkpoint.agent,
            checkpoint.attempt_index,
        )
        values = {
            "candidate_id": checkpoint.candidate_id,
            "stage": checkpoint.stage.value,
            "agent": checkpoint.agent.value,
            "attempt_index": checkpoint.attempt_index,
            "status": checkpoint.status.value,
            "prompt_version": checkpoint.prompt_version,
            "prompt_hash": checkpoint.prompt_hash,
            "model_alias": checkpoint.model_alias,
            "response_model": checkpoint.response_model,
            "state_payload": checkpoint.state.model_dump(mode="json"),
            "updated_at": checkpoint.updated_at,
        }
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(agent_checkpoint_table.c.id).where(
                    agent_checkpoint_table.c.id == checkpoint_id
                )
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(
                    insert(agent_checkpoint_table).values(
                        id=checkpoint_id,
                        created_at=checkpoint.created_at,
                        **values,
                    )
                )
                return
            connection.execute(
                update(agent_checkpoint_table)
                .where(agent_checkpoint_table.c.id == checkpoint_id)
                .values(**values)
            )

    def load_agent_checkpoint(
        self,
        candidate_id: str,
        stage: Stage,
        agent: AgentName,
        attempt_index: int,
    ) -> AgentCheckpointRecord | None:
        checkpoint_id = _agent_checkpoint_id(candidate_id, stage, agent, attempt_index)
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(agent_checkpoint_table).where(
                        agent_checkpoint_table.c.id == checkpoint_id
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return AgentCheckpointRecord(
            candidate_id=row["candidate_id"],
            stage=Stage(row["stage"]),
            agent=AgentName(row["agent"]),
            attempt_index=row["attempt_index"],
            status=AgentCheckpointStatus(row["status"]),
            prompt_version=row["prompt_version"],
            prompt_hash=row["prompt_hash"],
            model_alias=row["model_alias"],
            response_model=row["response_model"],
            state=row["state_payload"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def record_cost(self, record: CostRecord) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(cost_log_table).values(
                    id=_new_id("cost"),
                    candidate_id=record.candidate_id,
                    stage=record.stage.value,
                    agent=record.agent.value,
                    model=record.model,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    tool_calls=record.tool_calls,
                    cost_eur=record.cost_eur,
                    created_at=record.timestamp,
                )
            )
        self.increment_candidate_cost(record.candidate_id, record.cost_eur)

    def store_dossier(self, candidate_id: str, dossier: CandidateDossier) -> None:
        self.update_candidate(candidate_id, dossier_payload=dossier.model_dump(mode="json"))

    def load_dossier(self, candidate_id: str) -> CandidateDossier | None:
        candidate = self.get_candidate(candidate_id)
        if candidate is None or candidate.dossier_payload is None:
            return None
        return CandidateDossier.model_validate(candidate.dossier_payload)

    def mark_candidate_killed(self, candidate_id: str) -> None:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError(f"Unknown candidate: {candidate_id}")
        self.update_candidate(candidate_id, status="killed")
        if candidate.selected_arena_id is None:
            return
        with self.engine.begin() as connection:
            connection.execute(
                update(raw_arena_table)
                .where(
                    raw_arena_table.c.candidate_id == candidate_id,
                    raw_arena_table.c.id == candidate.selected_arena_id,
                )
                .values(status="killed", updated_at=_utc_now())
            )

    def clear_unexplored_arenas(self, *, dry_run: bool = False) -> int:
        with self.engine.begin() as connection:
            arena_ids = (
                connection.execute(
                    select(raw_arena_table.c.id).where(raw_arena_table.c.status == "proposed")
                )
                .scalars()
                .all()
            )
            if dry_run:
                return len(arena_ids)
            if arena_ids:
                connection.execute(
                    delete(raw_arena_table).where(raw_arena_table.c.id.in_(list(arena_ids)))
                )
            return len(arena_ids)

    def reset_runtime_state(self) -> dict[str, int]:
        tables = (
            agent_checkpoint_table,
            candidate_stage_run_table,
            channel_plan_table,
            cost_log_table,
            decision_event_table,
            landscape_entry_table,
            learning_entry_table,
            problem_unit_evidence_table,
            problem_unit_table,
            processed_source_table,
            raw_arena_table,
            raw_signal_table,
            wedge_hypothesis_table,
            candidate_table,
        )
        counts: dict[str, int] = {}
        with self.engine.begin() as connection:
            for table in tables:
                row_count = connection.execute(select(func.count()).select_from(table)).scalar_one()
                counts[table.name] = int(row_count)
                if row_count:
                    connection.execute(delete(table))
        return counts

    def database_stats(self) -> dict[str, Any]:
        with self.engine.begin() as connection:
            candidate_count = connection.execute(
                select(func.count()).select_from(candidate_table)
            ).scalar_one()
            raw_arena_count = connection.execute(
                select(func.count()).select_from(raw_arena_table)
            ).scalar_one()
            raw_signal_count = connection.execute(
                select(func.count()).select_from(raw_signal_table)
            ).scalar_one()
            candidate_status_rows = (
                connection.execute(
                    select(candidate_table.c.status, func.count())
                    .group_by(candidate_table.c.status)
                    .order_by(candidate_table.c.status)
                )
                .all()
            )
            arena_status_rows = (
                connection.execute(
                    select(raw_arena_table.c.status, func.count())
                    .group_by(raw_arena_table.c.status)
                    .order_by(raw_arena_table.c.status)
                )
                .all()
            )
        return {
            "candidates": int(candidate_count),
            "raw_arenas": int(raw_arena_count),
            "raw_signals": int(raw_signal_count),
            "candidate_statuses": {
                str(status): int(count) for status, count in candidate_status_rows
            },
            "arena_statuses": {str(status): int(count) for status, count in arena_status_rows},
        }

    @staticmethod
    def _insert_landscape_entry(
        connection: Connection, candidate_id: str, entry: LandscapeEntry
    ) -> None:
        connection.execute(
            insert(landscape_entry_table).values(
                id=entry.id or _new_id("land"),
                candidate_id=candidate_id,
                payload=entry.model_dump(mode="json"),
                created_at=_utc_now(),
            )
        )

    def store_learnings(
        self,
        candidate_id: str,
        entries: list[dict[str, Any]],
    ) -> None:
        """Persist learning entries for a candidate."""
        with self.engine.begin() as conn:
            for entry in entries:
                conn.execute(
                    insert(learning_entry_table).values(
                        id=_new_id("learn"),
                        candidate_id=candidate_id,
                        payload=entry,
                        created_at=_utc_now(),
                    )
                )

    def list_recent_learnings(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most recent learnings across all candidates."""
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(learning_entry_table)
                    .order_by(learning_entry_table.c.created_at.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            return [dict(row["payload"]) for row in rows]


def _candidate_from_row(row: RowMapping) -> CandidateRecord:
    current_stage = Stage(row["current_stage"]) if row["current_stage"] is not None else None
    return CandidateRecord(
        candidate_id=row["candidate_id"],
        status=row["status"],
        current_stage=current_stage,
        caution_flag=bool(row["caution_flag"]),
        selected_arena_id=row["selected_arena_id"],
        selected_problem_unit_id=row["selected_problem_unit_id"],
        selected_wedge_id=row["selected_wedge_id"],
        total_cost_eur=float(row["total_cost_eur"]),
        dossier_payload=row["dossier_payload"],
        request_payload=row.get("request_payload"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _stage_run_from_row(row: RowMapping) -> CandidateStageRunRecord:
    return CandidateStageRunRecord(
        candidate_id=row["candidate_id"],
        stage=Stage(row["stage"]),
        agent=AgentName(row["agent"]),
        attempt_index=row["attempt_index"],
        prompt_version=row["prompt_version"],
        prompt_hash=row["prompt_hash"],
        model_alias=row["model_alias"],
        payload=dict(row["payload"]),
        metrics=ActivityMetrics(
            cost_eur=float(row["cost_eur"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            tool_calls=int(row["tool_calls"]),
        ),
        created_at=row["created_at"],
    )


def _agent_checkpoint_id(
    candidate_id: str,
    stage: Stage,
    agent: AgentName,
    attempt_index: int,
) -> str:
    return f"agent:{candidate_id}:{stage.value}:{agent.value}:{attempt_index}"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class QueuedArenaSeed:
    arena: RawArena
    evaluated_arena: EvaluatedArena
    request_payload: dict[str, Any] | None


def _pick_seeded_arena(
    connection: Connection,
    candidate_id: str,
    candidate_rows: list[RowMapping],
) -> tuple[RowMapping, EvaluatedArena]:
    by_id = {str(row["id"]): row for row in candidate_rows}
    by_fingerprint = {
        RawArena.model_validate(row["payload"]).fingerprint(): row for row in candidate_rows
    }
    evaluation_payload = connection.execute(
        select(candidate_stage_run_table.c.payload).where(
            candidate_stage_run_table.c.candidate_id == candidate_id,
            candidate_stage_run_table.c.agent == AgentName.ARENA_EVALUATOR.value,
            candidate_stage_run_table.c.attempt_index == 0,
        )
    ).scalar_one_or_none()
    if evaluation_payload is not None:
        evaluation = ArenaEvaluation.model_validate(evaluation_payload)
        for ranked_arena in evaluation.ranked_arenas:
            ranked_id = ranked_arena.arena.id
            matched_row = by_id.get(ranked_id) if ranked_id is not None else None
            if matched_row is None:
                matched_row = by_fingerprint.get(ranked_arena.arena.fingerprint())
            if matched_row is None:
                continue
            hydrated_arena = RawArena.model_validate(matched_row["payload"])
            return matched_row, ranked_arena.model_copy(update={"arena": hydrated_arena})

    fallback_row = candidate_rows[0]
    fallback_arena = RawArena.model_validate(fallback_row["payload"])
    return fallback_row, EvaluatedArena(
        arena=fallback_arena,
        score=60,
        dimension_scores={},
        dimension_rationale={},
        viability_verdict="queued",
        risks=["Seeded from an unexplored arena backlog without a stored evaluator ranking."],
        recommended_first_sources=fallback_arena.channel_surface,
    )
