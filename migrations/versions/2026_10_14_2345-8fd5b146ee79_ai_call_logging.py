"""Add AI call logging: stage_runs (each AI stage run and its totals) and ai_calls (each attempt).

Revision ID: 8fd5b146ee79
Revises: c6692be62e65
Create Date: 2026-10-14 23:45:00.607044

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8fd5b146ee79"
down_revision: str | Sequence[str] | None = "c6692be62e65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create stage_runs, then ai_calls, indexed on run_id for counting a run's attempts."""
    op.create_table(
        "stage_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("totals", sa.JSON(), nullable=True),
    )
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("stage_runs.id"), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("contractor_id", sa.String(), sa.ForeignKey("contractors.gaf_id"), nullable=True),
        sa.Column("prompt_name", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("latency_seconds", sa.Float(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_calls_run_id", "ai_calls", ["run_id"])


def downgrade() -> None:
    """Drop ai_calls, then stage_runs."""
    op.drop_index("ix_ai_calls_run_id", table_name="ai_calls")
    op.drop_table("ai_calls")
    op.drop_table("stage_runs")
