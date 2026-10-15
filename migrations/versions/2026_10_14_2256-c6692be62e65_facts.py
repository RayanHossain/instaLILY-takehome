"""Add facts: what the AI extracted about each contractor, each with the exact quote it rests on.

Revision ID: c6692be62e65
Revises: 2becdc8c0dae
Create Date: 2026-10-14 22:56:06.520835

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6692be62e65"
down_revision: str | Sequence[str] | None = "2becdc8c0dae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create facts, indexed on contractor_id: a contractor's facts are replaced together."""
    op.create_table(
        "facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contractor_id", sa.String(), sa.ForeignKey("contractors.gaf_id"), nullable=False),
        sa.Column("field", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_facts_contractor_id", "facts", ["contractor_id"])


def downgrade() -> None:
    """Drop facts and its index."""
    op.drop_index("ix_facts_contractor_id", table_name="facts")
    op.drop_table("facts")
