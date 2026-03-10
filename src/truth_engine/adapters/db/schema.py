from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

candidate_table = Table(
    "candidate",
    metadata,
    Column("candidate_id", String(255), primary_key=True),
    Column("status", String(64), nullable=False),
    Column("current_stage", String(64), nullable=True),
    Column("caution_flag", Boolean, nullable=False, default=False),
    Column("selected_arena_id", String(255), nullable=True),
    Column("selected_problem_unit_id", String(255), nullable=True),
    Column("selected_wedge_id", String(255), nullable=True),
    Column("total_cost_eur", Float, nullable=False, default=0.0),
    Column("dossier_payload", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

candidate_stage_run_table = Table(
    "candidate_stage_run",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("candidate_id", String(255), nullable=False, index=True),
    Column("stage", String(64), nullable=False),
    Column("agent", String(64), nullable=False),
    Column("attempt_index", Integer, nullable=False, default=0),
    Column("prompt_version", String(128), nullable=False),
    Column("prompt_hash", String(64), nullable=False),
    Column("model_alias", String(128), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("tool_calls", Integer, nullable=False, default=0),
    Column("cost_eur", Float, nullable=False, default=0.0),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

raw_arena_table = Table(
    "raw_arena",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("candidate_id", String(255), nullable=False, index=True),
    Column("fingerprint", String(255), nullable=False, index=True),
    Column("status", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

processed_source_table = Table(
    "processed_source",
    metadata,
    Column("source_url_hash", String(64), primary_key=True),
    Column("source_url", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

raw_signal_table = Table(
    "raw_signal",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("candidate_id", String(255), nullable=False, index=True),
    Column("source_type", String(64), nullable=False),
    Column("source_url_hash", String(64), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

problem_unit_table = Table(
    "problem_unit",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("candidate_id", String(255), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

problem_unit_evidence_table = Table(
    "problem_unit_evidence",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("candidate_id", String(255), nullable=False, index=True),
    Column("problem_unit_id", String(255), nullable=False, index=True),
    Column("raw_signal_id", String(255), nullable=False, index=True),
)

landscape_entry_table = Table(
    "landscape_entry",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("candidate_id", String(255), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

wedge_hypothesis_table = Table(
    "wedge_hypothesis",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("candidate_id", String(255), nullable=False, index=True),
    Column("is_selected", Boolean, nullable=False, default=False),
    Column("payload", JSON, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

channel_plan_table = Table(
    "channel_plan",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("candidate_id", String(255), nullable=False, index=True),
    Column("attempt_index", Integer, nullable=False, default=0),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

decision_event_table = Table(
    "decision_event",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("candidate_id", String(255), nullable=False, index=True),
    Column("stage", String(64), nullable=False),
    Column("action", String(64), nullable=False),
    Column("reason", Text, nullable=False),
    Column("iteration", Integer, nullable=False, default=0),
    Column("metadata", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

cost_log_table = Table(
    "cost_log",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("candidate_id", String(255), nullable=False, index=True),
    Column("stage", String(64), nullable=False),
    Column("agent", String(64), nullable=False),
    Column("model", String(128), nullable=False),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("tool_calls", Integer, nullable=False, default=0),
    Column("cost_eur", Float, nullable=False, default=0.0),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

learning_entry_table = Table(
    "learning_entry",
    metadata,
    Column("id", String(255), primary_key=True),
    Column("candidate_id", String(255), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
