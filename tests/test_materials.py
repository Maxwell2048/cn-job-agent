"""Materials agent: the checks, pruning, rendering and the API, with a fictional
experiences library and base resume (no real personal data, no model)."""
import json
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from cn_job_agent.agents import materials
from cn_job_agent.agents.materials import Inputs, Section, check, prune
from cn_job_agent.api import create_app
from cn_job_agent.config import get_settings

from .conftest import FakeLLM, FakeToolkit


def sec(id_, project_id, text, project="Demo 项目：检索系统"):
    return Section(id_, project_id, project, "我的工作 检索", "demo.md", 3, 5, text)


def inputs(greeting_max=150):
    e1 = sec("E001", "P1", "我用 Python 和 FastAPI 实现检索接口，测试 120 项全部通过。")
    e2 = sec("E002", "P2", "共同完成 BiLSTM 模型训练，验证集 accuracy 0.73。", project="NLI 课程项目")
    g1 = Section("G01", "", "个人基本信息", "学历 Education", "profile.md", 6, 9, "信息技术硕士（人工智能方向）")
    return Inputs("r1", {"title": "AI 应用工程师", "company": "示例", "jd_text": "熟悉 Python、Docker", "city": "深圳"},
                  [], [], [{"project_id": "P1", "title": e1.project, "score": 3, "sections": [e1]},
                           {"project_id": "P2", "title": e2.project, "score": 1, "sections": [e2]}],
                  [g1], [["编程语言", "Python（精通）；SQL（熟练）"]], None, greeting_max,
                  {"E001": e1, "E002": e2, "G01": g1})


def draft(**override):
    data = {
        "target_title": "AI 应用工程师",
        "summary": {"text": "信息技术硕士，熟悉 Python。", "cites": ["G01", "E001"]},
        "projects": [{"project_id": "P1", "role": "", "period": "", "bullets": [
            {"label": "检索接口", "text": "用 Python 和 FastAPI 实现检索接口，120 项测试全部通过。", "cites": ["E001"]}]}],
        "greeting": {"text": "您好，我是信息技术硕士，做过 Python 检索接口，希望进一步沟通。", "cites": ["G01", "E001"]},
    }
    data.update(override)
    return data


def bullet(text, cites=("E001",)):
    return draft(projects=[{"project_id": "P1", "role": "", "period": "", "bullets": [
        {"label": "检索接口", "text": text, "cites": list(cites)}]}])


def errors(data):
    return materials.flatten(check(data, inputs()))


def test_a_supported_draft_passes():
    assert errors(draft()) == []


@pytest.mark.parametrize("text, reason", [
    ("用 Python 和 Docker 部署检索接口。", "Docker"),                 # a tool only the JD mentions
    ("检索接口测试 300 项全部通过。", "300"),                          # a number not in the source
    ("负责 Active Directory 账号管理。", "管理员侧"),
    ("在实习期间实现检索接口。", "实习"),
    ("检索准确率显著提升。", "夸大"),
    ("带领 5 人团队实现检索接口。", "团队人数"),
    ("实现多 Agent 协作的检索接口。", "多 Agent"),                     # a claim the source does not make
    ("用 Python 实现 Agent 系统的检索接口。", "Agent 系统"),            # "Agent" alone in a source is not enough
])
def test_unsupported_bullets_are_rejected(text, reason):
    assert any(reason in e for e in errors(bullet(text)))


def test_citations_must_exist_and_belong_to_the_project():
    assert any("不能用的编号" in e for e in errors(bullet("共同完成 BiLSTM 模型训练。", cites=["E002"])))
    assert any("没有在 cites" in e for e in errors(bullet("用 Python 实现检索接口。", cites=[])))
    assert any("不在给定项目" in e for e in errors(draft(projects=[{"project_id": "P9", "role": "", "period": "",
                                                                    "bullets": []}])))


def test_greeting_limits():
    long = draft(greeting={"text": "您好，" + "我熟悉 Python。" * 30, "cites": ["E001"]})
    assert any("超过" in e for e in materials.flatten(check(long, inputs())))
    contact = draft(greeting={"text": "您好，我熟悉 Python，邮箱 a@b.com。", "cites": ["E001"]})
    assert any("邮箱" in e for e in errors(contact))


def test_period_must_come_from_the_material():
    data = draft(projects=[{"project_id": "P1", "role": "全栈", "period": "2024.01 - 2024.06", "bullets": [
        {"label": "检索接口", "text": "用 Python 实现检索接口。", "cites": ["E001"]}]}])
    assert any("时间" in e for e in errors(data))


def test_prune_keeps_what_passes():
    data = draft(projects=[{"project_id": "P1", "role": "", "period": "", "bullets": [
        {"label": "检索接口", "text": "用 Python 实现检索接口。", "cites": ["E001"]},
        {"label": "部署", "text": "用 Kubernetes 部署。", "cites": ["E001"]}]}])
    kept, warnings = prune(data, check(data, inputs()))
    assert [b["label"] for b in kept["projects"][0]["bullets"]] == ["检索接口"]
    assert any("Kubernetes" in w for w in warnings)


def test_skills_are_reordered_not_changed():
    skills = [["办公软件", "Excel、Word"], ["后端", "FastAPI、PostgreSQL"]]
    assert materials.ordered_skills(skills, "熟悉 FastAPI 和 PostgreSQL") == [skills[1], skills[0]]


def test_base_project_matching():
    base = {"sections": [{"title": "项目经历", "entries": [{"left": "Demo 检索平台", "mid": "全栈开发", "right": "2025.03 - 至今"}]}]}
    assert materials.base_project(base, "Demo 项目：检索系统")["mid"] == "全栈开发"
    assert materials.base_project(base, "其他项目") is None


# ---------------------------------------------------------------- end to end (PostgreSQL)
class DraftLLM(FakeLLM):
    """Returns a fixed draft; when a check is passed in and fails, behaves like an
    exhausted attempt budget (an error with error_type)."""

    def __init__(self, data):
        super().__init__()
        self.data = data

    def generate_json(self, task, system_prompt, payload, schema=None, timeout_seconds=None, validate=None):
        if task != "tailor_resume_zh":
            return super().generate_json(task, system_prompt, payload, schema, timeout_seconds, validate)
        self.tasks.append(task)
        self.payload = payload
        if validate and validate(self.data):
            error = RuntimeError("attempts exhausted")
            error.error_type = "validation"
            raise error
        return self.data


pg = pytest.mark.pg


@pg
def test_build_writes_checked_materials(library):
    llm = DraftLLM(draft())
    result = materials.build(library["settings"], library["run_id"], llm)
    payload = json.dumps(llm.payload, ensure_ascii=False)
    assert "测试用户" not in payload and "test@example.com" not in payload     # never sent to the model
    assert [p["title"] for p in llm.payload["projects"]] == ["Demo 项目：检索系统"]
    project = result.data["projects"][0]
    assert (project["role"], project["period"]) == ("全栈开发", "2025.03 - 至今")   # from the base resume
    assert result.gaps == ["熟悉 Kubernetes"] and result.warnings == []
    assert result.skills[0][0] == "后端"
    folder = materials.latest(library["outputs"], library["run_id"])
    md = (folder / "resume_zh.md").read_text(encoding="utf-8")
    assert "测试用户" in md and "示例大学" in md and "**检索接口**" in md
    assert (folder / "resume_zh.docx").stat().st_size > 5000
    assert json.loads((folder / "materials.json").read_text(encoding="utf-8"))["citations"]["E001"]["source"] == "demo.md"


@pg
def test_build_drops_what_still_fails(library):
    bad = draft(projects=[{"project_id": "P1", "role": "", "period": "", "bullets": [
        {"label": "检索接口", "text": "用 Python 实现检索接口。", "cites": ["E001"]},
        {"label": "部署", "text": "用 Kubernetes 部署检索接口。", "cites": ["E001"]}]}])
    result = materials.build(library["settings"], library["run_id"], DraftLLM(bad))
    assert [b["label"] for b in result.data["projects"][0]["bullets"]] == ["检索接口"]
    assert any("Kubernetes" in w for w in result.warnings)


@pg
def test_materials_api(library, fake_embedder):
    kit = FakeToolkit(library["url"], DraftLLM(draft()), fake_embedder, library["outputs"])
    kit.settings = library["settings"]
    app = create_app(library["settings"], toolkit=kit, checkpointer_factory=lambda: nullcontext(InMemorySaver()),
                     serve_frontend=False)
    with TestClient(app) as client:
        run_id = library["run_id"]
        assert client.get(f"/api/runs/{run_id}/materials").status_code == 404
        job = client.post(f"/api/runs/{run_id}/materials").json()["job"]
        app.state.manager.wait(job)
        body = client.get(f"/api/runs/{run_id}/materials").json()
        assert body["draft"]["greeting"]["text"] and "folder" not in body
        assert set(body["files"]) == {"resume_zh.docx", "resume_zh.md", "greeting.txt"}
        assert client.get(f"/api/runs/{run_id}/materials/resume_zh.docx").status_code == 200
        assert client.get(f"/api/runs/{run_id}/materials/materials.json").status_code == 404
        assert client.post("/api/runs/nope/materials").status_code == 404
    get_settings.cache_clear()


@pg
def test_base_resume_role_and_period_win(library):
    data = draft(projects=[{"project_id": "P1", "role": "后端", "period": "2025", "bullets": [
        {"label": "检索接口", "text": "用 Python 实现检索接口。", "cites": ["E001"]}]}])
    project = materials.build(library["settings"], library["run_id"], DraftLLM(data)).data["projects"][0]
    assert (project["role"], project["period"]) == ("全栈开发", "2025.03 - 至今")
