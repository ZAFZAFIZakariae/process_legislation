import os, sys
import copy

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pipeline.post_process import post_process_data


def test_branch_nesting_order():
    data = {
        "structure": [
            {"type": "القسم", "number": "1"},
            {"type": "الباب", "number": "1"},
            {"type": "الفرع", "number": "1"},
            {"type": "المادة", "number": "1", "text": "a"},
            {"type": "المادة", "number": "2", "text": "b"},
            {"type": "الفرع", "number": "2"},
            {"type": "المادة", "number": "3", "text": "c"},
            {"type": "الفرع", "number": "3"},
            {"type": "المادة", "number": "4", "text": "d"},
        ]
    }

    result = post_process_data(copy.deepcopy(data))
    section = result["structure"][0]
    chapter = section["children"][0]
    branches = chapter["children"]

    assert [b["number"] for b in branches] == ["1", "2", "3"]
    assert [a["number"] for a in branches[0]["children"]] == ["1", "2"]
    assert [a["number"] for a in branches[1]["children"]] == ["3"]
    assert [a["number"] for a in branches[2]["children"]] == ["4"]
