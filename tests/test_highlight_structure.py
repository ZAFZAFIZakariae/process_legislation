from highlight import highlight_structure


def test_highlight_structure_inserts_mark():
    structure = [{"type": "مادة", "number": "1", "text": "المحكمة الابتدائية بالرباط تحكم"}]
    entities = [{"text": "المحكمة الابتدائية بالرباط"}]
    highlight_structure(structure, entities)
    assert "<mark>المحكمة الابتدائية بالرباط</mark>" in structure[0]["text"]
