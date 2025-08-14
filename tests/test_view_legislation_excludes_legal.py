import json
import pytest

flask = pytest.importorskip('flask')


def test_view_legislation_excludes_legal_documents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / 'output'
    legal_dir = tmp_path / 'legal_output'
    out_dir.mkdir()
    legal_dir.mkdir()
    (out_dir / 'law.json').write_text(json.dumps({}), encoding='utf-8')
    (legal_dir / 'case.json').write_text(json.dumps({}), encoding='utf-8')
    import app as app_mod
    client = app_mod.app.test_client()
    res = client.get('/legislation')
    body = res.get_data(as_text=True)
    assert 'law' in body
    assert 'case' not in body
