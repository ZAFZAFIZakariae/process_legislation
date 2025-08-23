import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ner import postprocess_result


def test_law_entity_with_article_uses_law_number():
    text = "المادة 4 من القانون التنظيمي رقم 29.11"
    result = {
        "entities": [
            {
                "id": "L1",
                "type": "LAW",
                "text": "المادة 4 من القانون التنظيمي رقم 29.11",
                "start_char": 0,
                "end_char": 41,
            }
        ],
        "relations": [],
    }
    postprocess_result(text, result)
    ent = result["entities"][0]
    assert ent["normalized"] == "المادة 4 القانون التنظيمي 29.11"
    assert ent["global_id"] == "LAW_29.11"


def test_law_entity_without_raqam():
    text = "المادة 15 من القانون 30.09"
    result = {
        "entities": [
            {
                "id": "L1",
                "type": "LAW",
                "text": "المادة 15 من القانون 30.09",
                "start_char": 0,
                "end_char": 28,
            }
        ],
        "relations": [],
    }
    postprocess_result(text, result)
    ent = result["entities"][0]
    assert ent["normalized"] == "المادة 15 القانون 30.09"
    assert ent["global_id"] == "LAW_30.09"


def test_law_entity_with_dahir_reference():
    text = (
        "كما تم تغييره وتتميمه بمقتضى المادة الفريدة من القانون رقم 30.06 "
        "الصادر بتنفيذه الظهير الشريف رقم 1.06.169"
    )
    result = {
        "entities": [
            {
                "id": "L1",
                "type": "LAW",
                "text": text,
                "start_char": 0,
                "end_char": len(text),
            }
        ],
        "relations": [],
    }
    postprocess_result(text, result)
    ent = result["entities"][0]
    assert ent["normalized"] == "القانون 30.06 الظهير الشريف 1.06.169"
    assert ent["global_id"] == "LAW_30.06"
