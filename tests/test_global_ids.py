import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ner import postprocess_result


def test_global_ids_for_law_and_article():
    text = "المادة 7 من القانون رقم 37.22"
    result = {
        "entities": [
            {"id": "a", "type": "ARTICLE", "text": "المادة 7", "start_char": 0, "end_char": 8},
            {"id": "b", "type": "LAW", "text": "القانون رقم 37.22", "start_char": 13, "end_char": 32},
        ],
        "relations": [
            {"relation_id": "r", "type": "refers_to", "source_id": "a", "target_id": "b"},
        ],
    }
    postprocess_result(text, result)
    article = next(e for e in result["entities"] if e["type"] == "ARTICLE")
    law = next(e for e in result["entities"] if e["type"] == "LAW")
    assert law["global_id"] == "LAW_37.22"
    assert article["global_id"] == "LAW_37.22_ART_7"


def test_article_without_law_gets_simple_global_id():
    text = "تنص المادة 5 على ..."
    result = {
        "entities": [
            {"id": "1", "type": "ARTICLE", "text": "المادة 5", "start_char": 4, "end_char": 12}
        ],
        "relations": [],
    }
    postprocess_result(text, result)
    art = result["entities"][0]
    assert art["global_id"] == "ART_5"


def test_article_refers_to_dahir():
    text = "المادة 7 من الظهير الشريف رقم 1.23.60"
    result = {
        "entities": [
            {"id": "a", "type": "ARTICLE", "text": "المادة 7", "start_char": 0, "end_char": 8},
            {
                "id": "b",
                "type": "DAHIR",
                "text": "الظهير الشريف رقم 1.23.60",
                "start_char": 13,
                "end_char": 41,
            },
        ],
        "relations": [
            {"relation_id": "r", "type": "refers_to", "source_id": "a", "target_id": "b"}
        ],
    }
    postprocess_result(text, result)
    art = next(e for e in result["entities"] if e["type"] == "ARTICLE")
    law = next(e for e in result["entities"] if e["type"] == "DAHIR")
    assert law["global_id"] == "DAHIR_1.23.60"
    assert art["global_id"] == "DAHIR_1.23.60_ART_7"
