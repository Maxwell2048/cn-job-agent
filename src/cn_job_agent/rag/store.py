"""Persist experience chunks in pgvector and search them.

job_rag_starter encodes the whole library in memory on every run. Here the
vectors are stored once and re-encoded only for chunks whose content (and so
whose content-hash chunk_id) changed, or when the embedding model changes.
Ranking reuses job_rag_starter's `rank_sections`, so results are the same
sections in the same order as the in-memory retriever.
"""
from sqlalchemy import delete, select, text

from ..db.models import KbChunk
from . import bridge

EXPERIENCE = "experience"
CHUNK_FIELDS = ("chunk_id", "section_id", "project", "section", "source", "line_start", "line_end",
                "char_start", "char_end", "text", "parent_text", "search_keywords", "evidence")


def check_lengths(embedder, texts):
    """Reject over-long inputs instead of losing text to silent truncation (as job_rag_starter does)."""
    for value in texts:
        if embedder.token_count(value) > embedder.max_seq_length:
            raise ValueError(f"有一段文本超过模型的 {embedder.max_seq_length} token 上限，请缩短标题：{value[:60]}……")


def index_chunks(session, embedder, chunks, corpus=EXPERIENCE):
    """Make the corpus in the table equal `chunks`. Returns counts."""
    wanted = {c["chunk_id"]: c for c in chunks}
    existing = dict(session.execute(
        select(KbChunk.chunk_id, KbChunk.model).where(KbChunk.corpus == corpus)).all())
    stale = [cid for cid, model in existing.items() if cid not in wanted or model != embedder.name]
    if stale:
        session.execute(delete(KbChunk).where(KbChunk.chunk_id.in_(stale)))
    kept = {cid for cid in existing if cid not in stale}
    new = [c for cid, c in wanted.items() if cid not in kept]
    if new:
        passages = [bridge.passage_text(c) for c in new]
        check_lengths(embedder, passages)
        vectors = embedder.encode(passages)
        for chunk, vector in zip(new, vectors):
            session.add(KbChunk(corpus=corpus, model=embedder.name, embedding=[float(x) for x in vector],
                                **{k: chunk[k] for k in CHUNK_FIELDS}))
    session.flush()
    return {"total": len(wanted), "added": len(new), "removed": len(stale), "kept": len(kept)}


def search(session, embedder, rank_sections, query, top_k=5, corpus=EXPERIENCE):
    """Top sections for a query: nearest chunks by cosine distance, then one
    result per source section (job_rag_starter's rank_sections)."""
    query_value = bridge.query_text(query)
    check_lengths(embedder, [query_value])
    vector = [float(x) for x in embedder.encode([query_value])[0]]
    candidates = max(top_k * 10, 50)
    # HNSW returns at most ef_search rows; raise it so deduplication has enough candidates.
    session.execute(text(f"SET LOCAL hnsw.ef_search = {max(candidates, 100)}"))
    distance = KbChunk.embedding.cosine_distance(vector).label("distance")
    rows = session.execute(select(KbChunk, distance).where(KbChunk.corpus == corpus)
                           .order_by(distance).limit(candidates)).all()
    chunks = [{k: getattr(row.KbChunk, k) for k in CHUNK_FIELDS} for row in rows]
    # Normalized vectors: cosine similarity = 1 - distance = the dot product job_rag_starter uses.
    scores = [1.0 - float(row.distance) for row in rows]
    return rank_sections(chunks, scores, top_k)
