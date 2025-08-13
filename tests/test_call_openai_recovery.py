import sys, os
sys.path.insert(0, os.getcwd())
import ner
from types import SimpleNamespace


def test_call_openai_extracts_json(monkeypatch):
    fake_content = "noise before {\"entities\": []} noise after"
    fake_resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=fake_content))])
    openai_mock = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: fake_resp)))
    monkeypatch.setattr(ner, "openai", openai_mock)
    result = ner.call_openai("prompt", model="gpt-4o")
    assert result == {"entities": []}
