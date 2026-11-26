"""Read-only bridge to job_rag_starter.

The section reader, personal-evidence selection, chunking and ranking come
from job_rag_starter's `search_experience.py`, loaded by file path so the two
projects keep one implementation and one experiences library. Nothing is
copied and nothing in job_rag_starter is written.
"""
import importlib.util
import sys
from functools import lru_cache
from pathlib import Path

REQUIRED = ("MODEL", "read_sections", "select_sections", "prepare_search_chunks", "rank_sections",
            "ExperienceRetriever")


class BridgeError(RuntimeError):
    pass


@lru_cache
def load_module(job_rag_home: Path, name: str = "search_experience"):
    path = Path(job_rag_home) / f"{name}.py"
    if not path.is_file():
        raise BridgeError(f"找不到 {path}；请把 CN_JOB_RAG_HOME 设为 job_rag_starter 项目目录")
    spec = importlib.util.spec_from_file_location(f"job_rag_starter_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def search_module(job_rag_home: Path):
    module = load_module(Path(job_rag_home))
    missing = [attr for attr in REQUIRED if not hasattr(module, attr)]
    if missing:
        raise BridgeError(f"job_rag_starter 的 search_experience.py 缺少 {', '.join(missing)}；接口可能已变")
    return module


def passage_text(chunk):
    """The passage format job_rag_starter embeds; kept identical so vectors match."""
    return f"passage: {chunk['project']} | {chunk['section']}\n{chunk['search_keywords']}\n{chunk['text']}"


def query_text(query):
    return "query: " + query.strip()


def experience_chunks(job_rag_home: Path, experiences_dir: Path, tokenizer, all_sections=False):
    """Chunks of the experiences library, exactly as job_rag_starter builds them."""
    module = search_module(job_rag_home)
    records = module.select_sections(module.read_sections(Path(experiences_dir)), all_sections)
    if not records:
        raise BridgeError(f"{experiences_dir} 里没有可检索的 .md / .txt 内容")
    return module.prepare_search_chunks(records, tokenizer)
