import json
import pytest

flask = pytest.importorskip('flask')


def test_view_legal_documents_lists_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / 'legal_output'
    out.mkdir()
    (out / 'case.json').write_text(json.dumps({'a': 1}), encoding='utf-8')

    import app as app_mod
    client = app_mod.app.test_client()

    res = client.get('/legal_documents')
    assert b'case' in res.data

    res = client.get('/legal_documents?file=case')
    body = res.get_data(as_text=True)
    assert 'json-tree' in body
    assert 'Edit annotations' in body
    assert '"a":1' in body
