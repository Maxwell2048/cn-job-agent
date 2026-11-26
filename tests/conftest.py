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
