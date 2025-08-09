import json
import pytest

flask = pytest.importorskip('flask')
from app import app


def test_view_legislation_includes_entities(tmp_path, monkeypatch):
    out_dir = tmp_path / 'output'
    ner_dir = tmp_path / 'ner_output'
    out_dir.mkdir()
    ner_dir.mkdir()

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
    ner_path = ner_dir / 'test_ner.json'
    with open(ner_path, 'w', encoding='utf-8') as f:
        json.dump(ner_data, f)

    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    resp = client.get('/legislation?file=test')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'القانون 1 يشير إلى الفصل 2' in body


def test_entity_links_only_when_related(tmp_path, monkeypatch):
    out_dir = tmp_path / 'output'
    ner_dir = tmp_path / 'ner_output'
    out_dir.mkdir()
    ner_dir.mkdir()

    structure_path = out_dir / 'test.json'
    with open(structure_path, 'w', encoding='utf-8') as f:
        json.dump({'text': '<القانون 1, id:1> <الفصل 2, id:2> <شخص ما, id:3>'}, f, ensure_ascii=False)

    ner_data = {
        'entities': [
            {'id': 1, 'text': 'القانون 1', 'type': 'LAW'},
            {'id': 2, 'text': 'الفصل 2', 'type': 'ARTICLE'},
            {'id': 3, 'text': 'شخص ما', 'type': 'PERSON'},
        ],
        'relations': [
            {'source_id': 1, 'target_id': 2, 'type': 'refers_to'},
        ],
    }
    ner_path = ner_dir / 'test_ner.json'
    with open(ner_path, 'w', encoding='utf-8') as f:
        json.dump(ner_data, f, ensure_ascii=False)

    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    resp = client.get('/legislation?file=test')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'href="#entity-1"' in body
    assert 'href="#entity-2"' in body
    assert 'href="#entity-3"' not in body
