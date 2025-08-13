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


def test_entity_popup_includes_relations(tmp_path, monkeypatch):
    out_dir = tmp_path / 'output'
    ner_dir = tmp_path / 'ner_output'
    out_dir.mkdir()
    ner_dir.mkdir()

    structure_path = out_dir / 'test.json'
    with open(structure_path, 'w', encoding='utf-8') as f:
        json.dump({'text': '<القانون 1, id:1> <الفصل 2, id:2>'}, f, ensure_ascii=False)

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
        json.dump(ner_data, f, ensure_ascii=False)

    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    resp = client.get('/legislation?file=test')
    body = resp.get_data(as_text=True)
    assert '&lt;li&gt;القانون 1 يشير إلى الفصل 2&lt;/li&gt;' in body


def test_internal_ref_shows_article_text(tmp_path, monkeypatch):
    out_dir = tmp_path / 'output'
    ner_dir = tmp_path / 'ner_output'
    out_dir.mkdir()
    ner_dir.mkdir()

    structure = {
        'structure': [
            {'type': 'الفصل', 'number': '4', 'text': 'نص 4'},
            {'type': 'الفصل', 'number': '5', 'text': 'نص 5'},
        ]
    }
    structure_path = out_dir / 'test.json'
    with open(structure_path, 'w', encoding='utf-8') as f:
        json.dump(structure, f, ensure_ascii=False)

    ner_data = {
        'entities': [
            {'id': 1, 'text': 'الفصل 4', 'type': 'ARTICLE'},
            {'id': 2, 'text': 'الفصل 5', 'type': 'ARTICLE'},
            {'id': 3, 'text': 'من 4 إلى 5', 'type': 'INTERNAL_REF'},
        ],
        'relations': [
            {'source_id': 3, 'target_id': 1, 'type': 'refers_to'},
            {'source_id': 3, 'target_id': 2, 'type': 'refers_to'},
        ],
    }
    ner_path = ner_dir / 'test_ner.json'
    with open(ner_path, 'w', encoding='utf-8') as f:
        json.dump(ner_data, f, ensure_ascii=False)

    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    resp = client.get('/legislation?file=test')
    body = resp.get_data(as_text=True)
    assert '&lt;li&gt;الفصل 4: نص 4&lt;/li&gt;' in body
    assert '&lt;li&gt;الفصل 5: نص 5&lt;/li&gt;' in body
