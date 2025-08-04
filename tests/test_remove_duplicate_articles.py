import pytest

from pipeline.hierarchy_builder import remove_duplicate_articles


def test_remove_duplicate_articles_nested_duplicates():
    structure = [
        {
            "type": "قسم",
            "number": "1",
            "children": [
                {"type": "مادة", "number": "1", "text": "short"},
                {"type": "مادة", "number": "1", "text": "a much longer text"},
                {"type": "مادة", "number": "2", "text": "unique"},
            ],
        },
        {
            "type": "قسم",
            "number": "2",
            "children": [
                {"type": "مادة", "number": "1", "text": "section2 article1"}
            ],
        },
    ]

    remove_duplicate_articles(structure)

    first_section = structure[0]["children"]
    # Article 1 duplicate removed, longer text kept
    assert len(first_section) == 2
    assert first_section[0]["number"] == "1"
    assert first_section[0]["text"] == "a much longer text"
    assert first_section[1]["number"] == "2"

    second_section = structure[1]["children"]
    # Article numbering in second section unaffected by first
    assert len(second_section) == 1
    assert second_section[0]["number"] == "1"
    assert second_section[0]["text"] == "section2 article1"
