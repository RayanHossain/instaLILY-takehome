"""Add lead_notes, each rep's append-only notes and statuses on leads, and reps.preset, the rep's chosen preset.

Revision ID: 66780dc1253e
Revises: 2ebc0323ee9f
Create Date: 2026-10-15 11:30:16.748202

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "66780dc1253e"
down_revision: str | Sequence[str] | None = "2ebc0323ee9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create lead_notes, and add preset to reps (empty until the rep picks one)."""
    op.create_table(
        "lead_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rep_id", sa.Integer(), sa.ForeignKey("reps.id"), nullable=False, index=True),
        sa.Column("contractor_id", sa.String(), sa.ForeignKey("contractors.gaf_id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("reps") as batch_op:
        batch_op.add_column(sa.Column("preset", sa.String(), nullable=True))


def downgrade() -> None:
    """Drop reps.preset and lead_notes."""
    with op.batch_alter_table("reps") as batch_op:
        batch_op.drop_column("preset")
    op.drop_table("lead_notes")
