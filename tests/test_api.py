"""The web API end to end: FastAPI TestClient, PostgreSQL, the real job graph
with a fake model, background jobs and Server-Sent Events."""
import json
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from cn_job_agent.api import create_app
from cn_job_agent.config import get_settings
from cn_job_agent.db.models import AgentRun
from cn_job_agent.db.session import session_scope

from .conftest import FakeLLM
from .test_collect import FakeSite, job
from .conftest import FakeToolkit

pytestmark = pytest.mark.pg


@pytest.fixture
def client(world):
    saver = InMemorySaver()
    kit = FakeToolkit(world["url"], FakeLLM(), world["embedder"], world["outputs"])
    site = FakeSite("good", "acme", "极光科技", [job("good", "acme", 7, "Agent开发工程师", ["深圳"])])
    app = create_app(get_settings(), toolkit=kit, checkpointer_factory=lambda: nullcontext(saver),
                     collect_options={"collectors": {"good": site}, "chat_model": None}, serve_frontend=False)
    with TestClient(app) as c:
        c.manager = app.state.manager
        yield c


def add(client, text, **meta):
    r = client.post("/api/postings", json={"text": text, **meta})
    assert r.status_code == 201, r.text
    return r.json()["posting"]["id"]


def events(client, path):
    with client.stream("GET", path) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]


def test_add_posting_validates_and_deduplicates(client):
    text = "AI 应用工程师\n岗位要求：\n- Python 开发\n- 向量检索 RAG\n"
    first = client.post("/api/postings", json={"text": text, "city": "深圳", "channel": "social"}).json()
    again = client.post("/api/postings", json={"text": text}).json()
    assert first["created"] and not again["created"] and again["posting"]["id"] == first["posting"]["id"]
    assert client.post("/api/postings", json={"text": "太短"}).status_code == 422


def test_run_in_background_with_live_events(client):
    pid = add(client, "全栈工程师 API\n岗位要求：\n- Python 开发\n- 向量检索 RAG\n- Kubernetes 集群运维\n",
              city="深圳", channel="social")
    r = client.post(f"/api/postings/{pid}/runs", json={})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    client.manager.wait(run_id)

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "done" and run["score"] == 67 and len(run["matches"]) == 3
    assert {m["verdict"] for m in run["matches"]} == {"direct", "insufficient"}
    nodes = [e["node"] for e in events(client, f"/api/runs/{run_id}/events")]
    assert nodes[0] == "__start__" and nodes[-1] == "__end__"
    assert {"rule_screen", "extract", "decide", "summarize", "finalize"} <= set(nodes)
    assert nodes.count("match_one") == 3
    assert "匹配报告" in client.get(f"/api/runs/{run_id}/report").text

    posting = client.get(f"/api/postings/{pid}").json()
    assert posting["status"] == "matched" and posting["latest"]["id"] == run_id and posting["jd_text"]
    assert any(p["id"] == pid for p in client.get("/api/postings", params={"q": "全栈工程师 API"}).json())


def test_review_pauses_and_resumes_over_the_api(client):
    pid = add(client, "后端 API\n- 1-3年工作经验\n- Python 开发\n", city="深圳", channel="social")
    run_id = client.post(f"/api/postings/{pid}/runs", json={}).json()["run_id"]
    client.manager.wait(run_id)
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "interrupted" and run["decision"] == "review"
    assert any(f["code"] == "experience" for f in run["screening"]["flags"])
    assert "__interrupt__" in [e["node"] for e in events(client, f"/api/runs/{run_id}/events")]

    assert client.post(f"/api/runs/{run_id}/resume", json={"approve": True}).status_code == 202
    client.manager.wait(run_id)
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "done"
    assert client.post(f"/api/runs/{run_id}/resume", json={"approve": True}).status_code == 409


def test_collection_in_background(client):
    r = client.post("/api/collections", json={"mode": "rules"})
    collection_id = r.json()["collection_id"]
    client.manager.wait(collection_id)
    detail = client.get(f"/api/collections/{collection_id}").json()
    assert detail["status"] == "done" and detail["mode"] == "rules"
    kinds = [e["node"] for e in events(client, f"/api/collections/{collection_id}/events")]
    assert "search" in kinds and kinds[-1] == "__end__"
    assert client.post("/api/collections", json={"mode": "magic"}).status_code == 422


def test_overview_companies_graph_and_insights(client):
    overview = client.get("/api/overview").json()
    assert overview["companies"] >= 1 and overview["profile"]["cities"]
    companies = client.get("/api/companies", params={"city": ["深圳"]}).json()
    acme = next(c for c in companies if c["key"] == "acme")
    assert acme["programs"][0]["verdict"] == "eligible" and acme["programs"][0]["city_match"] == "city"
    graph = client.get("/api/graph").json()
    ids = {n["id"] for n in graph["nodes"]}
    assert {"rule_screen", "extract", "decide", "human_review", "match_one", "finalize"} <= ids
    assert any(e["conditional"] for e in graph["edges"])
    assert "by_category" in client.get("/api/insights").json()


def test_model_endpoint_never_returns_the_key(client):
    body = client.get("/api/model").text
    key = get_settings().llm_api_key
    assert "api_key" not in body and (key is None or key.get_secret_value() not in body)


def test_errors_and_report_path_guard(client, world):
    assert client.post("/api/postings/999999/runs", json={}).status_code == 404
    assert client.get("/api/runs/nope").status_code == 404
    pid = add(client, "路径测试 API\n- Python 开发\n", city="深圳", channel="social")
    run_id = client.post(f"/api/postings/{pid}/runs", json={}).json()["run_id"]
    client.manager.wait(run_id)
    with session_scope(world["url"]) as s:
        s.get(AgentRun, run_id).report_path = "C:/Windows/win.ini"      # outside the outputs folder
    assert client.get(f"/api/runs/{run_id}/report").status_code == 404


def test_insights_list_skill_gaps_only(client, world):
    from cn_job_agent.db.models import RequirementMatch
    pid = add(client, "缺口测试 API\n- Python 开发\n", city="深圳", channel="social")
    run_id = client.post(f"/api/postings/{pid}/runs", json={}).json()["run_id"]
    client.manager.wait(run_id)
    with session_scope(world["url"]) as s:
        for i, (text, category) in enumerate([("熟悉 Kubernetes", "technical_skill"), ("2027届应届毕业生", "education"),
                                              ("能接受出差", "other"), ("工作地点深圳", "location")]):
            s.add(RequirementMatch(run_id=run_id, requirement_id=f"X{i}", text=text, category=category,
                                   importance="required", verdict="insufficient"))
    gaps = [g["text"] for g in client.get("/api/insights").json()["top_gaps"]]
    assert "熟悉 Kubernetes" in gaps
    assert not {"2027届应届毕业生", "能接受出差", "工作地点深圳"} & set(gaps)
