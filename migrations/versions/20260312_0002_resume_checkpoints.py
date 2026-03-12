from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260312_0002"
down_revision = "20260310_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("candidate", sa.Column("request_payload", sa.JSON(), nullable=True))

    op.create_table(
        "workflow_checkpoint",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("attempt_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_workflow_checkpoint_candidate_id",
        "workflow_checkpoint",
        ["candidate_id"],
        unique=False,
    )

    op.create_table(
        "agent_checkpoint",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("agent", sa.String(length=64), nullable=False),
        sa.Column("attempt_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("model_alias", sa.String(length=128), nullable=False),
        sa.Column("response_model", sa.String(length=128), nullable=False),
        sa.Column("state_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_checkpoint_candidate_id",
        "agent_checkpoint",
        ["candidate_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_checkpoint_candidate_id", table_name="agent_checkpoint")
    op.drop_table("agent_checkpoint")
    op.drop_index("ix_workflow_checkpoint_candidate_id", table_name="workflow_checkpoint")
    op.drop_table("workflow_checkpoint")
    op.drop_column("candidate", "request_payload")
