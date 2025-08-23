import ner

def test_parse_law_article_nums():
    ent = {
        "type": "LAW",
        "text": "المادة 15 من القانون رقم 30.09",
        "normalized": "المادة 15 القانون 30.09",
    }
    res = ner.parse_law_article_nums(ent)
    assert res == ("15", "30.09")


def test_parse_law_article_without_raqam():
    ent = {
        "type": "LAW",
        "text": "المادة 15 من القانون 30.09",
        "normalized": "المادة 15 القانون 30.09",
    }
    res = ner.parse_law_article_nums(ent)
    assert res == ("15", "30.09")
