"""Add ai_cache.gave_up: an answer still invalid after the retry, remembered so its input isn't asked again.

Revision ID: 2ebc0323ee9f
Revises: ecfc48d4d3af
Create Date: 2026-10-15 06:19:39.594662

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2ebc0323ee9f"
down_revision: str | Sequence[str] | None = "ecfc48d4d3af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add gave_up, false for every answer saved before this: none was remembered."""
    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.add_column(sa.Column("gave_up", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Drop gave_up."""
    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.drop_column("gave_up")
