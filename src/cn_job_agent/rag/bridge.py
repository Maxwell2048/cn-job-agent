"""Read-only bridge to job_rag_starter.

job_rag_starter's modules are plain top-level files that import each other by
name (`jd_parser` imports `local_llm`), so the bridge puts the project folder
on sys.path and imports them normally, then checks each module really came
from that folder. Reused as-is:

  search_experience   section reader, personal-evidence selection, chunking, ranking
  jd_parser           JD requirement extraction with verbatim-quote validation
  evidence_matcher    per-requirement evidence judgment with quote verification
  local_llm           local OpenAI-compatible / LangChain model adapters

Nothing is copied and nothing in job_rag_starter is written.
"""
import importlib
import sys
from pathlib import Path

REQUIRED = {
    "search_experience": ("MODEL", "read_sections", "select_sections", "prepare_search_chunks",
                          "rank_sections", "ExperienceRetriever"),
    "jd_parser": ("extract_requirements", "normalize_jd", "EXTRACTION_PROMPT_VERSION"),
    "evidence_matcher": ("EvidenceMatcher", "JUDGMENT_PROMPT_VERSION", "VERDICTS"),
    "local_llm": ("load_config", "build_llm", "LLMError"),
}


class BridgeError(RuntimeError):
    pass


def load(job_rag_home: Path, name: str):
    home = Path(job_rag_home).resolve()
    if not (home / f"{name}.py").is_file():
        raise BridgeError(f"找不到 {home / (name + '.py')}；请把 CN_JOB_RAG_HOME 设为 job_rag_starter 项目目录")
    if str(home) not in sys.path:
        sys.path.append(str(home))
    module = importlib.import_module(name)
    origin = Path(module.__file__).resolve().parent
    if origin != home:
        raise BridgeError(f"模块 {name} 来自 {origin}，不是 {home}；可能和已安装的同名包冲突")
    missing = [attr for attr in REQUIRED.get(name, ()) if not hasattr(module, attr)]
    if missing:
        raise BridgeError(f"job_rag_starter 的 {name}.py 缺少 {', '.join(missing)}；接口可能已变")
    return module


def search_module(job_rag_home: Path):
    return load(job_rag_home, "search_experience")


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
