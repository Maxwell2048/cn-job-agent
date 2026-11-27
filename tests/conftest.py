import hashlib

import numpy as np
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from cn_job_agent.config import PROJECT_ROOT, get_settings
from cn_job_agent.db.models import EMBEDDING_DIM


class CharTokenizer:
    """One token per character, with the offset mapping job_rag_starter's chunker reads."""

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=True):
        return {"offset_mapping": [(i, i + 1) for i in range(len(text))]}

    def encode(self, text):
        return list(text)


class FakeEmbedder:
    """Deterministic bag-of-character-bigram vectors: texts sharing words score higher."""
    name = "fake-bigram"
    max_seq_length = 10_000

    def __init__(self):
        self.tokenizer = CharTokenizer()
        self.calls = 0

    def token_count(self, value):
        return len(value)

    def encode(self, texts):
        texts = list(texts)
        self.calls += len(texts)
        out = np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)
        for row, value in enumerate(texts):
            body = value.split(":", 1)[-1].lower()   # drop the "query:" / "passage:" prefix
            for a, b in zip(body, body[1:]):
                if a.isspace() or b.isspace():
                    continue
                slot = int(hashlib.md5((a + b).encode()).hexdigest(), 16) % EMBEDDING_DIM
                out[row, slot] += 1.0
            norm = np.linalg.norm(out[row])
            out[row] = out[row] / norm if norm else out[row]
            if not norm:
                out[row, 0] = 1.0
        return out


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture(scope="session")
def job_rag_home():
    home = get_settings().job_rag_home
    if not (home / "search_experience.py").is_file():
        pytest.skip(f"job_rag_starter not found at {home}")
    return home


def _test_url():
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test")


@pytest.fixture(scope="session")
def pg_url():
    """A throwaway database next to the configured one, migrated from scratch."""
    url = _test_url()
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not reachable ({exc.__class__.__name__}); run docker compose up -d db")
    finally:
        admin.dispose()

    from alembic import command
    from alembic.config import Config
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    rendered = url.render_as_string(hide_password=False)
    config.attributes["database_url"] = rendered
    command.upgrade(config, "head")
    yield rendered
    config.attributes["database_url"] = rendered
    command.downgrade(config, "base")


class FakeLLM:
    """Stands in for job_rag_starter's local model adapter.

    extract_requirements: one requirement per JD line that starts with "- ",
    quoting the line verbatim (category from a keyword).
    judge_evidence: "direct" with a verbatim quote from the first candidate when
    the candidate shares a word with the requirement, else "insufficient".
    """
    model = "fake-llm"
    prompt_char_budget = 200_000

    def __init__(self, fail_extraction=False):
        self.fail_extraction = fail_extraction
        self.tasks = []

    def estimate_context(self, task, system_prompt, payload, schema):
        import json
        return len(system_prompt) + len(json.dumps(payload, ensure_ascii=False))

    def generate_json(self, task, system_prompt, payload, schema=None, timeout_seconds=None, validate=None):
        self.tasks.append(task)
        if task == "extract_requirements":
            if self.fail_extraction:
                from cn_job_agent.config import get_settings
                from cn_job_agent.rag import bridge
                raise bridge.load(get_settings().job_rag_home, "local_llm").ServiceError("model down")
            items = []
            for line in payload["jd_text"].splitlines():
                if not line.startswith("- "):
                    continue
                body = line[2:].strip()
                category = "experience" if "经验" in body else "education" if "学历" in body else "technical_skill"
                items.append({"text": body, "category": category, "importance": "required",
                              "source_quote": body, "importance_source_quote": body, "qualifiers": [],
                              "search_queries": [body], "needs_review": False})
            return {"requirements": items, "requirement_groups": []}
        if task == "judge_evidence":
            requirement = payload["requirement"]
            words = [w for w in requirement["text"].replace("，", " ").split() if len(w) >= 2]
            for candidate in payload["candidates"]:
                hit = next((w for w in words if w in candidate["text"]), None)
                if hit:
                    return {"requirement_id": requirement["requirement_id"], "verdict": "direct",
                            "reason": f"候选提到 {hit}", "evidence": [{"candidate_id": candidate["candidate_id"],
                                                                     "quote": hit}],
                            "missing_aspects": [], "questions_for_user": []}
            return {"requirement_id": requirement["requirement_id"], "verdict": "insufficient",
                    "reason": "当前检索资料未提供证据", "evidence": [], "missing_aspects": [requirement["text"]],
                    "questions_for_user": []}
        raise AssertionError(task)


@pytest.fixture
def fake_llm():
    return FakeLLM()


# ---------------------------------------------------------------- shared world for graph, collect and API tests
def chunk(i, project, body):
    return {"chunk_id": f"g{i:015d}", "section_id": f"t{i:015d}", "project": project, "section": "我的贡献",
            "source": f"{project}.md", "line_start": 1, "line_end": 2, "char_start": 0, "char_end": len(body),
            "text": body, "parent_text": body, "search_keywords": "", "evidence": []}


def _toolkit_base():
    from cn_job_agent.agents import runner
    return runner.Toolkit


class FakeToolkit(_toolkit_base()):
    """The real Toolkit (real jd_parser and EvidenceMatcher) around a fake model and embedder."""

    def __init__(self, url, llm, embedder, outputs):
        super().__init__(get_settings(), database_url=url)
        self.outputs_dir = outputs
        self._built.update(llm=llm, embedder=embedder)

    def today(self):
        from datetime import date
        return date(2026, 11, 26)


@pytest.fixture
def world(pg_url, fake_embedder, tmp_path):
    """Two indexed experience chunks, a profile and one eligible company (acme, 极光科技)."""
    from cn_job_agent.db.session import session_scope
    from cn_job_agent.rag import store
    from cn_job_agent.seed.loader import ProfileIn, SeedFile, load_profile, load_seed
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
