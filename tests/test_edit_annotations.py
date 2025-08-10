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
