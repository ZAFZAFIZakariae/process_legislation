import io
import sys
import pytest

flask = pytest.importorskip('flask')


def test_process_toggles_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    called = []

    def mock_convert_to_text(input_path, tmp_dir):
        out = tmp_path / 'input.txt'
        out.write_text('data', encoding='utf-8')
        return str(out)

    def mock_run_passes(txt_path, model):
        return {'structure': []}

    # no-op hierarchy functions
    monkeypatch.setattr('app.convert_to_text', mock_convert_to_text)
    monkeypatch.setattr('app.run_passes', mock_run_passes)
    monkeypatch.setattr('app.postprocess_structure', lambda x: x)
    monkeypatch.setattr('app.flatten_articles', lambda x: None)
    monkeypatch.setattr('app.merge_duplicates', lambda x: x)
    monkeypatch.setattr('app.remove_duplicate_articles', lambda x: None)
    monkeypatch.setattr('app.attach_stray_articles', lambda x: None)

    def mock_run_structured_ner(data, model):
        called.append('ner')
        return data, {}, 'ner_text', {}

    monkeypatch.setattr('app.run_structured_ner', mock_run_structured_ner)

    class MockDecisionModule:
        @staticmethod
        def run_structured_decision_parser(data, model):
            called.append('decision')
            return {'ok': True}

    monkeypatch.setitem(sys.modules, 'pipeline.structured_decision_parser', MockDecisionModule)

    import app as app_mod
    client = app_mod.app.test_client()

    def post(data_dict):
        file_data = (io.BytesIO(b'text'), 'test.txt')
        data_dict['file'] = file_data
        client.post('/', data=data_dict, content_type='multipart/form-data')

    # none toggled
    post({'action': 'process'})
    assert called == []
    called.clear()

    # only ner
    post({'action': 'process', 'structured_ner': 'on'})
    assert called == ['ner']
    called.clear()

    # only decision
    post({'action': 'process', 'decision_parser': 'on'})
    assert called == ['decision']
    called.clear()

    # both - decision before ner
    post({'action': 'process', 'structured_ner': 'on', 'decision_parser': 'on'})
    assert called == ['decision', 'ner']
