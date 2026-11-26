"""ChromaDB persistent vector store for the Fortivex knowledge base."""
import shutil
from pathlib import Path
from typing import Optional

import chromadb

from app.config import settings
from app.rag.embeddings import embed_texts
from app.rag.ingestion import knowledge_fingerprint, load_knowledge_records, record_to_chunk
from app.utils.logger import logger

_client: Optional[chromadb.api.ClientAPI] = None


def _fingerprint_file() -> Path:
    return Path(settings.CHROMA_DIR) / "kb_fingerprint.txt"


def get_client():
    global _client
    if _client is None:
        Path(settings.CHROMA_DIR).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=settings.CHROMA_DIR)
    return _client


def get_collection():
    return get_client().get_or_create_collection(
        name=settings.CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"}
    )


def ensure_index(force: bool = False) -> dict:
    """Build (or rebuild when the KB / embedding model changed) the vector index. Idempotent."""
    records, report = load_knowledge_records()
    fp = knowledge_fingerprint()
    client = get_client()
    fp_file = _fingerprint_file()
    collection = get_collection()

    up_to_date = (
        not force
        and fp_file.exists()
        and fp_file.read_text().strip() == fp
        and collection.count() == len(records)
    )
    if up_to_date:
        report["indexed"] = collection.count()
        report["status"] = "up_to_date"
        return report

    logger.info(f"[RAG] (Re)building vector index with {len(records)} atomic records")
    try:
        client.delete_collection(settings.CHROMA_COLLECTION)
    except Exception:
        pass
    collection = get_collection()

    texts, metas, ids = [], [], []
    for rec in records:
        text, meta = record_to_chunk(rec)
        texts.append(text)
        metas.append(meta)
        ids.append(rec["id"])
    collection.add(ids=ids, documents=texts, metadatas=metas, embeddings=embed_texts(texts))
    fp_file.write_text(fp)

    report["indexed"] = collection.count()
    report["status"] = "rebuilt"
    logger.info(f"[RAG] Indexed {report['indexed']} records into ChromaDB '{settings.CHROMA_COLLECTION}'")
    return report
