"""Add the contractor fields parsed from GAF profile pages.

Revision ID: 72104f5e78b2
Revises: 1f7e712a06e4
Create Date: 2026-10-14 20:27:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "72104f5e78b2"
down_revision: str | Sequence[str] | None = "1f7e712a06e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the profile columns, all nullable: a profile may not show a value."""
    with op.batch_alter_table("contractors") as batch_op:
        batch_op.add_column(sa.Column("street_address", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("website_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("website_domain", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("google_place_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("google_rating", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("google_review_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("about_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("in_business_since", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop the profile columns."""
    with op.batch_alter_table("contractors") as batch_op:
        batch_op.drop_column("in_business_since")
        batch_op.drop_column("about_text")
        batch_op.drop_column("google_review_count")
        batch_op.drop_column("google_rating")
        batch_op.drop_column("google_place_id")
        batch_op.drop_column("website_domain")
        batch_op.drop_column("website_url")
        batch_op.drop_column("street_address")
