from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260312_0003"
down_revision = "20260312_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_workflow_checkpoint_candidate_id", table_name="workflow_checkpoint")
    op.drop_table("workflow_checkpoint")


def downgrade() -> None:
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
