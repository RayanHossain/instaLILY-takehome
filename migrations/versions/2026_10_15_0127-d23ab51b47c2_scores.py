"""Add scores: each contractor's four component scores, flags, and reasons from the score stage.

Revision ID: d23ab51b47c2
Revises: 8fd5b146ee79
Create Date: 2026-10-15 01:27:32.637058

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d23ab51b47c2"
down_revision: str | Sequence[str] | None = "8fd5b146ee79"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create scores, one row per contractor. A preset's total is never stored."""
    op.create_table(
        "scores",
        sa.Column("contractor_id", sa.String(), sa.ForeignKey("contractors.gaf_id"), primary_key=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("winnability", sa.Float(), nullable=False),
        sa.Column("stability", sa.Float(), nullable=False),
        sa.Column("distance", sa.Float(), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("rules_version", sa.String(), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop scores."""
    op.drop_table("scores")
