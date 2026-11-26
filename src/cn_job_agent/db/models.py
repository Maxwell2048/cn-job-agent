"""Tables.

companies         one employer (腾讯, 工商银行 ...)
campus_programs   one recruiting programme of a company for a cohort, with its
                  graduation window (腾讯 2027 校招, 小红书 REDstar ...)
search_profiles   what the job seeker is looking for: roles, cities, channels,
                  and the dates that decide cohort eligibility
kb_chunks         retrieval chunks of a knowledge corpus with their E5 vectors
                  (pgvector); corpus "experience" is the job_rag_starter library
"""
from datetime import date, datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 384  # intfloat/multilingual-e5-small


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    # internet | hardware | bank | soe | foreign
    sector: Mapped[str] = mapped_column(String(32), index=True)
    portal: Mapped[str] = mapped_column(String(300), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    programs: Mapped[list["CampusProgram"]] = relationship(back_populates="company", cascade="all, delete-orphan",
                                                           order_by="CampusProgram.id")


class CampusProgram(Base):
    __tablename__ = "campus_programs"
    __table_args__ = (UniqueConstraint("company_id", "key", name="uq_program_company_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), default="main")
    title: Mapped[str] = mapped_column(String(200), default="")
    cohort: Mapped[str] = mapped_column(String(16), default="2027")
    # Graduation window as published; dates are null when the source gives none.
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_text: Mapped[str] = mapped_column(Text, default="")
    # testamur | cscse_cert | graduation_cert | unknown: which date the window is judged against
    basis: Mapped[str] = mapped_column(String(24), default="testamur")
    # Accepts graduates of the previous cohort who have not taken a job yet ("2026 届未就业").
    accepts_prior_unemployed: Mapped[bool] = mapped_column(Boolean, default=False)
    status_text: Mapped[str] = mapped_column(Text, default="")
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline_text: Mapped[str] = mapped_column(String(200), default="")
    roles: Mapped[list] = mapped_column(JSON, default=list)
    cities: Mapped[list] = mapped_column(JSON, default=list)
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    apply_limit: Mapped[str] = mapped_column(String(300), default="")
    # official | third_party | mixed | unverified
    confidence: Mapped[str] = mapped_column(String(16), default="unverified")
    sources: Mapped[list] = mapped_column(JSON, default=list)
    checked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    company: Mapped[Company] = relationship(back_populates="programs")


class SearchProfile(Base):
    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    roles: Mapped[list] = mapped_column(JSON, default=list)       # [{key, label, keywords}]
    cities: Mapped[list] = mapped_column(JSON, default=list)
    channels: Mapped[list] = mapped_column(JSON, default=list)    # campus | social_entry | foreign_global
    testamur_month: Mapped[date | None] = mapped_column(Date, nullable=True)   # first day of the month
    cscse_cert_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KbChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        Index("ix_kb_chunks_embedding_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    chunk_id: Mapped[str] = mapped_column(String(32), primary_key=True)   # content hash from job_rag_starter
    corpus: Mapped[str] = mapped_column(String(32), index=True)           # experience | company (later)
    section_id: Mapped[str] = mapped_column(String(32), index=True)
    project: Mapped[str] = mapped_column(String(300), default="")
    section: Mapped[str] = mapped_column(String(300), default="")
    source: Mapped[str] = mapped_column(String(500), default="")
    line_start: Mapped[int] = mapped_column(Integer, default=0)
    line_end: Mapped[int] = mapped_column(Integer, default=0)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)               # the embedded window (narrative only)
    parent_text: Mapped[str] = mapped_column(Text)        # the full original section, for display and citation
    search_keywords: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(100))
    embedding = mapped_column(Vector(EMBEDDING_DIM))
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
