from highlight import render_ner_html


def test_render_ner_html_relations():
    text = 'القانون 1 يشير إلى الفصل 2'
    result = {
        'entities': [
            {'id': 1, 'type': 'LAW', 'text': 'القانون 1', 'start_char': 0, 'end_char': 9},
            {'id': 2, 'type': 'ARTICLE', 'text': 'الفصل 2', 'start_char': 19, 'end_char': 26},
        ],
        'relations': [
            {'source_id': 1, 'target_id': 2, 'type': 'refers_to'}
        ],
    }
    html = render_ner_html(text, result)
    assert 'entity-mark' in html
    assert 'data-rel="القانون 1 يشير إلى الفصل 2"' in html
