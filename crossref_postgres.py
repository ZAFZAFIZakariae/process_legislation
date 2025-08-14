from __future__ import annotations
import os, re
from functools import lru_cache
from typing import Optional, List, Dict, Any
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

PG_DSN = os.environ.get("PG_DSN", "postgresql+psycopg://postgres:postgres@localhost:5432/legislation")
engine = create_engine(PG_DSN, poolclass=QueuePool, pool_size=10, max_overflow=20)

_DIGIT_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
def canonical_num(value: str) -> Optional[str]:
    if not isinstance(value, str):
        return None
    s = value.translate(_DIGIT_TRANS)
    m = re.search(r"\d+(?:[./]+[^\d]*\d+)*", s)
    if not m:
        return None
    digits = re.findall(r"\d+", m.group(0))
    seps   = re.findall(r"[./]+", m.group(0))
    out = digits[0]
    for sep, d in zip(seps, digits[1:]):
        out += sep[0] + d
    return out

@lru_cache(maxsize=8192)
def get_article_hits(article_number_raw: str, law_number_raw: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
    art = canonical_num(article_number_raw or "")
    law = canonical_num(law_number_raw) if law_number_raw else None
    if not art:
        return []
    with engine.connect() as conn:
        hits: List[Dict[str, Any]] = []
        if law:
            rows = conn.execute(text("""
                SELECT a.text, a.number, d.id, d.file_name, d.short_title, d.doc_number
                FROM articles a JOIN documents d ON d.id=a.document_id
                WHERE d.doc_number=:law AND a.number=:art
                LIMIT :lim
            """), dict(law=law, art=art, lim=limit)).mappings().all()
            hits.extend([
                {
                    "document_id": r["id"], "file_name": r["file_name"], "short_title": r["short_title"],
                    "doc_number": r["doc_number"], "article_number": r["number"], "text": r["text"]
                } for r in rows
            ])
        if len(hits) < limit:
            rows = conn.execute(text("""
                SELECT a.text, a.number, d.id, d.file_name, d.short_title, d.doc_number
                FROM articles a JOIN documents d ON d.id=a.document_id
                WHERE a.number=:art
                ORDER BY d.doc_number NULLS LAST, d.id
                LIMIT :lim
            """), dict(art=art, lim=limit)).mappings().all()
            seen = {(h["document_id"], h["article_number"]) for h in hits}
            for r in rows:
                key = (r["id"], r["number"])
                if key in seen:
                    continue
                hits.append({
                    "document_id": r["id"], "file_name": r["file_name"], "short_title": r["short_title"],
                    "doc_number": r["doc_number"], "article_number": r["number"], "text": r["text"]
                })
                if len(hits) >= limit:
                    break
        return hits

@lru_cache(maxsize=4096)
def find_person_docs(normalized_name: str, limit: int = 200) -> List[Dict[str, Any]]:
    if not normalized_name:
        return []
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT d.id, d.file_name, d.short_title, d.doc_number
            FROM entities e JOIN documents d ON d.id=e.document_id
            WHERE e.type='PERSON' AND e.normalized=:n
            LIMIT :lim
        """), dict(n=normalized_name, lim=limit)).mappings().all()
        return [{"document_id": r["id"], "file_name": r["file_name"],
                 "short_title": r["short_title"], "doc_number": r["doc_number"]} for r in rows]

def format_article_popup(hit: Dict[str, Any]) -> str:
    title = hit.get("short_title") or hit.get("file_name") or f"Doc {hit.get('document_id')}"
    num   = hit.get("article_number","")
    text  = (hit.get("text") or "").replace("\n"," ").strip()
    text  = re.sub(r"<([^,<>]+), id:[^>]+>", r" \1 ", text)
    return f"<b>{title} — الفصل {num}</b><br>{text}"
