import json
import pytest

flask = pytest.importorskip('flask')


def test_view_legal_documents_lists_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / 'legal_output'
    ner_dir = tmp_path / 'ner_output'
    out.mkdir()
    ner_dir.mkdir()
    (out / 'case.json').write_text(
        json.dumps({'structure': [], 'text': 'hello world'}), encoding='utf-8'
    )
    ner_data = {
        'entities': [
            {'id': 1, 'text': 'hello', 'start_char': 0, 'end_char': 5, 'type': 'LAW'},
        ],
        'relations': [],
    }
    (ner_dir / 'case_ner.json').write_text(json.dumps(ner_data), encoding='utf-8')

    import app as app_mod
    client = app_mod.app.test_client()

    res = client.get('/legal_documents')
    assert b'case' in res.data

    res = client.get('/legal_documents?file=case')
    body = res.get_data(as_text=True)
    assert 'json-tree' in body
    assert 'Edit annotations' in body
    assert 'hello world' in body
    assert 'ent-1' in body
