"""Semantic retriever with entity-aware metadata filtering and grounding thresholds."""
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.config import settings
from app.rag.embeddings import embed_query
from app.rag.vector_store import get_collection
from app.utils.logger import logger

# Query keywords -> KB `entity` values (used for metadata filtering; the embedding search still runs unfiltered too)
ENTITY_KEYWORDS = {
    "Fortivex CRM": [r"\bcrm\b", r"admission", r"student lifecycle", r"counsell?or", r"enquir"],
    "Fortivex Attendance Management System (FAMS)": [r"\bfams\b", r"attendance", r"payroll", r"\bleave\b", r"roster"],
    "Empowers Academy": [r"empowers?", r"academy"],
    "Medivex AI": [r"medivex", r"clinical", r"medical coding", r"bioinformatics", r"biostatistics"],
    "FORTIVEX AI PRIVATE LIMITED": [r"fortivex ai\b", r"\bcompany\b", r"\bceo\b", r"director", r"\boffice\b", r"headquarter", r"\bdubai\b", r"bengaluru|bangalore"],
}
POLICY_TYPE = "agent_policy"


@dataclass
class RetrievedDoc:
    id: str
    title: str
    content: str
    entity: str
    entity_type: str
    category: str
    source: str
    qualification: str = ""
    facts: Dict = field(default_factory=dict)
    similarity: float = 0.0

    def to_context_line(self) -> str:
        note = f" [Note: {self.qualification}]" if self.qualification else ""
        return f"({self.id} | {self.entity}) {self.title}: {self.content}{note}"

    def trace(self) -> Dict:
        return {"id": self.id, "entity": self.entity, "category": self.category,
                "source": self.source, "similarity": round(self.similarity, 3)}


def detect_entities(query: str) -> List[str]:
    q = query.lower()
    return [ent for ent, pats in ENTITY_KEYWORDS.items() if any(re.search(p, q) for p in pats)]


def _to_docs(res: Dict) -> List[RetrievedDoc]:
    docs = []
    if not res.get("ids") or not res["ids"][0]:
        return docs
    for i, rid in enumerate(res["ids"][0]):
        m = res["metadatas"][0][i]
        dist = res["distances"][0][i]
        try:
            facts = json.loads(m.get("facts_json") or "{}")
        except Exception:
            facts = {}
        docs.append(RetrievedDoc(
            id=rid, title=m.get("title", ""), content=m.get("content", ""), entity=m.get("entity", ""),
            entity_type=m.get("entity_type", ""), category=m.get("category", ""), source=m.get("source", ""),
            qualification=m.get("qualification", ""), facts=facts,
            similarity=1.0 - float(dist),  # cosine distance -> similarity
        ))
    return docs


def retrieve(query: str, context_hint: str = "", top_k: Optional[int] = None,
             min_similarity: Optional[float] = None) -> List[RetrievedDoc]:
    """
    Retrieve the most relevant verified records. Agent-policy records are excluded (they are instructions,
    injected separately into the prompt). Returns [] when nothing is similar enough -> caller must not answer
    from imagination.
    """
    top_k = top_k or settings.RAG_TOP_K
    min_similarity = settings.RAG_MIN_SIMILARITY if min_similarity is None else min_similarity
    query = (query or "").strip()
    if not query:
        return []
    # Short follow-ups ("what about pricing?") are enriched with the current topic for better recall.
    search_text = f"{context_hint}. {query}" if context_hint and len(query.split()) <= 6 else query

    col = get_collection()
    qvec = embed_query(search_text)
    not_policy = {"entity_type": {"$ne": POLICY_TYPE}}

    merged: Dict[str, RetrievedDoc] = {}

    def run(where):
        res = col.query(query_embeddings=[qvec], n_results=top_k, where=where,
                        include=["metadatas", "distances"])
        for d in _to_docs(res):
            if d.id not in merged or d.similarity > merged[d.id].similarity:
                merged[d.id] = d

    run(not_policy)
    entities = detect_entities(search_text)
    if entities:
        run({"$and": [not_policy, {"entity": {"$in": entities}}]})

    docs = sorted(merged.values(), key=lambda d: d.similarity, reverse=True)
    docs = [d for d in docs if d.similarity >= min_similarity][:top_k]
    logger.info(f"[RAG] q='{query[:60]}' entities={entities} -> "
                f"{[(d.id, round(d.similarity, 2)) for d in docs]}")
    return docs


def get_policies() -> List[str]:
    """Static agent-policy records (answering, privacy, commercial, tool-execution rules)."""
    col = get_collection()
    res = col.get(where={"entity_type": POLICY_TYPE}, include=["metadatas"])
    return [f"{m['title']}: {m['content']}" for m in res.get("metadatas", [])]
