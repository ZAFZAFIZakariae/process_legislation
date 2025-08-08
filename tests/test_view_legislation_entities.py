import json
import pytest

flask = pytest.importorskip('flask')
from app import app


def test_view_legislation_includes_entities(tmp_path, monkeypatch):
    out_dir = tmp_path / 'output'
    out_dir.mkdir()

    structure_path = out_dir / 'test.json'
    with open(structure_path, 'w', encoding='utf-8') as f:
        json.dump({}, f)

    ner_data = {
        'entities': [
            {'id': 1, 'text': 'القانون 1', 'type': 'LAW'},
            {'id': 2, 'text': 'الفصل 2', 'type': 'ARTICLE'},
        ],
        'relations': [
            {'source_id': 1, 'target_id': 2, 'type': 'refers_to'},
        ],
    }
    ner_path = out_dir / 'test_ner.json'
    with open(ner_path, 'w', encoding='utf-8') as f:
        json.dump(ner_data, f)

    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    resp = client.get('/legislation?file=test.json')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'القانون 1 يشير إلى الفصل 2' in body
