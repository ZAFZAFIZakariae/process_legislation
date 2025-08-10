import json
import pytest

flask = pytest.importorskip('flask')
from app import app


def _setup_dirs(tmp_path):
    out_dir = tmp_path / 'output'
    ner_dir = tmp_path / 'ner_output'
    txt_dir = tmp_path / 'data_txt'
    out_dir.mkdir()
    ner_dir.mkdir()
    txt_dir.mkdir()

    with open(out_dir / 'test.json', 'w', encoding='utf-8') as f:
        json.dump({}, f)
    with open(ner_dir / 'test_ner.json', 'w', encoding='utf-8') as f:
        json.dump({'entities': [], 'relations': []}, f)
    with open(txt_dir / 'test.txt', 'w', encoding='utf-8') as f:
        f.write('abcdef')

    return out_dir, ner_dir, txt_dir


def test_edit_legislation_save(tmp_path, monkeypatch):
    _, ner_dir, _ = _setup_dirs(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = app.test_client()

    resp = client.get('/legislation/edit?file=test')
    assert resp.status_code == 200
    assert '<textarea' in resp.get_data(as_text=True)

    content = '[[ENT id=1 type=LAW]]abc[[/ENT]]def'
    resp = client.post('/legislation/edit?file=test', data={'action': 'save', 'content': content})
    assert resp.status_code == 302

    with open(ner_dir / 'test_ner.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data['entities'][0]['type'] == 'LAW'
    assert data['entities'][0]['start_char'] == 0


def test_edit_legislation_add_delete(tmp_path, monkeypatch):
    _, ner_dir, _ = _setup_dirs(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = app.test_client()

    resp = client.post(
        '/legislation/edit?file=test',
        data={'action': 'add', 'start': '0', 'end': '3', 'type': 'LAW'},
    )
    assert resp.status_code == 200
    with open(ner_dir / 'test_ner.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data['entities'][0]['text'] == 'abc'
    eid = data['entities'][0]['id']

    resp = client.post('/legislation/edit?file=test', data={'action': 'delete', 'id': str(eid)})
    assert resp.status_code == 200
    with open(ner_dir / 'test_ner.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data['entities'] == []
