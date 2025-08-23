"""Helpers for resolving cross‑references stored in PostgreSQL.

These utilities mirror the functions in :mod:`crossref` but operate on a
PostgreSQL database loaded via ``db/postgres_import.py``.  They are used by the
Flask web app when a ``PG_DSN`` is configured and can also be imported directly
for programmatic access.
"""

from __future__ import annotations
import os, re
from functools import lru_cache
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

PG_DSN = os.environ.get(
    "PG_DSN", "postgresql+psycopg:///legislation"
)
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
def get_article_hits(
    article_number_raw: str,
    law_number_raw: Optional[str] = None,
    law_names_raw: Optional[Tuple[str, ...]] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    art = canonical_num(article_number_raw or "")
    law = canonical_num(law_number_raw) if law_number_raw else None
    law_names = [n.strip().lower() for n in (law_names_raw or []) if n]
    if not art:
        return []
    with engine.connect() as conn:
        # 1) Try an explicit law number if supplied
        if law:
            rows = conn.execute(
                text(
                    """
                SELECT a.text, a.number, d.id, d.file_name, d.short_title, d.doc_number, d.law_number
                FROM articles a JOIN documents d ON d.id=a.document_id
                WHERE (d.doc_number=:law OR d.law_number=:law) AND a.number=:art
                LIMIT :lim
            """
                ),
                dict(law=law, art=art, lim=limit),
            ).mappings().all()
            if rows:
                return [
                    {
                        "document_id": r["id"],
                        "file_name": r["file_name"],
                        "short_title": r["short_title"],
                        "doc_number": r["doc_number"],
                        "article_number": r["number"],
                        "text": r["text"],
                    }
                    for r in rows
                ]

            # As a fallback for legacy rows without ``law_number`` populated,
            # match the law digits inside titles or file names.
            law_like = f"%{law}%"
            rows = conn.execute(
                text(
                    """
                SELECT a.text, a.number, d.id, d.file_name, d.short_title, d.doc_number, d.law_number
                FROM articles a JOIN documents d ON d.id=a.document_id
                WHERE a.number=:art AND (d.short_title LIKE :law_like OR d.file_name LIKE :law_like)
                ORDER BY d.doc_number NULLS LAST, d.id
                LIMIT :lim
            """
                ),
                dict(art=art, law_like=law_like, lim=limit),
            ).mappings().all()
            if rows:
                return [
                    {
                        "document_id": r["id"],
                        "file_name": r["file_name"],
                        "short_title": r["short_title"],
                        "doc_number": r["doc_number"],
                        "article_number": r["number"],
                        "text": r["text"],
                    }
                    for r in rows
                ]

        # 2) Match against law names if provided
        if law_names:
            conds = []
            params: Dict[str, Any] = {"art": art, "lim": limit}
            for i, name in enumerate(law_names):
                key = f"p{i}"
                params[key] = f"%{name}%"
                conds.append(f"LOWER(d.short_title) LIKE :{key} OR LOWER(d.file_name) LIKE :{key}")
            where_clause = " OR ".join(conds)
            sql = f"""
                SELECT a.text, a.number, d.id, d.file_name, d.short_title, d.doc_number
                FROM articles a JOIN documents d ON d.id=a.document_id
                WHERE a.number=:art AND ({where_clause})
                ORDER BY d.doc_number NULLS LAST, d.id
                LIMIT :lim
            """
            rows = conn.execute(text(sql), params).mappings().all()
            if rows:
                return [
                    {
                        "document_id": r["id"],
                        "file_name": r["file_name"],
                        "short_title": r["short_title"],
                        "doc_number": r["doc_number"],
                        "article_number": r["number"],
                        "text": r["text"],
                    }
                    for r in rows
                ]

        # 3) Fallback: any article with matching number
        rows = conn.execute(
            text(
                """
            SELECT a.text, a.number, d.id, d.file_name, d.short_title, d.doc_number
            FROM articles a JOIN documents d ON d.id=a.document_id
            WHERE a.number=:art
            ORDER BY d.doc_number NULLS LAST, d.id
            LIMIT :lim
        """
            ),
            dict(art=art, lim=limit),
        ).mappings().all()
        return [
            {
                "document_id": r["id"],
                "file_name": r["file_name"],
                "short_title": r["short_title"],
                "doc_number": r["doc_number"],
                "article_number": r["number"],
                "text": r["text"],
            }
            for r in rows
        ]

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

@lru_cache(maxsize=4096)
def find_entity_docs(global_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Return documents containing an entity with the given ``global_id``."""
    if not global_id:
        return []
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT d.id, d.file_name, d.short_title, d.doc_number
            FROM entities e JOIN documents d ON d.id=e.document_id
            WHERE e.global_id=:gid
            LIMIT :lim
        """), dict(gid=global_id, lim=limit)).mappings().all()
        return [
            {
                "document_id": r["id"],
                "file_name": r["file_name"],
                "short_title": r["short_title"],
                "doc_number": r["doc_number"],
            }
            for r in rows
        ]

def format_article_popup(hit: Dict[str, Any]) -> str:
    title = hit.get("short_title") or hit.get("file_name") or f"Doc {hit.get('document_id')}"
    num   = hit.get("article_number","")
    text  = (hit.get("text") or "").replace("\n"," ").strip()
    text  = re.sub(r"<([^,<>]+), id:[^>]+>", r" \1 ", text)
    return f"<b>{title} — الفصل {num}</b><br>{text}"
