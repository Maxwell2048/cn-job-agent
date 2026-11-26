from cn_job_agent.rag import bridge


def test_bridge_exposes_the_job_rag_starter_functions(job_rag_home):
    module = bridge.search_module(job_rag_home)
    assert module.MODEL == "intfloat/multilingual-e5-small"


def test_chunks_of_the_fictional_examples(job_rag_home, fake_embedder):
    chunks = bridge.experience_chunks(job_rag_home, job_rag_home / "examples" / "experiences",
                                      fake_embedder.tokenizer)
    assert chunks
    for chunk in chunks:
        assert len(chunk["chunk_id"]) == 16 and len(chunk["section_id"]) == 16
        # The embedded window is a slice of the narrative; the parent keeps the original section.
        assert chunk["text"] and chunk["parent_text"]
        assert "http" not in chunk["text"]


def test_passage_and_query_formats_match_job_rag_starter():
    chunk = {"project": "P", "section": "S", "search_keywords": "k", "text": "t"}
    assert bridge.passage_text(chunk) == "passage: P | S\nk\nt"
    assert bridge.query_text("  RAG ") == "query: RAG"
