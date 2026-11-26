"""
Knowledge-base ingestion.

Source of truth: the atomic JSONL records (one verified fact-set per line).
The Markdown file is parsed too and cross-checked against the JSONL; a record that exists only in the
Markdown is ingested (never invented), and any content divergence is logged for review.
"""
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from app.config import settings
from app.utils.logger import logger

_HEADER_RE = re.compile(r"^###\s+(?P<id>[\w.\-]+)\s+[—-]\s+(?P<title>.+?)\s*$")
_FIELD_RE = re.compile(r"^-\s+\*\*(?P<key>[^:*]+):\*\*\s*(?P<val>.*)$")


def load_jsonl(path: Path) -> List[Dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.error(f"[RAG] Invalid JSON on line {n} of {path.name}: {e}")
    return records


def parse_markdown(path: Path) -> Dict[str, Dict]:
    """Parse '### id — title' record blocks from the Markdown knowledge base."""
    records: Dict[str, Dict] = {}
    current = None
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            m = _HEADER_RE.match(line)
            if m:
                current = {"id": m.group("id"), "title": m.group("title").strip()}
                records[current["id"]] = current
                continue
            if current is None:
                continue
            fm = _FIELD_RE.match(line)
            if not fm:
                continue
            key, val = fm.group("key").strip().lower(), fm.group("val").strip()
            if key == "entity":
                current["entity"] = val
            elif key == "type":
                current["entity_type"] = val
            elif key == "category":
                current["category"] = val
            elif key == "content":
                current["content"] = val
            elif key == "source":
                current["source"] = val
            elif key == "structured facts":
                try:
                    current["facts"] = json.loads(val.strip("`"))
                except Exception:
                    pass
    return {k: v for k, v in records.items() if v.get("content")}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("&amp;", "&")).strip()


def load_knowledge_records() -> Tuple[List[Dict], Dict]:
    """Return (records, report). JSONL is authoritative; Markdown-only records are appended."""
    kb_dir = settings.KNOWLEDGE_BASE_DIR
    jsonl_path = kb_dir / settings.KB_JSONL_FILE
    md_path = kb_dir / settings.KB_MARKDOWN_FILE
    if not jsonl_path.exists():
        raise FileNotFoundError(f"Knowledge base JSONL not found: {jsonl_path}")

    jsonl_records = load_jsonl(jsonl_path)
    by_id = {r["id"]: r for r in jsonl_records}
    report = {"jsonl_records": len(jsonl_records), "markdown_records": 0,
              "markdown_only": [], "content_mismatch": []}

    if md_path.exists():
        md_records = parse_markdown(md_path)
        report["markdown_records"] = len(md_records)
        for rid, mrec in md_records.items():
            if rid not in by_id:
                mrec.setdefault("source_type", "markdown_only")
                jsonl_records.append(mrec)
                by_id[rid] = mrec
                report["markdown_only"].append(rid)
            elif _norm(by_id[rid].get("content")) != _norm(mrec.get("content")):
                report["content_mismatch"].append(rid)
        if report["markdown_only"]:
            logger.warning(f"[RAG] Records only in Markdown (ingested): {report['markdown_only']}")
        if report["content_mismatch"]:
            logger.warning(f"[RAG] JSONL/Markdown content differs for: {report['content_mismatch']} (JSONL used)")
    else:
        logger.warning(f"[RAG] Markdown knowledge base not found at {md_path}; using JSONL only")

    return jsonl_records, report


def record_to_chunk(record: Dict) -> Tuple[str, Dict]:
    """
    One atomic record = one chunk. Embedding text is the title + content (content is primary);
    every other field is preserved as metadata so answers stay traceable to their source.
    """
    text = f"{record.get('title', '')}. {record['content']}".strip()
    meta = {
        "id": record["id"],
        "entity": record.get("entity", ""),
        "entity_type": record.get("entity_type", ""),
        "category": record.get("category", ""),
        "title": record.get("title", ""),
        "source": record.get("source", ""),
        "source_type": record.get("source_type", ""),
        "qualification": record.get("qualification") or record.get("verification_note") or "",
        "facts_json": json.dumps(record.get("facts") or {}, ensure_ascii=False),
        "content": record["content"],
    }
    return text, meta


def knowledge_fingerprint() -> str:
    h = hashlib.sha256()
    for name in (settings.KB_JSONL_FILE, settings.KB_MARKDOWN_FILE):
        p = settings.KNOWLEDGE_BASE_DIR / name
        if p.exists():
            h.update(p.read_bytes())
    h.update(settings.EMBEDDING_MODEL.encode())
    return h.hexdigest()
