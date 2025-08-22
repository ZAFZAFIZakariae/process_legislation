import json
import sqlite3
from import_db import init_db, import_json
from crossref import find_entity_docs


def test_import_db_stores_global_id(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(str(db_path))
    data_dir = tmp_path / "out"
    data_dir.mkdir()
    sample = {
        "metadata": {},
        "entities": [
            {
                "id": "E1",
                "type": "LAW",
                "text": "القانون رقم 37.22",
                "normalized": "37.22 القانون",
                "global_id": "LAW_37.22",
            }
        ],
    }
    (data_dir / "doc.json").write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
    import_json(str(db_path), str(data_dir))
    con = sqlite3.connect(str(db_path))
    row = con.execute("SELECT global_id FROM Entities WHERE ent_id='E1'").fetchone()
    con.close()
    assert row[0] == "LAW_37.22"
    docs = find_entity_docs("LAW_37.22", db_path=str(db_path))
    assert docs and docs[0]["document_id"] == 1
