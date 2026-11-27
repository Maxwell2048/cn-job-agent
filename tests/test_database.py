"""Against a real PostgreSQL + pgvector (a throwaway *_test database)."""
from datetime import date

import pytest
from sqlalchemy import func, select

from cn_job_agent.db.models import CampusProgram, Company, KbChunk, SearchProfile
from cn_job_agent.db.session import session_scope
from cn_job_agent.rag import bridge, store
from cn_job_agent.seed.loader import ProfileIn, SeedFile, load_profile, load_seed

pytestmark = pytest.mark.pg


def chunk(i, project, body):
    return {"chunk_id": f"c{i:015d}", "section_id": f"s{i:015d}", "project": project, "section": "我的贡献",
            "source": f"{project}.md", "line_start": 1, "line_end": 3, "char_start": 0, "char_end": len(body),
            "text": body, "parent_text": body, "search_keywords": "", "evidence": []}


CHUNKS = [
    chunk(1, "RAG", "用多语言向量检索和证据校验搭建求职 RAG 系统"),
    chunk(2, "Ticket", "工单系统的权限、审计和 SLA 提醒"),
    chunk(3, "Data", "用 Power BI 和 SQL 做航空数据仓库分析"),
]


def test_index_is_incremental_and_search_ranks(pg_url, fake_embedder, job_rag_home):
    rank_sections = bridge.search_module(job_rag_home).rank_sections
    with session_scope(pg_url) as s:
        counts = store.index_chunks(s, fake_embedder, CHUNKS)      # earlier test files may have left other chunks
        assert (counts["total"], counts["added"], counts["kept"]) == (3, 3, 0)
    calls = fake_embedder.calls
    with session_scope(pg_url) as s:   # unchanged corpus: nothing re-encoded
        assert store.index_chunks(s, fake_embedder, CHUNKS)["added"] == 0
    assert fake_embedder.calls == calls
    changed = CHUNKS[:2] + [chunk(4, "Data", "用 Power BI 做仪表盘")]
    with session_scope(pg_url) as s:
        assert store.index_chunks(s, fake_embedder, changed) == {"total": 3, "added": 1, "removed": 1, "kept": 2}
        assert s.scalar(select(func.count()).select_from(KbChunk)) == 3
    with session_scope(pg_url) as s:
        results = store.search(s, fake_embedder, rank_sections, "向量检索 RAG", top_k=2)
    assert [r["project"] for r in results][0] == "RAG"
    assert len(results) == 2 and results[0]["score"] >= results[1]["score"]
    assert results[0]["text"] == CHUNKS[0]["parent_text"]


def test_seed_and_profile_upserts(pg_url):
    seed = SeedFile.model_validate({"checked_on": "2026-11-21", "companies": [
        {"key": "acme_db", "name": "Acme", "sector": "internet", "programs": [
            {"key": "a", "title": "A", "window": ["2026-01", "2027-12"], "cities": ["武汉"]},
            {"key": "b", "title": "B", "window": None, "basis": "unknown"}]}]})
    with session_scope(pg_url) as s:
        assert load_seed(s, seed) == {"companies": 1, "programs": 2, "programs_removed": 0}
    seed.companies[0].programs = seed.companies[0].programs[:1]
    seed.companies[0].name = "Acme 2"
    with session_scope(pg_url) as s:
        assert load_seed(s, seed)["programs_removed"] == 1
    with session_scope(pg_url) as s:
        company = s.scalar(select(Company).where(Company.key == "acme_db"))
        assert company.name == "Acme 2"
        [program] = s.scalars(select(CampusProgram).where(CampusProgram.company_id == company.id)).all()
        assert program.window_start == date(2026, 1, 1) and program.window_end == date(2027, 12, 31)
        assert program.checked_on == date(2026, 11, 21)

    profile = ProfileIn.model_validate({"roles": [{"key": "r", "label": "R"}], "cities": ["武汉"],
                                        "channels": ["campus"], "testamur_month": "2025-12"})
    with session_scope(pg_url) as s:
        load_profile(s, profile)
        load_profile(s, profile)
    with session_scope(pg_url) as s:
        [row] = s.scalars(select(SearchProfile)).all()
        assert row.testamur_month == date(2025, 12, 1)
