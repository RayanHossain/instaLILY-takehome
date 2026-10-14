"""Initial tables: runs, contractors, raw_responses, reps (with one seeded rep).

Revision ID: 18cf9ccda867
Revises:
Create Date: 2026-10-14 18:25:20.245915

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "18cf9ccda867"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the tables and seed one rep."""
    # One row per pipeline execution.
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("territory_zip", sa.String(), nullable=False),
        sa.Column("radius_miles", sa.Float(), nullable=False),
        sa.Column("contractors_seen", sa.Integer(), nullable=False),
    )

    # One row per GAF contractor, keyed on GAF's own ID (text, to keep leading zeros).
    op.create_table(
        "contractors",
        sa.Column("gaf_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("postal_code", sa.String(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("profile_url", sa.String(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=True),
        sa.Column("certifications", sa.JSON(), nullable=False),
        sa.Column("designations", sa.JSON(), nullable=False),
        sa.Column("specialties", sa.JSON(), nullable=False),
        sa.Column("enrolled_in_gaf_leads", sa.Boolean(), nullable=False),
        sa.Column("first_seen_run", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("last_seen_run", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Every HTTP response body, saved before it is parsed.
    op.create_table(
        "raw_responses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("contractor_id", sa.String(), sa.ForeignKey("contractors.gaf_id"), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
    )

    # Sales reps and their territories, starting with one demo rep for the 10013 branch.
    reps = op.create_table(
        "reps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("territory_zip", sa.String(), nullable=False),
        sa.Column("radius_miles", sa.Float(), nullable=False),
    )
    op.bulk_insert(reps, [{"name": "Demo Rep", "territory_zip": "10013", "radius_miles": 25}])


def downgrade() -> None:
    """Drop everything, children before parents."""
    op.drop_table("reps")
    op.drop_table("raw_responses")
    op.drop_table("contractors")
    op.drop_table("runs")
