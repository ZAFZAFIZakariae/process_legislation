import io
import os
import json
import pytest

flask = pytest.importorskip('flask')
from app import app


def test_extract_structure_saves_raw_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def fake_convert_to_text(input_path, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        out = os.path.join(output_dir, 'tmp.txt')
        with open(out, 'w', encoding='utf-8') as f:
            f.write('hello world')
        return out

    def fake_run_passes(txt_path, model):
        return {'structure': []}

    def fake_run_structured_ner(result, model):
        return result, {'entities': []}, 'hello world', {'entities': []}

    monkeypatch.setattr('app.convert_to_text', fake_convert_to_text)
    monkeypatch.setattr('app.run_passes', fake_run_passes)
    monkeypatch.setattr('app.run_structured_ner', fake_run_structured_ner)
    monkeypatch.setattr('app.postprocess_structure', lambda x: x)
    monkeypatch.setattr('app.flatten_articles', lambda x: None)
    monkeypatch.setattr('app.merge_duplicates', lambda x: x)
    monkeypatch.setattr('app.remove_duplicate_articles', lambda x: None)
    monkeypatch.setattr('app.attach_stray_articles', lambda x: None)
    monkeypatch.setattr('app.render_ner_html', lambda text, result: '')

    client = app.test_client()
    data = {'file': (io.BytesIO(b'PDF'), 'test.pdf')}
    resp = client.post('/structure', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    saved = tmp_path / 'data_txt' / 'test.txt'
    assert saved.exists()
    assert saved.read_text(encoding='utf-8') == 'hello world'
