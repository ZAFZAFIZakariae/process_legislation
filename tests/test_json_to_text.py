from ner import json_to_text


def test_json_to_text_extracts_all_strings():
    sample = {
        "preamble": "intro",
        "chapters": [
            {"articles": [{"text": "art1"}, {"text": "art2"}]},
        ],
        "nested": {"inner": "deep"},
        "number": 5,
    }
    text = json_to_text(sample)
    assert "intro" in text
    assert "art1" in text
    assert "art2" in text
    assert "deep" in text
    assert "5" not in text
