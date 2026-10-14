"""Allow contractors.enrolled_in_gaf_leads to be NULL, meaning GAF didn't say.

Revision ID: 377713630aea
Revises: 18cf9ccda867
Create Date: 2026-10-14 18:58:58.449976

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "377713630aea"
down_revision: str | Sequence[str] | None = "18cf9ccda867"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the NOT NULL rule on enrolled_in_gaf_leads."""
    with op.batch_alter_table("contractors") as batch_op:
        batch_op.alter_column("enrolled_in_gaf_leads", existing_type=sa.Boolean(), nullable=True)


def downgrade() -> None:
    """Turn unknowns back into False, then restore NOT NULL."""
    contractors = sa.table("contractors", sa.column("enrolled_in_gaf_leads", sa.Boolean()))
    op.execute(
        contractors.update()
        .where(contractors.c.enrolled_in_gaf_leads.is_(None))
        .values(enrolled_in_gaf_leads=False)
    )
    with op.batch_alter_table("contractors") as batch_op:
        batch_op.alter_column("enrolled_in_gaf_leads", existing_type=sa.Boolean(), nullable=False)
