"""Tables.

companies         one employer (腾讯, 工商银行 ...)
campus_programs   one recruiting programme of a company for a cohort, with its
                  graduation window (腾讯 2027 校招, 小红书 REDstar ...)
search_profiles   what the job seeker is looking for: roles, cities, channels,
                  and the dates that decide cohort eligibility
kb_chunks         retrieval chunks of a knowledge corpus with their E5 vectors
                  (pgvector); corpus "experience" is the job_rag_starter library
job_postings      one JD the job seeker added (pasted, file, clipboard)
agent_runs        one run of the LangGraph job graph over a posting; its
                  thread_id is also the LangGraph checkpoint thread
requirement_matches  one row per extracted requirement of a run, with the
                  matching agent's verdict and verified evidence quotes
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
    # Full-time work experience that a Chinese employer would count, in years.
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    # {degree: bachelor|master|phd, undergrad_tier: 985|211|double_first_class|other, qs_rank: int|null}
    education: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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


class JobPosting(Base):
    __tablename__ = "job_postings"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_postings_source_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # manual | file | clipboard | stdin, or a collector key such as tencent / zhiye:iflytek
    source: Mapped[str] = mapped_column(String(32), default="manual")
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)   # the job site's own id
    posted_at: Mapped[str] = mapped_column(String(40), default="")
    collection_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    company_name: Mapped[str] = mapped_column(String(300), default="")
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"),
                                                   nullable=True, index=True)
    city: Mapped[str] = mapped_column(String(100), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    # campus | social | unknown: given by the user or inferred from the JD
    channel: Mapped[str] = mapped_column(String(16), default="unknown")
    jd_text: Mapped[str] = mapped_column(Text)
    jd_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    # new -> screened_out | review | matched | failed
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Company | None] = relationship()
    runs: Mapped[list["AgentRun"]] = relationship(back_populates="posting", cascade="all, delete-orphan",
                                                  order_by="AgentRun.started_at")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)     # also the LangGraph thread_id
    posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    graph_version: Mapped[str] = mapped_column(String(16), default="")
    # running | interrupted | rejected | done | failed
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    screening: Mapped[dict] = mapped_column(JSON, default=dict)      # decision, flags, company verdicts
    summary: Mapped[dict] = mapped_column(JSON, default=dict)        # coverage and score
    versions: Mapped[dict] = mapped_column(JSON, default=dict)       # prompt versions, model
    trace: Mapped[list] = mapped_column(JSON, default=list)          # visited nodes with timings
    report_path: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    posting: Mapped[JobPosting] = relationship(back_populates="runs")
    matches: Mapped[list["RequirementMatch"]] = relationship(back_populates="run", cascade="all, delete-orphan",
                                                             order_by="RequirementMatch.requirement_id")


class RequirementMatch(Base):
    __tablename__ = "requirement_matches"
    __table_args__ = (UniqueConstraint("run_id", "requirement_id", name="uq_match_run_requirement"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    requirement_id: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), index=True)
    importance: Mapped[str] = mapped_column(String(16))
    source_quote: Mapped[str] = mapped_column(Text, default="")
    # direct | related | insufficient | null when processing failed
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    processing_status: Mapped[str] = mapped_column(String(16), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    missing_aspects: Mapped[list] = mapped_column(JSON, default=list)
    questions_for_user: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)

    run: Mapped[AgentRun] = relationship(back_populates="matches")


class CollectionRun(Base):
    """One run of the search planner: which searches it made and what it saved."""
    __tablename__ = "collection_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16))                       # agent | rules
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | done | failed
    plan: Mapped[list] = mapped_column(JSON, default=list)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    trace: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
