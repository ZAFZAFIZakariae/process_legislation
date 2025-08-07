import copy
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pipeline.post_process import post_process_data


def test_post_process_prunes_and_cleans():
    data = {
        "structure": [
            {
                "type": "قسم",
                "number": "1",
                "children": [
                    {"type": "مادة", "number": "1", "text": "text"},
                ],
            },
            # Stray root-level article (duplicate of article 1)
            {"type": "مادة", "number": "1", "text": "dup"},
            # Node with non-numeric number
            {"type": "مادة", "number": "foo", "text": "bad"},
            # Unknown type should be removed
            {"type": "ملاحظة", "number": "1", "text": "note"},
            # Root-level branch that should be dropped when sections exist
            {"type": "فرع", "number": "99", "children": []},
        ],
        "tables_and_schedules": [
            {"rows": [{"columns": ["", ""]}]},
            {"rows": [{"columns": ["data", ""]}]},
        ],
        "annexes": [
            {"annex_title": "A", "annex_text": ""},
            {"annex_title": "B", "annex_text": "Useful"},
        ],
    }

    cleaned = post_process_data(copy.deepcopy(data))

    # Only the section and its article remain; stray root article removed
    assert cleaned["structure"] == [
        {
            "type": "قسم",
            "number": "1",
            "children": [
                {"type": "مادة", "number": "1", "text": "text", "children": []}
            ],
        }
    ]

    # Placeholder table removed, non-empty one preserved
    assert cleaned["tables_and_schedules"] == [
        {"rows": [{"columns": ["data", ""]}]}
    ]

    # Empty annex pruned
    assert cleaned["annexes"] == [
        {"annex_title": "B", "annex_text": "Useful"}
    ]
