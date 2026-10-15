"""Add raw_responses.error, so a request that got no response is recorded too.

Revision ID: 8e09de868a8d
Revises: 754e5b771ba4
Create Date: 2026-10-14 20:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8e09de868a8d"
down_revision: str | Sequence[str] | None = "754e5b771ba4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable error column. Rows saved before this all got a response."""
    with op.batch_alter_table("raw_responses") as batch_op:
        batch_op.add_column(sa.Column("error", sa.String(), nullable=True))


def downgrade() -> None:
    """Drop error."""
    with op.batch_alter_table("raw_responses") as batch_op:
        batch_op.drop_column("error")
