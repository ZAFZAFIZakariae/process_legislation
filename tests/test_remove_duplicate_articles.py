import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pipeline.hierarchy_builder import remove_duplicate_articles


def test_prefers_more_informative_version_and_preserves_position():
    first = {"type": "مادة", "number": "1", "text": "old"}
    second = {"type": "مادة", "number": "1", "text": "new and improved"}
    items = [first, second, {"type": "مادة", "number": "2", "text": "next"}]

    remove_duplicate_articles(items)

    assert [n["number"] for n in items] == ["1", "2"]
    assert items[0] is first
    assert items[0]["text"] == "new and improved"


def test_duplicates_removed_across_sections():
    structure = [
        {
            "type": "قسم",
            "number": "1",
            "children": [
                {"type": "مادة", "number": "1", "text": "section1 article1"},
                {"type": "مادة", "number": "2", "text": "section1 article2"},
            ],
        },
        {
            "type": "قسم",
            "number": "2",
            "children": [
                {"type": "مادة", "number": "1", "text": "dup"}
            ],
        },
    ]

    remove_duplicate_articles(structure)

    first_section = structure[0]["children"]
    assert [n["number"] for n in first_section] == ["1", "2"]

    second_section = structure[1]["children"]
    assert second_section == []


def test_out_of_order_earlier_duplicate_removed():
    items = [
        {"type": "مادة", "number": "50", "text": "fifty"},
        {"type": "مادة", "number": "65", "text": "stray"},
        {"type": "مادة", "number": "51", "text": "fifty one"},
        {"type": "مادة", "number": "65", "text": "proper sixty five"},
    ]

    remove_duplicate_articles(items)

    assert [n["number"] for n in items] == ["50", "51", "65"]
    assert items[-1]["text"] == "proper sixty five"
