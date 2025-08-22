from __future__ import annotations
import os
import sqlite3
from functools import lru_cache
from typing import Optional, List, Dict, Any, Tuple

# Reuse canonical_num logic
try:
    from highlight import canonical_num  # already in your repo
except Exception:
    # Minimal fallback
    def canonical_num(value: str) -> Optional[str]:
        if not isinstance(value, str):
            return None
        s = value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
        import re
        m = re.search(r"\d+(?:[./]+[^\d]*\d+)*", s)
        if not m:
            return None
        digits = re.findall(r"\d+", m.group(0))
        seps = re.findall(r"[./]+", m.group(0))
        out = digits[0]
        for sep, d in zip(seps, digits[1:]):
            out += sep[0] + d
        return out

DEFAULT_DB = os.environ.get("LEGIS_DB_PATH", "data.sqlite")

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_documents_doc_number ON Documents(doc_number);
CREATE INDEX IF NOT EXISTS idx_documents_filename ON Documents(file_name);
CREATE INDEX IF NOT EXISTS idx_articles_docid_number ON Articles(document_id, number);
CREATE INDEX IF NOT EXISTS idx_entities_norm_type ON Entities(normalized, type);
CREATE INDEX IF NOT EXISTS idx_entities_docid ON Entities(document_id);
CREATE INDEX IF NOT EXISTS idx_entities_global_id ON Entities(global_id);
"""

def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con

def ensure_indices(db_path: str = DEFAULT_DB) -> None:
    con = _connect(db_path)
    try:
        con.executescript(INDEX_SQL)
        con.commit()
    finally:
        con.close()

def _fetchone(con: sqlite3.Connection, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    cur = con.execute(sql, params)
    return cur.fetchone()

def _fetchall(con: sqlite3.Connection, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    cur = con.execute(sql, params)
    return cur.fetchall()

def _law_id_by_docnum(con: sqlite3.Connection, law_doc_number: str) -> Optional[int]:
    return_id = _fetchone(con,
        "SELECT id FROM Documents WHERE doc_number = ? LIMIT 1", (law_doc_number,))
    return int(return_id["id"]) if return_id else None

@lru_cache(maxsize=4096)
def get_article_hits(
    article_number_raw: str,
    law_number_raw: Optional[str] = None,
    db_path: str = DEFAULT_DB,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Resolve article text across ALL documents. If a law number is provided, prefer that law.
    Returns a list of hits: [{document_id, file_name, short_title, doc_number, article_number, text}]
    """
    art_num = canonical_num(article_number_raw or "")
    law_num = canonical_num(law_number_raw) if law_number_raw else None
    if not art_num:
        return []

    con = _connect(db_path)
    try:
        hits: List[Dict[str, Any]] = []
        if law_num:
            doc_id = _law_id_by_docnum(con, law_num)
            if doc_id:
                sql = """
                  SELECT a.text AS article_text, a.number AS article_number,
                         d.id AS document_id, d.file_name, d.short_title, d.doc_number
                  FROM Articles a
                  JOIN Documents d ON d.id = a.document_id
                  WHERE a.document_id = ? AND a.number = ?
                  LIMIT ?
                """
                rows = _fetchall(con, sql, (doc_id, art_num, limit))
                hits.extend([
                    {
                        "document_id": r["document_id"],
                        "file_name": r["file_name"],
                        "short_title": r["short_title"],
                        "doc_number": r["doc_number"],
                        "article_number": r["article_number"],
                        "text": r["article_text"],
                    } for r in rows
                ])

        # Fallback: search same article number across all documents
        if len(hits) < limit:
            sql = """
              SELECT a.text AS article_text, a.number AS article_number,
                     d.id AS document_id, d.file_name, d.short_title, d.doc_number
              FROM Articles a
              JOIN Documents d ON d.id = a.document_id
              WHERE a.number = ?
              ORDER BY d.doc_number IS NULL, d.doc_number, d.id
              LIMIT ?
            """
            rows = _fetchall(con, sql, (art_num, limit))
            # Avoid duplicates if law_num branch already added some
            seen: set[Tuple[int, str]] = {(h["document_id"], h["article_number"]) for h in hits}
            for r in rows:
                key = (int(r["document_id"]), r["article_number"])
                if key in seen:
                    continue
                hits.append({
                    "document_id": r["document_id"],
                    "file_name": r["file_name"],
                    "short_title": r["short_title"],
                    "doc_number": r["doc_number"],
                    "article_number": r["article_number"],
                    "text": r["article_text"],
                })
                seen.add(key)
        return hits
    finally:
        con.close()

@lru_cache(maxsize=2048)
def find_entity_docs(
    global_id: str,
    db_path: str = DEFAULT_DB,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Return documents containing an entity with the given ``global_id``."""
    if not global_id:
        return []
    con = _connect(db_path)
    try:
        sql = """
          SELECT DISTINCT d.id AS document_id, d.file_name, d.short_title, d.doc_number
          FROM Entities e
          JOIN Documents d ON d.id = e.document_id
          WHERE e.global_id = ?
          LIMIT ?
        """
        rows = _fetchall(con, sql, (global_id, limit))
        return [
            {
                "document_id": r["document_id"],
                "file_name": r["file_name"],
                "short_title": r["short_title"],
                "doc_number": r["doc_number"],
            }
            for r in rows
        ]
    finally:
        con.close()

@lru_cache(maxsize=2048)
def find_person_docs(
    normalized_name: str,
    db_path: str = DEFAULT_DB,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Return list of documents where a PERSON with given normalized name appears.
    """
    if not normalized_name:
        return []
    con = _connect(db_path)
    try:
        sql = """
          SELECT DISTINCT d.id AS document_id, d.file_name, d.short_title, d.doc_number
          FROM Entities e
          JOIN Documents d ON d.id = e.document_id
          WHERE e.type = 'PERSON' AND e.normalized = ?
          LIMIT ?
        """
        rows = _fetchall(con, sql, (normalized_name, limit))
        return [{
            "document_id": r["document_id"],
            "file_name": r["file_name"],
            "short_title": r["short_title"],
            "doc_number": r["doc_number"],
        } for r in rows]
    finally:
        con.close()

def format_article_popup(hit: Dict[str, Any]) -> str:
    """
    Produce a compact HTML snippet for popups (safe to inject).
    """
    title = hit.get("short_title") or hit.get("file_name") or f"Doc {hit.get('document_id')}"
    num = hit.get("article_number", "")
    text = (hit.get("text") or "").replace("\n", " ").strip()
    # minimal cleanup of angle brackets that clash with your highlighter's id markup
    import re
    text = re.sub(r"<([^,<>]+), id:[^>]+>", r" \1 ", text)
    return f"<b>{title} — الفصل {num}</b><br>{text}"
