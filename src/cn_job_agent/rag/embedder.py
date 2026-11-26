"""Embedding model wrapper. Anything with `tokenizer`, `max_seq_length`,
`name` and `encode(texts) -> normalized ndarray` works, so tests can use a
small fake instead of the E5 model."""
import sys


class E5Embedder:
    def __init__(self, model_name, offline=True):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise RuntimeError("缺少 sentence-transformers；请运行 pip install -e .") from exc
        print(f"正在加载向量模型 {model_name}……", file=sys.stderr)
        self.name = model_name
        self.model = SentenceTransformer(model_name, device="cpu", local_files_only=offline)
        self.tokenizer = self.model.tokenizer
        self.max_seq_length = self.model.max_seq_length

    def token_count(self, text):
        return len(self.tokenizer.encode(text))

    def encode(self, texts):
        return self.model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True,
                                 show_progress_bar=False, batch_size=16)
