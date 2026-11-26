"""The search planner (rules and tool-calling agent modes) against PostgreSQL with fake job sites."""
import copy

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from cn_job_agent.agents import runner
from cn_job_agent.agents.collect import collect
from cn_job_agent.collectors import ListedJob
from cn_job_agent.config import get_settings
from cn_job_agent.db.models import CollectionRun, JobPosting
from cn_job_agent.db.session import session_scope
from cn_job_agent.seed.loader import ProfileIn, SeedFile, load_profile, load_seed

from .conftest import FakeLLM
from .test_graph import FakeToolkit

pytestmark = pytest.mark.pg


class FakeSite:
    def __init__(self, key, company_key, company_name, jobs):
        self.key, self.company_key, self.company_name, self.jobs = key, company_key, company_name, jobs
        self.searches = []

    def search(self, keyword, limit=40):
        self.searches.append(keyword)
        return [copy.copy(j) for j in self.jobs if keyword.lower() in j.title.lower()][:limit]

    def detail(self, job):
        job.jd_text = f"{job.title}\n岗位要求：\n- Python 开发\n"
        return job


def job(key, company, i, title, cities):
    return ListedJob(source=key, external_id=str(i), company_key=company, title=title, cities=cities,
                     url=f"https://example.test/{key}/{i}", category="校园招聘")


@pytest.fixture
def sites(pg_url):
    with session_scope(pg_url) as s:
        s.query(JobPosting).filter(JobPosting.source.in_(["good", "late"])).delete()
        load_profile(s, ProfileIn.model_validate({
            "roles": [{"key": "agent", "label": "Agent 开发", "keywords": ["Agent", "全栈"]}],
            "cities": ["深圳", "武汉"], "channels": ["campus"], "testamur_month": "2026-08"}))
        load_seed(s, SeedFile.model_validate({"companies": [
            {"key": "goodco", "name": "好公司", "sector": "internet", "programs": [
                {"title": "2027 校招", "window": ["2026-01", "2027-12"], "cities": ["深圳"]}]},
            {"key": "lateco", "name": "晚公司", "sector": "internet", "programs": [
                {"title": "2027 校招", "window": ["2026-09", None]}]}]}))
    good = FakeSite("good", "goodco", "好公司", [
        job("good", "goodco", 1, "Agent开发工程师", ["深圳", "北京"]),
        job("good", "goodco", 2, "AI全栈工程师", ["武汉"]),
        job("good", "goodco", 3, "Agent算法工程师", ["新加坡"]),          # wrong city
        job("good", "goodco", 4, "Agent开发实习生", ["深圳"]),            # internship
        job("good", "goodco", 5, "资深Agent架构师", ["深圳"]),            # senior
    ])
    late = FakeSite("late", "lateco", "晚公司", [job("late", "lateco", 9, "Agent开发工程师", ["深圳"])])
    return {"url": pg_url, "good": good, "late": late}


def test_rules_mode_keeps_relevant_jobs_in_target_cities(sites):
    collectors = {"good": sites["good"], "late": sites["late"]}
    outcome = collect(get_settings(), mode="rules", database_url=sites["url"], collectors=collectors)
    assert outcome.status == "done" and outcome.mode == "rules"
    assert sorted(s["title"] for s in outcome.saved) == ["AI全栈工程师", "Agent开发工程师"]
    assert sites["late"].searches == []            # ineligible cohort window: not searched
    with session_scope(sites["url"]) as s:
        rows = s.scalars(select(JobPosting).where(JobPosting.source == "good")).all()
        assert {r.external_id for r in rows} == {"1", "2"}
        assert all(r.company.key == "goodco" and r.channel == "campus" and r.status == "new" for r in rows)
        run = s.get(CollectionRun, outcome.run_id)
        assert run.status == "done" and run.stats["saved"] == 2 and run.plan
    again = collect(get_settings(), mode="rules", database_url=sites["url"], collectors=collectors)
    assert again.stats["saved"] == 0               # already saved postings are skipped


class ScriptedChatModel(BaseChatModel):
    """Returns pre-written AI messages in order; bind_tools is accepted and ignored."""
    script: list
    position: int = 0

    @property
    def _llm_type(self):
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self.script[self.position]
        self.position += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def call(name, args, i):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{i}", "type": "tool_call"}])


def test_agent_mode_runs_the_tool_loop(sites):
    model = ScriptedChatModel(script=[
        call("list_sources", {}, 1),
        call("search_jobs", {"source": "good", "keyword": "Agent"}, 2),
        call("save_jobs", {"source": "good", "ids": ["1", "3"], "reason": "Agent 开发岗位"}, 3),
        AIMessage(content="搜索了 good 网站，保存 1 个岗位。"),
    ])
    outcome = collect(get_settings(), mode="agent", database_url=sites["url"],
                      collectors={"good": sites["good"], "late": sites["late"]}, chat_model=model)
    assert outcome.status == "done" and outcome.mode == "agent"
    assert [s["title"] for s in outcome.saved] == ["Agent开发工程师", "Agent算法工程师"]
    with session_scope(sites["url"]) as s:
        run = s.get(CollectionRun, outcome.run_id)
        kinds = [(t["type"], t.get("tool")) for t in run.trace]
        assert kinds[:2] == [("tool_call", "list_sources"), ("tool_result", "list_sources")]
        assert ("tool_call", "save_jobs") in kinds and kinds[-1] == ("answer", None)


def test_save_requires_a_prior_search(sites):
    model = ScriptedChatModel(script=[
        call("save_jobs", {"source": "good", "ids": ["1"], "reason": "猜的"}, 1),
        AIMessage(content="完成"),
    ])
    outcome = collect(get_settings(), mode="agent", database_url=sites["url"],
                      collectors={"good": sites["good"]}, chat_model=model)
    assert outcome.saved == []


class BrokenModel(ScriptedChatModel):
    def _generate(self, *args, **kwargs):
        raise RuntimeError("tools not supported")


def test_auto_mode_falls_back_to_rules(sites):
    outcome = collect(get_settings(), mode="auto", database_url=sites["url"],
                      collectors={"good": sites["good"]}, chat_model=BrokenModel(script=[]))
    assert outcome.mode == "rules" and outcome.status == "done" and len(outcome.saved) == 2
    with session_scope(sites["url"]) as s:
        trace = s.get(CollectionRun, outcome.run_id).trace
        assert trace[0]["type"] == "fallback" and "tools not supported" in trace[0]["text"]


def test_agent_mode_does_not_fall_back(sites):
    outcome = collect(get_settings(), mode="agent", database_url=sites["url"],
                      collectors={"good": sites["good"]}, chat_model=BrokenModel(script=[]))
    assert outcome.status == "failed" and "tools not supported" in outcome.error


def test_collected_postings_are_processed_from_the_queue(sites, fake_embedder, tmp_path):
    collect(get_settings(), mode="rules", database_url=sites["url"], collectors={"good": sites["good"]})
    kit = FakeToolkit(sites["url"], FakeLLM(), fake_embedder, tmp_path)
    outcomes = runner.process_pending(kit, InMemorySaver(), limit=10)
    assert outcomes and all(o.status in ("done", "interrupted", "rejected") for _, o in outcomes)
    assert runner.pending_postings(sites["url"], 10) == []
