"""Collected postings and collection runs.

Revision ID: 0003_collection
Revises: 0002_postings_runs
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_collection"
down_revision = "0002_postings_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("job_postings", sa.Column("external_id", sa.String(128), nullable=True))
    op.add_column("job_postings", sa.Column("posted_at", sa.String(40), nullable=False, server_default=""))
    op.add_column("job_postings", sa.Column("collection_run_id", sa.String(40), nullable=True))
    op.create_unique_constraint("uq_postings_source_external", "job_postings", ["source", "external_id"])

    op.create_table(
        "collection_runs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False),              # agent | rules
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("plan", sa.JSON, nullable=False),                     # searches made: source, keyword, hits
        sa.Column("stats", sa.JSON, nullable=False),
        sa.Column("trace", sa.JSON, nullable=False),                    # agent messages / tool calls, summarised
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table("collection_runs")
    op.drop_constraint("uq_postings_source_external", "job_postings", type_="unique")
    op.drop_column("job_postings", "collection_run_id")
    op.drop_column("job_postings", "posted_at")
    op.drop_column("job_postings", "external_id")
