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

    calls = {'run_passes': 0, 'ner': 0, 'decision': 0}

    def mock_run_passes(txt_path, model):
        calls['run_passes'] += 1
        return {'structure': []}

    def mock_process_legal_document(input_path, uploaded_name, model, tmp_dir):
        return {'structure': [{'text': 'data'}]}, 'data'

    def mock_run_structured_ner(data, model):
        calls['ner'] += 1
        return data, {'entities': []}, 'ner_text', {}

    class MockDecisionModule:
        @staticmethod
        def run_structured_decision_parser(data, model):
            calls['decision'] += 1
            return {'case': 1}

    monkeypatch.setattr('app.convert_to_text', mock_convert_to_text)
    monkeypatch.setattr('app.run_passes', mock_run_passes)
    monkeypatch.setattr('app.process_legal_document', mock_process_legal_document)
    monkeypatch.setattr('app.run_structured_ner', mock_run_structured_ner)
    monkeypatch.setitem(sys.modules, 'pipeline.structured_decision_parser', MockDecisionModule)
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
    assert calls['ner'] == 0
    assert calls['decision'] == 0

    post({'action': 'process', 'output_type': 'legal'}, 'plain.txt')
    plain_json = tmp_path / 'legal_output' / 'plain.json'
    assert plain_json.exists()
    plain_saved = json.loads(plain_json.read_text(encoding='utf-8'))
    assert 'decision' not in plain_saved
    assert 'ner' not in plain_saved
    assert not (tmp_path / 'ner_output' / 'plain_ner.json').exists()
    assert calls['ner'] == 0
    assert calls['decision'] == 0

    post(
        {
            'action': 'process',
            'output_type': 'legal',
            'decision_parser': 'on',
            'structured_ner': 'on',
        },
        'doc.txt',
    )
    json_path = tmp_path / 'legal_output' / 'doc.json'
    assert json_path.exists()
    saved = json.loads(json_path.read_text(encoding='utf-8'))
    assert saved['text'] == 'data'
    assert saved['structure'] == [{'text': 'data'}]
    assert saved['decision'] == {'case': 1}
    assert saved['ner'] == {'entities': []}
    assert (tmp_path / 'ner_output' / 'doc_ner.json').exists()
    assert not (tmp_path / 'output' / 'doc.json').exists()
    assert calls['run_passes'] == 1
    assert calls['ner'] == 1
    assert calls['decision'] == 1
