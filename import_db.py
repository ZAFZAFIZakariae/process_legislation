import os
import json
import argparse
import sqlite3

from highlight import canonical_num

try:
    from interface import load_law_articles
except Exception:
    try:
        from app import load_law_articles
    except Exception:
        load_law_articles = None  # type: ignore


OUTPUT_DIR = "output"


def init_db(path: str) -> None:
    """Create or overwrite the SQLite database at *path*."""
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(
        """
        DROP TABLE IF EXISTS Documents;
        DROP TABLE IF EXISTS Articles;
        DROP TABLE IF EXISTS Entities;
        DROP TABLE IF EXISTS Relations;

        CREATE TABLE Documents(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT,
            doc_number TEXT,
            short_title TEXT,
            official_title TEXT,
            doc_type TEXT
        );

        CREATE TABLE Articles(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            number TEXT,
            text TEXT,
            FOREIGN KEY(document_id) REFERENCES Documents(id)
        );

        CREATE TABLE Entities(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            ent_id TEXT,
            type TEXT,
            text TEXT,
            start_char INTEGER,
            end_char INTEGER,
            normalized TEXT,
            canonical_num TEXT,
            global_id TEXT,
            FOREIGN KEY(document_id) REFERENCES Documents(id)
        );

        CREATE TABLE Relations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            relation_id TEXT,
            type TEXT,
            source_id TEXT,
            target_id TEXT,
            FOREIGN KEY(document_id) REFERENCES Documents(id)
        );
        """
    )
    con.commit()
    con.close()
    print(f"[+] Initialised database {path}")


def _collect_articles(nodes: list, cur: sqlite3.Cursor, document_id: int) -> None:
    for node in nodes:
        if node.get("type") in {"الفصل", "مادة"}:
            num = canonical_num(node.get("number"))
            txt = node.get("text")
            if num and txt:
                cur.execute(
                    "INSERT INTO Articles(document_id, number, text) VALUES (?,?,?)",
                    (document_id, num, txt),
                )
        if node.get("children"):
            _collect_articles(node["children"], cur, document_id)


def import_json(db_path: str, dir_path: str = OUTPUT_DIR) -> None:
    """Import all JSON files under *dir_path* into *db_path*."""
    if load_law_articles:
        load_law_articles(dir_path)  # warm cache / for side effects if any
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    for name in os.listdir(dir_path):
        if not name.endswith(".json"):
            continue
        path = os.path.join(dir_path, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"Failed to load {path}: {exc}")
            continue
        meta = data.get("metadata", {})
        doc_num = canonical_num(meta.get("document_number"))
        cur.execute(
            "INSERT INTO Documents(file_name, doc_number, short_title, official_title, doc_type) VALUES (?,?,?,?,?)",
            (
                name,
                doc_num,
                meta.get("short_title"),
                meta.get("official_title"),
                meta.get("document_type"),
            ),
        )
        doc_id = cur.lastrowid

        if isinstance(data.get("structure"), list):
            _collect_articles(data["structure"], cur, doc_id)

        for ent in data.get("entities", []):
            cur.execute(
                "INSERT INTO Entities(document_id, ent_id, type, text, start_char, end_char, normalized, canonical_num, global_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    doc_id,
                    ent.get("id"),
                    ent.get("type"),
                    ent.get("text"),
                    ent.get("start_char"),
                    ent.get("end_char"),
                    ent.get("normalized"),
                    canonical_num(ent.get("normalized") or ent.get("text")),
                    ent.get("global_id"),
                ),
            )
        for rel in data.get("relations", []):
            cur.execute(
                "INSERT INTO Relations(document_id, relation_id, type, source_id, target_id) VALUES (?,?,?,?,?)",
                (
                    doc_id,
                    rel.get("relation_id"),
                    rel.get("type"),
                    rel.get("source_id"),
                    rel.get("target_id"),
                ),
            )
    cur.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_documents_doc_number ON Documents(doc_number);
        CREATE INDEX IF NOT EXISTS idx_documents_filename ON Documents(file_name);
        CREATE INDEX IF NOT EXISTS idx_articles_docid_number ON Articles(document_id, number);
        CREATE INDEX IF NOT EXISTS idx_entities_norm_type ON Entities(normalized, type);
        CREATE INDEX IF NOT EXISTS idx_entities_docid ON Entities(document_id);
        CREATE INDEX IF NOT EXISTS idx_entities_global_id ON Entities(global_id);
        """
    )
    con.commit()
    con.close()
    print(f"[+] Imported JSON files from {dir_path} into {db_path}")


def export_graph(db_path: str, out_path: str) -> None:
    """Export all relations as a GraphML file."""
    try:
        import networkx as nx  # type: ignore
    except Exception:
        print("networkx is required for graph export")
        return
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    ent_map: dict[tuple[int, str], int] = {}
    G = nx.DiGraph()
    for row in cur.execute(
        "SELECT id, document_id, ent_id, type, text, normalized FROM Entities"
    ):
        rid, doc_id, ent_id, typ, txt, norm = row
        ent_map[(doc_id, str(ent_id))] = rid
        G.add_node(rid, document=doc_id, type=typ, text=txt, normalized=norm)
    for row in cur.execute(
        "SELECT document_id, relation_id, type, source_id, target_id FROM Relations"
    ):
        doc_id, rel_id, typ, src, tgt = row
        s = ent_map.get((doc_id, str(src)))
        t = ent_map.get((doc_id, str(tgt)))
        if s and t:
            G.add_edge(s, t, key=rel_id, type=typ, document=doc_id)
    nx.write_graphml(G, out_path)
    print(f"[+] Wrote graph to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import extraction results into SQLite")
    parser.add_argument("--init-db", metavar="PATH", help="Create/overwrite SQLite DB")
    parser.add_argument("--import", dest="import_db", metavar="PATH", help="Import JSON files into DB")
    parser.add_argument("--export-graph", metavar="PATH", help="Export relation graph as GraphML")
    parser.add_argument("--db", metavar="PATH", help="Database path for import/export", default="data.sqlite")

    args = parser.parse_args()

    if args.init_db:
        init_db(args.init_db)
    if args.import_db:
        import_json(args.db, args.import_db)
    if args.export_graph:
        export_graph(args.db, args.export_graph)


if __name__ == "__main__":
    main()
