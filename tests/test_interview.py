"""Interview-prep agent: checks, pruning and the API, with the fictional library
from the materials tests (no real personal data, no model)."""
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from cn_job_agent.agents import interview
from cn_job_agent.api import create_app
from cn_job_agent.config import get_settings

from .conftest import FakeToolkit
from .test_materials import DraftLLM, inputs


def cited(text, *cites):
    return {"text": text, "cites": list(cites)}


def prep(**override):
    data = {
        "self_intro": cited("我是信息技术硕士，用 Python 和 FastAPI 实现过检索接口。", "G01", "E001"),
        "project_questions": [{"project_id": "P1", "question": "检索接口怎么测试？", "answer_points": [
            cited("用 Python 和 FastAPI 实现检索接口，120 项测试全部通过。", "E001")]}],
        "technical_questions": [{"requirement_id": "R001", "question": "RAG 的流程是什么？",
                                 "answer_outline": "先检索相关片段，再交给模型生成带引用的回答。",
                                 "my_experience": cited("", )}],
        "gap_questions": [{"requirement_id": "R002", "question": "用过 Kubernetes 吗？",
                           "strategy": cited("没有直接经验，会先在本机用 Docker 熟悉容器，再学习编排。")}],
        "questions_to_ask": ["团队现在的检索方案是什么？"],
    }
    data.update(override)
    return data


def problems(data):
    return interview.check(data, inputs())


def test_a_supported_prep_passes():
    assert problems(prep()) == {}


def test_personal_answers_must_be_backed():
    data = prep(project_questions=[{"project_id": "P1", "question": "部署？", "answer_points": [
        cited("用 Kubernetes 部署检索接口。", "E001")]}])
    assert any("Kubernetes" in e for e in interview.prune(data, problems(data))[1])
    data = prep(self_intro=cited("我做过多 Agent 系统。", "E001"))
    assert "intro" in problems(data)


def test_concept_outlines_need_no_citation_but_keep_the_boundaries():
    assert problems(prep()) == {}                                   # outline without cites is fine
    data = prep(technical_questions=[{"requirement_id": "R1", "question": "权限管理？",
                                      "answer_outline": "我在实习时负责 Active Directory 账号管理。",
                                      "my_experience": cited("")}])
    assert ("technical", 0) in problems(data)


def test_prune_keeps_what_passes():
    data = prep(project_questions=[{"project_id": "P1", "question": "测试？", "answer_points": [
        cited("用 Python 实现检索接口。", "E001"), cited("测试覆盖率 95%。", "E001")]}])
    kept, warnings = interview.prune(data, problems(data))
    assert [p["text"] for p in kept["project_questions"][0]["answer_points"]] == ["用 Python 实现检索接口。"]
    assert any("95" in w for w in warnings)


class PrepLLM(DraftLLM):
    def generate_json(self, task, system_prompt, payload, schema=None, timeout_seconds=None, validate=None):
        if task == "interview_prep_zh":
            return super().generate_json("tailor_resume_zh", system_prompt, payload, schema, timeout_seconds, validate)
        return super().generate_json(task, system_prompt, payload, schema, timeout_seconds, validate)


@pytest.mark.pg
def test_build_and_api(library, fake_embedder):
    result = interview.build(library["settings"], library["run_id"], PrepLLM(prep()))
    assert result["draft"]["project_questions"][0]["answer_points"] and result["warnings"] == []
    assert "E001" in result["citations"]
    kit = FakeToolkit(library["url"], PrepLLM(prep()), fake_embedder, library["outputs"])
    kit.settings = library["settings"]
    app = create_app(library["settings"], toolkit=kit, checkpointer_factory=lambda: nullcontext(InMemorySaver()),
                     serve_frontend=False)
    with TestClient(app) as client:
        run_id = library["run_id"]
        job = client.post(f"/api/runs/{run_id}/interview").json()["job"]
        app.state.manager.wait(job)
        body = client.get(f"/api/runs/{run_id}/interview").json()
        assert body["draft"]["self_intro"]["text"] and "folder" not in body
        md = client.get(f"/api/runs/{run_id}/interview/interview.md")
        assert md.status_code == 200 and "项目深挖" in md.text
        assert client.post("/api/runs/nope/interview").status_code == 404
    get_settings.cache_clear()
