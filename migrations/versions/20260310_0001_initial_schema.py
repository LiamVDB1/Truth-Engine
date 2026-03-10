from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260310_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate",
        sa.Column("candidate_id", sa.String(length=255), primary_key=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column("caution_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("selected_arena_id", sa.String(length=255), nullable=True),
        sa.Column("selected_problem_unit_id", sa.String(length=255), nullable=True),
        sa.Column("selected_wedge_id", sa.String(length=255), nullable=True),
        sa.Column("total_cost_eur", sa.Float(), nullable=False, server_default="0"),
        sa.Column("dossier_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "candidate_stage_run",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("agent", sa.String(length=64), nullable=False),
        sa.Column("attempt_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("model_alias", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_eur", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_candidate_stage_run_candidate_id",
        "candidate_stage_run",
        ["candidate_id"],
        unique=False,
    )
    op.create_table(
        "raw_arena",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("fingerprint", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_raw_arena_candidate_id", "raw_arena", ["candidate_id"], unique=False)
    op.create_index("ix_raw_arena_fingerprint", "raw_arena", ["fingerprint"], unique=False)
    op.create_table(
        "processed_source",
        sa.Column("source_url_hash", sa.String(length=64), primary_key=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "raw_signal",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_url_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_raw_signal_candidate_id", "raw_signal", ["candidate_id"], unique=False)
    op.create_index(
        "ix_raw_signal_source_url_hash",
        "raw_signal",
        ["source_url_hash"],
        unique=False,
    )
    op.create_table(
        "problem_unit",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_problem_unit_candidate_id", "problem_unit", ["candidate_id"], unique=False)
    op.create_table(
        "problem_unit_evidence",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("problem_unit_id", sa.String(length=255), nullable=False),
        sa.Column("raw_signal_id", sa.String(length=255), nullable=False),
    )
    op.create_index(
        "ix_problem_unit_evidence_candidate_id",
        "problem_unit_evidence",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        "ix_problem_unit_evidence_problem_unit_id",
        "problem_unit_evidence",
        ["problem_unit_id"],
        unique=False,
    )
    op.create_index(
        "ix_problem_unit_evidence_raw_signal_id",
        "problem_unit_evidence",
        ["raw_signal_id"],
        unique=False,
    )
    op.create_table(
        "landscape_entry",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_landscape_entry_candidate_id", "landscape_entry", ["candidate_id"], unique=False
    )
    op.create_table(
        "wedge_hypothesis",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_wedge_hypothesis_candidate_id", "wedge_hypothesis", ["candidate_id"], unique=False
    )
    op.create_table(
        "channel_plan",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("attempt_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_channel_plan_candidate_id", "channel_plan", ["candidate_id"], unique=False)
    op.create_table(
        "decision_event",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_decision_event_candidate_id", "decision_event", ["candidate_id"], unique=False
    )
    op.create_table(
        "cost_log",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("agent", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_eur", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cost_log_candidate_id", "cost_log", ["candidate_id"], unique=False)
    op.create_table(
        "learning_entry",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_learning_entry_candidate_id", "learning_entry", ["candidate_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_learning_entry_candidate_id", table_name="learning_entry")
    op.drop_table("learning_entry")
    op.drop_index("ix_cost_log_candidate_id", table_name="cost_log")
    op.drop_table("cost_log")
    op.drop_index("ix_decision_event_candidate_id", table_name="decision_event")
    op.drop_table("decision_event")
    op.drop_index("ix_channel_plan_candidate_id", table_name="channel_plan")
    op.drop_table("channel_plan")
    op.drop_index("ix_wedge_hypothesis_candidate_id", table_name="wedge_hypothesis")
    op.drop_table("wedge_hypothesis")
    op.drop_index("ix_landscape_entry_candidate_id", table_name="landscape_entry")
    op.drop_table("landscape_entry")
    op.drop_index("ix_problem_unit_evidence_raw_signal_id", table_name="problem_unit_evidence")
    op.drop_index(
        "ix_problem_unit_evidence_problem_unit_id",
        table_name="problem_unit_evidence",
    )
    op.drop_index("ix_problem_unit_evidence_candidate_id", table_name="problem_unit_evidence")
    op.drop_table("problem_unit_evidence")
    op.drop_index("ix_problem_unit_candidate_id", table_name="problem_unit")
    op.drop_table("problem_unit")
    op.drop_index("ix_raw_signal_source_url_hash", table_name="raw_signal")
    op.drop_index("ix_raw_signal_candidate_id", table_name="raw_signal")
    op.drop_table("raw_signal")
    op.drop_table("processed_source")
    op.drop_index("ix_raw_arena_fingerprint", table_name="raw_arena")
    op.drop_index("ix_raw_arena_candidate_id", table_name="raw_arena")
    op.drop_table("raw_arena")
    op.drop_index("ix_candidate_stage_run_candidate_id", table_name="candidate_stage_run")
    op.drop_table("candidate_stage_run")
    op.drop_table("candidate")
