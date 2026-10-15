"""Add briefs: the AI's touch plan for each top lead, with the hash of the input it was written from.

Revision ID: ecfc48d4d3af
Revises: d23ab51b47c2
Create Date: 2026-10-15 01:34:07.706326

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ecfc48d4d3af"
down_revision: str | Sequence[str] | None = "d23ab51b47c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create briefs, one row per contractor: its latest brief."""
    op.create_table(
        "briefs",
        sa.Column("contractor_id", sa.String(), sa.ForeignKey("contractors.gaf_id"), primary_key=True),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop briefs."""
    op.drop_table("briefs")
