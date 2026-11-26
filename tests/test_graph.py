"""The LangGraph job graph end to end, against PostgreSQL, with job_rag_starter's
real jd_parser and EvidenceMatcher driven by a fake model."""
from datetime import date

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select

from cn_job_agent.agents import postings, runner
from cn_job_agent.config import get_settings
from cn_job_agent.db.models import AgentRun, JobPosting, RequirementMatch
from cn_job_agent.db.session import session_scope
from cn_job_agent.rag import store
from cn_job_agent.seed.loader import ProfileIn, SeedFile, load_profile, load_seed

from .conftest import FakeLLM

pytestmark = pytest.mark.pg


def chunk(i, project, body):
    return {"chunk_id": f"g{i:015d}", "section_id": f"t{i:015d}", "project": project, "section": "我的贡献",
            "source": f"{project}.md", "line_start": 1, "line_end": 2, "char_start": 0, "char_end": len(body),
            "text": body, "parent_text": body, "search_keywords": "", "evidence": []}


class FakeToolkit(runner.Toolkit):
    def __init__(self, url, llm, embedder, outputs):
        super().__init__(get_settings(), database_url=url)
        self.outputs_dir = outputs
        self._built.update(llm=llm, embedder=embedder)   # the real matcher is built around these fakes

    def today(self):
        return date(2026, 11, 26)


@pytest.fixture
def world(pg_url, fake_embedder, tmp_path):
    with session_scope(pg_url) as s:
        store.index_chunks(s, fake_embedder, [chunk(1, "Backend", "用 Python 和 FastAPI 开发后端接口"),
                                              chunk(2, "RAG", "用向量检索 RAG 做证据匹配")])
        load_profile(s, ProfileIn.model_validate({
            "roles": [{"key": "agent", "label": "Agent"}], "cities": ["深圳", "武汉"], "channels": ["campus"],
            "testamur_month": "2026-08", "experience_years": 0,
            "education": {"degree": "master", "undergrad_tier": "other", "qs_rank": 77}}))
        load_seed(s, SeedFile.model_validate({"companies": [
            {"key": "acme", "name": "极光科技", "sector": "internet", "programs": [
                {"title": "2027 校招", "window": ["2026-01", "2027-12"], "cities": ["深圳"]}]}]}))
    return {"url": pg_url, "embedder": fake_embedder, "outputs": tmp_path}


def add(world, text, **meta):
    with session_scope(world["url"]) as s:
        posting, _ = postings.add_posting(s, text, **meta)
        return posting.id


def toolkit(world, llm=None):
    return FakeToolkit(world["url"], llm or FakeLLM(), world["embedder"], world["outputs"])


def test_pass_path_matches_every_requirement(world):
    pid = add(world, "AI 应用工程师\n岗位要求：\n- Python 开发\n- 向量检索 RAG\n- Kubernetes 集群运维\n",
              company_name="极光科技（深圳）有限公司", city="深圳", channel="social")
    kit = toolkit(world)
    outcome = runner.start(kit, InMemorySaver(), pid)
    assert outcome.status == "done", outcome.error
    assert outcome.screening["decision"] == "pass"
    assert outcome.summary["counts"] == {"direct": 2, "related": 0, "insufficient": 1, "error": 0}
    assert outcome.summary["score"] == 67
    with session_scope(world["url"]) as s:
        rows = s.scalars(select(RequirementMatch).where(RequirementMatch.run_id == outcome.run_id)).all()
        assert sorted(r.verdict for r in rows) == ["direct", "direct", "insufficient"]
        assert all(e["quote"] for r in rows for e in r.evidence)
        run = s.get(AgentRun, outcome.run_id)
        nodes = [t["node"] for t in run.trace]
        assert {"rule_screen", "extract", "decide", "summarize", "finalize"} <= set(nodes)
        assert nodes.count("match_one") == 3
        assert s.get(JobPosting, pid).status == "matched"
        assert s.get(JobPosting, pid).company.key == "acme"
    report = open(outcome.report_path, encoding="utf-8").read()
    assert "直接支持" in report and "证据缺口" in report and "Kubernetes" in report


def test_hard_flag_rejects_without_judging(world):
    pid = add(world, "Java 工程师\n- 5年以上Java开发经验\n", city="深圳", channel="social")
    llm = FakeLLM()
    outcome = runner.start(toolkit(world, llm), InMemorySaver(), pid)
    assert outcome.status == "rejected"
    assert "judge_evidence" not in llm.tasks
    with session_scope(world["url"]) as s:
        assert s.get(JobPosting, pid).status == "screened_out"
    assert "硬性不符" in open(outcome.report_path, encoding="utf-8").read()


def test_force_matches_a_rejected_posting(world):
    pid = add(world, "后端\n- 5年以上Python开发经验\n", city="深圳", channel="social")
    outcome = runner.start(toolkit(world), InMemorySaver(), pid, force=True)
    assert outcome.status == "done"


def test_review_pauses_and_resumes_from_postgres(world):
    """Interrupt in one process, resume in another: both only share the database."""
    pid = add(world, "全栈开发\n- 1-3年工作经验\n- Python 开发\n", city="深圳", channel="social")
    url = world["url"].replace("postgresql+psycopg://", "postgresql://", 1)
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()
        paused = runner.start(toolkit(world), saver, pid)
    assert paused.status == "interrupted"
    assert paused.interrupt["flags"][0]["code"] == "experience"
    with session_scope(world["url"]) as s:
        assert s.get(AgentRun, paused.run_id).status == "interrupted"
        assert s.get(JobPosting, pid).status == "review"
    with pytest.raises(ValueError):
        with PostgresSaver.from_conn_string(url) as saver:
            runner.resume(toolkit(world), saver, paused.run_id)          # needs an answer
    with PostgresSaver.from_conn_string(url) as saver:                    # a fresh connection and graph
        done = runner.resume(toolkit(world), saver, paused.run_id, approve=True)
    assert done.status == "done"
    assert done.summary["counts"]["direct"] >= 1
    assert "你已确认继续" in open(done.report_path, encoding="utf-8").read()


def test_declined_review_ends_the_run(world):
    pid = add(world, "数据分析\n- 1-3年工作经验\n", city="深圳", channel="social")
    saver = InMemorySaver()
    paused = runner.start(toolkit(world), saver, pid)
    declined = runner.resume(toolkit(world), saver, paused.run_id, approve=False)
    assert declined.status == "rejected"


def test_auto_approve_skips_the_pause(world):
    pid = add(world, "运维\n- 1-3年工作经验\n", city="深圳", channel="social")
    assert runner.start(toolkit(world), InMemorySaver(), pid, auto_approve=True).status == "done"


def test_extraction_failure_is_a_failed_run(world):
    pid = add(world, "某岗位\n- Python 开发\n", city="深圳", channel="social")
    outcome = runner.start(toolkit(world, FakeLLM(fail_extraction=True)), InMemorySaver(), pid)
    assert outcome.status == "failed"
    with session_scope(world["url"]) as s:
        assert s.get(JobPosting, pid).status == "failed"


def test_campus_posting_uses_the_cohort_window(world):
    pid = add(world, "2027届校园招聘 Agent 开发\n- Python 开发\n", company_name="极光科技", city="深圳")
    outcome = runner.start(toolkit(world), InMemorySaver(), pid)
    window = [f for f in outcome.screening["flags"] if f["code"] == "cohort_window"]
    assert window and window[0]["severity"] == "info"


def test_same_jd_is_saved_once(world):
    assert add(world, "重复的 JD\n- Python\n") == add(world, "重复的 JD\r\n- Python\r\n")


def test_compiling_the_graph_builds_nothing_expensive():
    """LangGraph inspects node closures at compile time; that must not load models."""
    from cn_job_agent.agents.graph import build_graph
    kit = runner.Toolkit(get_settings(), database_url="postgresql+psycopg://unused@127.0.0.1:1/none")
    build_graph(kit).get_graph().draw_mermaid()
    assert kit._built == {}


def test_location_requirements_are_left_to_screening(world):
    class LocationLLM(FakeLLM):
        def generate_json(self, task, system_prompt, payload, *args, **kwargs):
            data = super().generate_json(task, system_prompt, payload, *args, **kwargs)
            if task == "extract_requirements":
                for item in data["requirements"]:
                    if "工作地点" in item["text"]:
                        item["category"] = "location"
            return data

    pid = add(world, "某岗位\n- 工作地点深圳\n- Python 开发\n", city="深圳", channel="social")
    outcome = runner.start(toolkit(world, LocationLLM()), InMemorySaver(), pid)
    assert outcome.summary["requirements"] == 1
    assert "由筛选处理的要求" in open(outcome.report_path, encoding="utf-8").read()
