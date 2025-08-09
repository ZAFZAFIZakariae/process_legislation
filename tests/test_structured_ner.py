import json
import sys
import structured_ner
from structured_ner import _insert_brackets, annotate_structure, annotate_json


def test_insert_brackets_simple():
    text = "القانون 1 يشير إلى الفصل 2"
    entities = [
        {"id": "LAW_1", "text": "القانون 1", "type": "LAW"},
        {"id": "ARTICLE_2", "text": "الفصل 2", "type": "ARTICLE"},
    ]
    marked = _insert_brackets(text, entities)
    assert "<القانون 1, id:LAW_1>" in marked
    assert "<الفصل 2, id:ARTICLE_2>" in marked


def test_annotate_structure_in_place():
    structure = [{"text": "القانون 1"}]
    entities = [{"id": "LAW_1", "text": "القانون 1", "type": "LAW"}]
    annotate_structure(structure, entities)
    assert structure[0]["text"] == "<القانون 1, id:LAW_1>"


def test_insert_brackets_deduplicates():
    text = "القانون 1 القانون 1"
    entities = [
        {"id": "LAW_1", "text": "القانون 1", "type": "LAW"},
        {"id": "LAW_1", "text": "القانون 1", "type": "LAW"},
    ]
    marked = _insert_brackets(text, entities)
    assert marked.count("<القانون 1, id:LAW_1>") == 2
    assert "<<" not in marked


def test_annotate_json_metadata():
    data = {"metadata": {"official_title": "القانون 1"}, "structure": []}
    entities = [{"id": "LAW_1", "text": "القانون 1", "type": "LAW"}]
    annotate_json(data, entities)
    assert data["metadata"]["official_title"] == "<القانون 1, id:LAW_1>"


def test_main_saves_relations(tmp_path, monkeypatch):
    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.json"
    data = {"structure": [{"text": "المادة 1 تشير إلى المادة 2"}]}
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    ner_result = {
        "entities": [
            {"id": "ARTICLE_1", "type": "ARTICLE", "text": "المادة 1"},
            {"id": "ARTICLE_2", "type": "ARTICLE", "text": "المادة 2"},
            {"id": "INTERNAL_REF_1", "type": "INTERNAL_REF", "text": "المادة 1"},
        ],
        "relations": [
            {
                "relation_id": "REL_refers_to_INTERNAL_REF_1_ARTICLE_2",
                "type": "refers_to",
                "source_id": "INTERNAL_REF_1",
                "target_id": "ARTICLE_2",
            }
        ],
    }

    monkeypatch.setattr(structured_ner, "extract_entities", lambda text, model: ner_result)
    monkeypatch.setattr(structured_ner, "postprocess_result", lambda text, res: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "structured_ner",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
    )

    structured_ner.main()

    with open(output_path, "r", encoding="utf-8") as f:
        out = json.load(f)

    assert out["relations"] == ner_result["relations"]
    assert out["relations"][0]["target_id"] == "ARTICLE_2"


def test_entities_output_without_positions(tmp_path, monkeypatch):
    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.json"
    ent_path = tmp_path / "entities.json"
    data = {"structure": [{"text": "المادة 1"}]}
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    ner_result = {
        "entities": [
            {
                "id": "ARTICLE_1",
                "type": "ARTICLE",
                "text": "المادة 1",
                "start_char": 0,
                "end_char": 7,
            }
        ],
        "relations": [],
    }

    monkeypatch.setattr(structured_ner, "extract_entities", lambda text, model: ner_result)
    monkeypatch.setattr(structured_ner, "postprocess_result", lambda text, res: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "structured_ner",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--entities-output",
            str(ent_path),
        ],
    )

    structured_ner.main()

    with open(ent_path, "r", encoding="utf-8") as f:
        ents = json.load(f)["entities"]

    assert "start_char" not in ents[0]
    assert "end_char" not in ents[0]


def test_relations_output_without_positions(tmp_path, monkeypatch):
    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.json"
    ent_path = tmp_path / "entities.json"
    data = {"structure": [{"text": "المادة 1 تشير"}]}
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    ner_result = {
        "entities": [],
        "relations": [
            {
                "relation_id": "R1",
                "type": "refers_to",
                "source_id": "A",
                "target_id": "B",
                "start_char": 0,
                "end_char": 5,
                "source": {"id": "A", "start_char": 0, "end_char": 1},
                "target": {"id": "B", "start_char": 2, "end_char": 3},
            }
        ],
    }

    monkeypatch.setattr(structured_ner, "extract_entities", lambda text, model: ner_result)
    monkeypatch.setattr(structured_ner, "postprocess_result", lambda text, res: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "structured_ner",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--entities-output",
            str(ent_path),
        ],
    )

    structured_ner.main()

    with open(ent_path, "r", encoding="utf-8") as f:
        rels = json.load(f).get("relations", [])

    assert "start_char" not in rels[0]
    assert "end_char" not in rels[0]
    assert "start_char" not in rels[0]["source"]
    assert "end_char" not in rels[0]["source"]
    assert "start_char" not in rels[0]["target"]
    assert "end_char" not in rels[0]["target"]
