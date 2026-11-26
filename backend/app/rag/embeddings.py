"""Sentence-Transformers embeddings (lazy-loaded singleton)."""
import threading
from typing import List

from app.config import settings
from app.utils.logger import logger

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                logger.info(f"[RAG] Loading embedding model {settings.EMBEDDING_MODEL} ...")
                _model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _model


def embed_texts(texts: List[str]) -> List[List[float]]:
    vecs = _get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]


def embed_query(text: str) -> List[float]:
    return embed_texts([text])[0]
