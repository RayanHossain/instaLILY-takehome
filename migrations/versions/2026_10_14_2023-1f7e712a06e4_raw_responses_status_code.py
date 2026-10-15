"""Add raw_responses.status_code, so a failed page can be saved and told apart from a good one.

Revision ID: 1f7e712a06e4
Revises: aac17bf38635
Create Date: 2026-10-14 20:23:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f7e712a06e4"
down_revision: str | Sequence[str] | None = "aac17bf38635"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable status_code column. Rows saved before this have no value."""
    with op.batch_alter_table("raw_responses") as batch_op:
        batch_op.add_column(sa.Column("status_code", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop status_code."""
    with op.batch_alter_table("raw_responses") as batch_op:
        batch_op.drop_column("status_code")
