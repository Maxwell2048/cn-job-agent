"""Initial schema: companies, campus programmes, search profiles, pgvector knowledge chunks.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sector", sa.String(32), nullable=False),
        sa.Column("portal", sa.String(300), nullable=False, server_default=""),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_companies_sector", "companies", ["sector"])

    op.create_table(
        "campus_programs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False, server_default="main"),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("cohort", sa.String(16), nullable=False, server_default="2027"),
        sa.Column("window_start", sa.Date, nullable=True),
        sa.Column("window_end", sa.Date, nullable=True),
        sa.Column("window_text", sa.Text, nullable=False, server_default=""),
        sa.Column("basis", sa.String(24), nullable=False, server_default="testamur"),
        sa.Column("accepts_prior_unemployed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("status_text", sa.Text, nullable=False, server_default=""),
        sa.Column("deadline", sa.Date, nullable=True),
        sa.Column("deadline_text", sa.String(200), nullable=False, server_default=""),
        sa.Column("roles", sa.JSON, nullable=False),
        sa.Column("cities", sa.JSON, nullable=False),
        sa.Column("requirements", sa.JSON, nullable=False),
        sa.Column("apply_limit", sa.String(300), nullable=False, server_default=""),
        sa.Column("confidence", sa.String(16), nullable=False, server_default="unverified"),
        sa.Column("sources", sa.JSON, nullable=False),
        sa.Column("checked_on", sa.Date, nullable=True),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "key", name="uq_program_company_key"),
    )
    op.create_index("ix_campus_programs_company_id", "campus_programs", ["company_id"])

    op.create_table(
        "search_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("roles", sa.JSON, nullable=False),
        sa.Column("cities", sa.JSON, nullable=False),
        sa.Column("channels", sa.JSON, nullable=False),
        sa.Column("testamur_month", sa.Date, nullable=True),
        sa.Column("cscse_cert_date", sa.Date, nullable=True),
        sa.Column("birth_date", sa.Date, nullable=True),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "kb_chunks",
        sa.Column("chunk_id", sa.String(32), primary_key=True),
        sa.Column("corpus", sa.String(32), nullable=False),
        sa.Column("section_id", sa.String(32), nullable=False),
        sa.Column("project", sa.String(300), nullable=False, server_default=""),
        sa.Column("section", sa.String(300), nullable=False, server_default=""),
        sa.Column("source", sa.String(500), nullable=False, server_default=""),
        sa.Column("line_start", sa.Integer, nullable=False, server_default="0"),
        sa.Column("line_end", sa.Integer, nullable=False, server_default="0"),
        sa.Column("char_start", sa.Integer, nullable=False, server_default="0"),
        sa.Column("char_end", sa.Integer, nullable=False, server_default="0"),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("parent_text", sa.Text, nullable=False),
        sa.Column("search_keywords", sa.Text, nullable=False, server_default=""),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("indexed_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_kb_chunks_corpus", "kb_chunks", ["corpus"])
    op.create_index("ix_kb_chunks_section_id", "kb_chunks", ["section_id"])
    op.create_index("ix_kb_chunks_embedding_hnsw", "kb_chunks", ["embedding"], postgresql_using="hnsw",
                    postgresql_with={"m": 16, "ef_construction": 64},
                    postgresql_ops={"embedding": "vector_cosine_ops"})


def downgrade():
    op.drop_table("kb_chunks")
    op.drop_table("search_profiles")
    op.drop_table("campus_programs")
    op.drop_table("companies")
