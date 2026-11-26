"""Matching agent: per-requirement evidence judgment.

job_rag_starter's EvidenceMatcher does the work (retrieval per search query,
candidate numbering, model judgment, verbatim-quote verification against the
full section). What changes here is the retriever: `PgRetriever` serves the
same results from pgvector instead of an in-memory index, so the matcher
needs no changes.
"""
import threading
from types import SimpleNamespace

from sqlalchemy import select

from ..db.models import KbChunk
from ..db.session import session_scope
from ..rag import store

VALUE = {"direct": 1.0, "related": 0.5, "insufficient": 0.0}
WEIGHT = {"required": 2.0, "unspecified": 1.0, "preferred": 0.5}
LABELS = [(70, "强匹配"), (50, "可以投"), (30, "勉强"), (0, "弱匹配")]


class PgRetriever:
    """The retriever interface EvidenceMatcher expects: search() and
    basic_profile_candidates(), backed by the kb_chunks table."""
    framework = "pgvector"

    def __init__(self, database_url, embedder, search_module):
        self.database_url = database_url
        self.embedder = embedder
        self.module = search_module
        self._profile_chunks = None
        self._lock = threading.Lock()

    def search(self, query, top_k=5):
        with session_scope(self.database_url) as session:
            return store.search(session, self.embedder, self.module.rank_sections, query, top_k=top_k)

    def _profile(self):
        with self._lock:
            if self._profile_chunks is None:
                with session_scope(self.database_url) as session:
                    rows = session.scalars(select(KbChunk).where(KbChunk.corpus == store.EXPERIENCE,
                                                                 KbChunk.source.like("%profile.md"))).all()
                    self._profile_chunks = [{k: getattr(r, k) for k in store.CHUNK_FIELDS} for r in rows]
            return self._profile_chunks

    def basic_profile_candidates(self, query):
        """job_rag_starter's own rule (which declared basic skills to pin), run
        over the profile chunks stored in pgvector."""
        shim = SimpleNamespace(model=True, chunks=self._profile())
        return self.module.ExperienceRetriever.basic_profile_candidates(shim, query)


def build_llm(settings):
    """The JSON-task model adapter for the configured provider (local model or a
    mainstream API, see cn_job_agent.llm); diagnostics go to this project's state folder."""
    from .. import llm
    return llm.build_json_llm(settings)


def summarize(matches):
    """Counts and a weighted evidence score. The score summarises evidence
    coverage only; it is not a probability of getting the job."""
    counts = {"direct": 0, "related": 0, "insufficient": 0, "error": 0}
    by_importance = {}
    total_weight = earned = 0.0
    for match in matches:
        verdict = match.get("verdict")
        key = verdict if verdict in VALUE else "error"
        counts[key] += 1
        importance = match.get("importance", "unspecified")
        bucket = by_importance.setdefault(importance, {"direct": 0, "related": 0, "insufficient": 0, "error": 0})
        bucket[key] += 1
        if verdict in VALUE:
            weight = WEIGHT.get(importance, 1.0)
            total_weight += weight
            earned += weight * VALUE[verdict]
    conditions = [m for m in matches if m.get("category") != "responsibility" and m.get("verdict") in VALUE]
    insufficient_share = (sum(m["verdict"] == "insufficient" for m in conditions) / len(conditions)) \
        if conditions else None
    score = round(100 * earned / total_weight) if total_weight else None
    label = next((name for floor, name in LABELS if score is not None and score >= floor), "无法评分")
    required = [m for m in matches if m.get("importance") == "required" and m.get("verdict") in VALUE]
    return {
        "requirements": len(matches),
        "counts": counts,
        "by_importance": by_importance,
        "score": score,
        "label": label,
        "required_covered": sum(m["verdict"] in ("direct", "related") for m in required),
        "required_total": len(required),
        "condition_insufficient_share": None if insufficient_share is None else round(insufficient_share, 3),
        "formula": "加权平均：direct=1、related=0.5、insufficient=0；必需×2、未注明×1、优先×0.5；处理失败的要求不计入",
    }
