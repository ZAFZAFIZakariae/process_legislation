import json
import pytest

flask = pytest.importorskip('flask')
from app import app

def test_edit_legislation_handles_alphanumeric_ids(tmp_path, monkeypatch):
    out_dir = tmp_path / 'output'
    ner_dir = tmp_path / 'ner_output'
    txt_dir = tmp_path / 'data_txt'
    out_dir.mkdir()
    ner_dir.mkdir()
    txt_dir.mkdir()

    # Structure contains an entity marker with alphanumeric ID
    structure_path = out_dir / 'test.json'
    with open(structure_path, 'w', encoding='utf-8') as f:
        json.dump({'text': '<القانون 1, id:LAW_1>'}, f, ensure_ascii=False)

    # Raw text and NER data for the editor
    with open(txt_dir / 'test.txt', 'w', encoding='utf-8') as f:
        f.write('القانون 1')
    ner_data = {'entities': [{'id': 'LAW_1', 'text': 'القانون 1', 'type': 'LAW'}], 'relations': []}
    with open(ner_dir / 'test_ner.json', 'w', encoding='utf-8') as f:
        json.dump(ner_data, f, ensure_ascii=False)

    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    resp = client.get('/legislation/edit?file=test')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'class="entity-mark"' in body
    assert 'data-id="LAW_1"' in body


def test_post_update_persists_changes(tmp_path, monkeypatch):
    out_dir = tmp_path / 'output'
    ner_dir = tmp_path / 'ner_output'
    txt_dir = tmp_path / 'data_txt'
    out_dir.mkdir()
    ner_dir.mkdir()
    txt_dir.mkdir()

    structure_path = out_dir / 'test.json'
    with open(structure_path, 'w', encoding='utf-8') as f:
        json.dump({'text': '<القانون 1, id:LAW_1>'}, f, ensure_ascii=False)

    with open(txt_dir / 'test.txt', 'w', encoding='utf-8') as f:
        f.write('القانون 1')
    ner_path = ner_dir / 'test_ner.json'
    ner_data = {
        'entities': [{'id': 'LAW_1', 'text': 'القانون 1', 'type': 'LAW'}],
        'relations': []
    }
    with open(ner_path, 'w', encoding='utf-8') as f:
        json.dump(ner_data, f, ensure_ascii=False)

    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    resp = client.post(
        '/legislation/edit?file=test',
        data={'action': 'update', 'id': 'LAW_1', 'type': 'NEW'}
    )
    assert resp.status_code == 200
    with open(ner_path, 'r', encoding='utf-8') as f:
        saved = json.load(f)
    assert saved['entities'][0]['type'] == 'NEW'


def test_add_entity_updates_structure_json(tmp_path, monkeypatch):
    out_dir = tmp_path / 'output'
    ner_dir = tmp_path / 'ner_output'
    txt_dir = tmp_path / 'data_txt'
    out_dir.mkdir()
    ner_dir.mkdir()
    txt_dir.mkdir()

    structure_path = out_dir / 'test.json'
    with open(structure_path, 'w', encoding='utf-8') as f:
        json.dump({'text': 'القانون'}, f, ensure_ascii=False)

    with open(txt_dir / 'test.txt', 'w', encoding='utf-8') as f:
        f.write('القانون')
    ner_path = ner_dir / 'test_ner.json'
    with open(ner_path, 'w', encoding='utf-8') as f:
        json.dump({'entities': [], 'relations': []}, f, ensure_ascii=False)

    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    resp = client.post(
        '/legislation/edit?file=test',
        data={'action': 'add', 'start': 0, 'end': 7, 'type': 'LAW'}
    )
    assert resp.status_code == 200
    with open(structure_path, 'r', encoding='utf-8') as f:
        struct = json.load(f)
    assert struct['text'] == '<القانون, id:1>'
    with open(ner_path, 'r', encoding='utf-8') as f:
        ner_saved = json.load(f)
    assert ner_saved['entities'][0]['id'] == 1


def test_add_entity_with_text_corrects_offset(tmp_path, monkeypatch):
    out_dir = tmp_path / 'output'
    ner_dir = tmp_path / 'ner_output'
    txt_dir = tmp_path / 'data_txt'
    out_dir.mkdir()
    ner_dir.mkdir()
    txt_dir.mkdir()

    content = 'هيرنا ا شيء الدستور نهاية'
    structure_path = out_dir / 'test.json'
    with open(structure_path, 'w', encoding='utf-8') as f:
        json.dump({'text': content}, f, ensure_ascii=False)

    with open(txt_dir / 'test.txt', 'w', encoding='utf-8') as f:
        f.write(content)

    ner_path = ner_dir / 'test_ner.json'
    with open(ner_path, 'w', encoding='utf-8') as f:
        json.dump({'entities': [], 'relations': []}, f, ensure_ascii=False)

    monkeypatch.chdir(tmp_path)
    client = app.test_client()
    resp = client.post(
        '/legislation/edit?file=test',
        data={'action': 'add', 'start': 0, 'end': 7, 'type': 'LAW', 'text': 'الدستور'}
    )
    assert resp.status_code == 200

    with open(ner_path, 'r', encoding='utf-8') as f:
        ner_saved = json.load(f)
    assert ner_saved['entities'][0]['text'] == 'الدستور'

    with open(structure_path, 'r', encoding='utf-8') as f:
        struct = json.load(f)
    assert struct['text'] == 'هيرنا ا شيء <الدستور, id:1> نهاية'
