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
        json.dumps({'structure': [{'text': '<hello, id:1> world'}], 'text': 'hello world'}),
        encoding='utf-8',
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
    assert 'document-text' in body
    assert 'Edit annotations' in body
    assert 'id:1' in body
    assert 'class="entity-link"' not in body


def test_law_entity_with_article_popup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / 'legal_output'
    ner_dir = tmp_path / 'ner_output'
    out.mkdir()
    ner_dir.mkdir()
    structure = {
        'structure': [{'text': '<المادة 1 من القانون 30.09, id:1>'}],
        'text': 'المادة 1 من القانون 30.09',
    }
    (out / 'case.json').write_text(
        json.dumps(structure, ensure_ascii=False), encoding='utf-8'
    )
    ner_data = {
        'entities': [
            {
                'id': 1,
                'type': 'LAW',
                'text': 'المادة 1 من القانون 30.09',
                'normalized': 'المادة 1 القانون 30.09',
            }
        ],
        'relations': [],
    }
    (ner_dir / 'case_ner.json').write_text(
        json.dumps(ner_data, ensure_ascii=False), encoding='utf-8'
    )
    import app as app_mod
    monkeypatch.setattr(
        app_mod, '_resolve_article_text', lambda num, law_nums, law_names: f'snippet {num}'
    )
    client = app_mod.app.test_client()
    res = client.get('/legal_documents?file=case')
    body = res.get_data(as_text=True)
    assert '"articles": ["snippet 1"]' in body
