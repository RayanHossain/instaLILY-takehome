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
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("territory_zip", sa.String(), nullable=False),
        sa.Column("radius_miles", sa.Float(), nullable=False),
        sa.Column("contractors_seen", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )

    # One row per GAF contractor, keyed on GAF's own ID (text, to keep leading zeros).
    op.create_table(
        "contractors",
        sa.Column("gaf_id", sa.String(), nullable=False),
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
        sa.Column("first_seen_run", sa.Integer(), nullable=False),
        sa.Column("last_seen_run", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["first_seen_run"], ["runs.id"], name=op.f("fk_contractors_first_seen_run_runs")),
        sa.ForeignKeyConstraint(["last_seen_run"], ["runs.id"], name=op.f("fk_contractors_last_seen_run_runs")),
        sa.PrimaryKeyConstraint("gaf_id", name=op.f("pk_contractors")),
    )
    op.create_index(op.f("ix_contractors_last_seen_run"), "contractors", ["last_seen_run"])

    # Every HTTP response body, saved before it is parsed.
    op.create_table(
        "raw_responses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("contractor_id", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["contractor_id"], ["contractors.gaf_id"], name=op.f("fk_raw_responses_contractor_id_contractors")),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_raw_responses_run_id_runs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_responses")),
    )
    op.create_index(op.f("ix_raw_responses_run_id"), "raw_responses", ["run_id"])
    op.create_index(op.f("ix_raw_responses_contractor_id"), "raw_responses", ["contractor_id"])

    # Sales reps and their territories, starting with one demo rep for the 10013 branch.
    reps = op.create_table(
        "reps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("territory_zip", sa.String(), nullable=False),
        sa.Column("radius_miles", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reps")),
    )
    op.bulk_insert(reps, [{"name": "Demo Rep", "territory_zip": "10013", "radius_miles": 25}])


def downgrade() -> None:
    """Drop everything, children before parents."""
    op.drop_table("reps")
    op.drop_index(op.f("ix_raw_responses_contractor_id"), table_name="raw_responses")
    op.drop_index(op.f("ix_raw_responses_run_id"), table_name="raw_responses")
    op.drop_table("raw_responses")
    op.drop_index(op.f("ix_contractors_last_seen_run"), table_name="contractors")
    op.drop_table("contractors")
    op.drop_table("runs")
