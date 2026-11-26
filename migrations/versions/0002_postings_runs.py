"""Job postings, agent runs and per-requirement matches.

Revision ID: 0002_postings_runs
Revises: 0001_initial
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_postings_runs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade():
    op.add_column("search_profiles", sa.Column("experience_years", sa.Integer, nullable=False, server_default="0"))
    op.add_column("search_profiles", sa.Column("education", sa.JSON, nullable=True))

    op.create_table(
        "job_postings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("title", sa.String(300), nullable=False, server_default=""),
        sa.Column("company_name", sa.String(300), nullable=False, server_default=""),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("city", sa.String(100), nullable=False, server_default=""),
        sa.Column("url", sa.String(500), nullable=False, server_default=""),
        sa.Column("channel", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("jd_text", sa.Text, nullable=False),
        sa.Column("jd_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_job_postings_company_id", "job_postings", ["company_id"])
    op.create_index("ix_job_postings_status", "job_postings", ["status"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("posting_id", sa.Integer, sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("graph_version", sa.String(16), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("screening", sa.JSON, nullable=False),
        sa.Column("summary", sa.JSON, nullable=False),
        sa.Column("versions", sa.JSON, nullable=False),
        sa.Column("trace", sa.JSON, nullable=False),
        sa.Column("report_path", sa.String(500), nullable=False, server_default=""),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("started_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS, nullable=True),
    )
    op.create_index("ix_agent_runs_posting_id", "agent_runs", ["posting_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])

    op.create_table(
        "requirement_matches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requirement_id", sa.String(16), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("importance", sa.String(16), nullable=False),
        sa.Column("source_quote", sa.Text, nullable=False, server_default=""),
        sa.Column("verdict", sa.String(16), nullable=True),
        sa.Column("processing_status", sa.String(16), nullable=False, server_default=""),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("missing_aspects", sa.JSON, nullable=False),
        sa.Column("questions_for_user", sa.JSON, nullable=False),
        sa.Column("errors", sa.JSON, nullable=False),
        sa.UniqueConstraint("run_id", "requirement_id", name="uq_match_run_requirement"),
    )
    op.create_index("ix_requirement_matches_run_id", "requirement_matches", ["run_id"])
    op.create_index("ix_requirement_matches_category", "requirement_matches", ["category"])
    op.create_index("ix_requirement_matches_verdict", "requirement_matches", ["verdict"])


def downgrade():
    op.drop_table("requirement_matches")
    op.drop_table("agent_runs")
    op.drop_table("job_postings")
    op.drop_column("search_profiles", "education")
    op.drop_column("search_profiles", "experience_years")
