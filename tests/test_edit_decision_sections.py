import json
import pytest

flask = pytest.importorskip('flask')
from app import app


def _setup_dirs(tmp_path):
    legal_dir = tmp_path / 'legal_output'
    ner_dir = tmp_path / 'ner_output'
    txt_dir = tmp_path / 'data_txt'
    legal_dir.mkdir()
    ner_dir.mkdir()
    txt_dir.mkdir()
    with open(legal_dir / 'test.json', 'w', encoding='utf-8') as f:
        json.dump({
            'facts': [],
            'arguments': [],
            'legal_reasons': [],
            'decision': []
        }, f)
    with open(ner_dir / 'test_ner.json', 'w', encoding='utf-8') as f:
        json.dump({'entities': [], 'relations': []}, f)
    with open(txt_dir / 'test.txt', 'w', encoding='utf-8') as f:
        f.write('abc')
    return legal_dir


def test_add_delete_sections(tmp_path, monkeypatch):
    legal_dir = _setup_dirs(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = app.test_client()

    resp = client.post('/decision/edit?file=test', data={
        'action': 'add_struct',
        'category': 'facts',
        'text': 'fact1'
    })
    assert resp.status_code == 200
    with open(legal_dir / 'test.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data['facts'] == ['fact1']

    resp = client.post('/decision/edit?file=test', data={
        'action': 'delete_struct',
        'category': 'facts',
        'index': '0'
    })
    assert resp.status_code == 200
    with open(legal_dir / 'test.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data['facts'] == []
