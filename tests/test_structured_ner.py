import json
import sys

import structured_ner
from structured_ner import _insert_brackets, annotate_structure


def test_insert_brackets_simple():
    text = "القانون 1 يشير إلى الفصل 2"
    entities = [
        {"text": "القانون 1", "type": "LAW"},
        {"text": "الفصل 2", "type": "ARTICLE"},
    ]
    marked = _insert_brackets(text, entities)
    assert "[LAW:القانون 1]" in marked
    assert "[ARTICLE:الفصل 2]" in marked


def test_annotate_structure_in_place():
    structure = [{"text": "القانون 1"}]
    entities = [{"text": "القانون 1", "type": "LAW"}]
    annotate_structure(structure, entities)
    assert structure[0]["text"] == "[LAW:القانون 1]"


def test_main_saves_relations(tmp_path, monkeypatch):
    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.json"
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump({"structure": [{"text": "القانون 1 يشير إلى الفصل 2"}]}, f)

    ner_result = {
        "entities": [
            {"id": 1, "type": "LAW", "text": "القانون 1", "start_char": 0, "end_char": 9},
            {"id": 2, "type": "ARTICLE", "text": "الفصل 2", "start_char": 19, "end_char": 26},
        ],
        "relations": [
            {"source_id": 1, "target_id": 2, "type": "refers_to"}
        ],
    }

    monkeypatch.setattr(
        structured_ner, "extract_entities", lambda text, model: ner_result
    )
    monkeypatch.setattr(structured_ner, "postprocess_result", lambda text, res: None)

    monkeypatch.setattr(
        sys,
        "argv",
        ["structured_ner", "--input", str(input_path), "--output", str(output_path)],
    )
    structured_ner.main()

    with open(output_path, "r", encoding="utf-8") as f:
        saved = json.load(f)

    assert saved["relations"] == ner_result["relations"]
    assert saved["relations"][0]["source_id"] == 1
    assert saved["relations"][0]["target_id"] == 2
    assert saved["relations"][0]["type"] == "refers_to"
    assert saved["structure"][0]["text"] == "[LAW:القانون 1] يشير إلى [ARTICLE:الفصل 2]"
