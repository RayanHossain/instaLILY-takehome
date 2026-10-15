"""Add the contractor website check: HTTP status or error, and when it was checked.

Revision ID: 754e5b771ba4
Revises: 72104f5e78b2
Create Date: 2026-10-14 20:29:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "754e5b771ba4"
down_revision: str | Sequence[str] | None = "72104f5e78b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the website check columns, all nullable: most contractors haven't been checked."""
    with op.batch_alter_table("contractors") as batch_op:
        batch_op.add_column(sa.Column("website_status", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("website_error", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("website_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Drop the website check columns."""
    with op.batch_alter_table("contractors") as batch_op:
        batch_op.drop_column("website_checked_at")
        batch_op.drop_column("website_error")
        batch_op.drop_column("website_status")
