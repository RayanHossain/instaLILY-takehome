"""Add raw_responses.request_body: the JSON we sent, so a saved search page records its offset.

Revision ID: aac17bf38635
Revises: 377713630aea
Create Date: 2026-10-14 19:34:24.662527

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aac17bf38635"
down_revision: str | Sequence[str] | None = "377713630aea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable request_body column. Rows saved before this have no value."""
    with op.batch_alter_table("raw_responses") as batch_op:
        batch_op.add_column(sa.Column("request_body", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop request_body."""
    with op.batch_alter_table("raw_responses") as batch_op:
        batch_op.drop_column("request_body")
