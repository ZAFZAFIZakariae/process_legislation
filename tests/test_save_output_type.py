import io
import json
import sys
import pytest

flask = pytest.importorskip('flask')

def test_save_output_type(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def mock_convert_to_text(input_path, tmp_dir):
        out = tmp_path / 'input.txt'
        out.write_text('data', encoding='utf-8')
        return str(out)

    calls = {'run_passes': 0}

    def mock_run_passes(txt_path, model):
        calls['run_passes'] += 1
        return {'structure': [], 'decision': {'case': 1}}

    monkeypatch.setattr('app.convert_to_text', mock_convert_to_text)
    monkeypatch.setattr('app.run_passes', mock_run_passes)
    monkeypatch.setattr('app.postprocess_structure', lambda x: x)
    monkeypatch.setattr('app.flatten_articles', lambda x: None)
    monkeypatch.setattr('app.merge_duplicates', lambda x: x)
    monkeypatch.setattr('app.remove_duplicate_articles', lambda x: None)
    monkeypatch.setattr('app.attach_stray_articles', lambda x: None)

    import app as app_mod
    client = app_mod.app.test_client()

    def post(data_dict, filename):
        file_data = (io.BytesIO(b'text'), filename)
        data_dict['file'] = file_data
        client.post('/', data=data_dict, content_type='multipart/form-data')

    post({'action': 'process'}, 'leg.txt')
    assert (tmp_path / 'output' / 'leg.json').exists()
    assert calls['run_passes'] == 1

    post({'action': 'process', 'output_type': 'legal'}, 'doc.txt')
    json_path = tmp_path / 'legal_output' / 'doc.json'
    assert json_path.exists()
    saved = json.loads(json_path.read_text(encoding='utf-8'))
    assert saved['text'] == 'data'
    assert saved['structure'] == [{'text': 'data'}]
    assert not (tmp_path / 'output' / 'doc.json').exists()
    assert calls['run_passes'] == 1
