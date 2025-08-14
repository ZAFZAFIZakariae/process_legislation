from __future__ import annotations
import json, os, glob
from typing import Dict, Any
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

PG_DSN = os.environ.get("PG_DSN", "postgresql+psycopg://postgres:postgres@localhost:5432/legislation")
engine = create_engine(PG_DSN, poolclass=QueuePool, pool_size=10, max_overflow=20)

def upsert_document(conn, file_name, short_title, doc_number):
    r = conn.execute(text("""
        INSERT INTO documents(file_name, short_title, doc_number)
        VALUES (:f,:s,:n)
        ON CONFLICT (file_name) DO UPDATE SET short_title=EXCLUDED.short_title, doc_number=EXCLUDED.doc_number
        RETURNING id
    """), dict(f=file_name, s=short_title, n=doc_number)).first()
    return r[0]

def import_json_dir(path: str):
    with engine.begin() as conn:
        for p in glob.glob(os.path.join(path, "*.json")):
            data = json.load(open(p, "r", encoding="utf-8"))
            meta  = data.get("metadata", {})
            short = meta.get("short_title") or meta.get("official_title") or os.path.basename(p)
            docn  = meta.get("document_number") or meta.get("number")
            doc_id = upsert_document(conn, os.path.basename(p), short, docn)

            conn.execute(text("DELETE FROM articles WHERE document_id=:d"), dict(d=doc_id))
            for node in data.get("structure", []):
                if node.get("type") == "ARTICLE":
                    conn.execute(text("""
                        INSERT INTO articles(document_id, number, text)
                        VALUES (:d, :n, :t)
                    """), dict(d=doc_id, n=node.get("number") or node.get("normalized") or node.get("title"), t=node.get("text") or ""))

            ents = data.get("ner_result", {}).get("entities", [])
            conn.execute(text("DELETE FROM entities WHERE document_id=:d"), dict(d=doc_id))
            for e in ents:
                conn.execute(text("""
                    INSERT INTO entities(document_id, type, text, normalized)
                    VALUES (:d, :ty, :tx, :nz)
                """), dict(d=doc_id, ty=e.get("type"), tx=e.get("text"), nz=e.get("normalized") or e.get("text")))

            rels = data.get("ner_result", {}).get("relations", [])
            conn.execute(text("DELETE FROM relations WHERE document_id=:d"), dict(d=doc_id))
            for r in rels:
                conn.execute(text("""
                    INSERT INTO relations(document_id, source_id, target_id, type)
                    VALUES (:d, :s, :t, :ty)
                """), dict(d=doc_id, s=r.get("source_id"), t=r.get("target_id"), ty=r.get("type")))
