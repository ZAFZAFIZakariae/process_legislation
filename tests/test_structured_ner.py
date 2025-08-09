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
