"""Add ai_cache: every AI answer, saved before it is parsed, and reused once it validates.

Revision ID: 2becdc8c0dae
Revises: 8e09de868a8d
Create Date: 2026-10-14 22:50:31.014776

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2becdc8c0dae"
down_revision: str | Sequence[str] | None = "8e09de868a8d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ai_cache, indexed on cache_key for lookups."""
    op.create_table(
        "ai_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_name", sa.String(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_cache_cache_key", "ai_cache", ["cache_key"])


def downgrade() -> None:
    """Drop ai_cache and its index."""
    op.drop_index("ix_ai_cache_cache_key", table_name="ai_cache")
    op.drop_table("ai_cache")
