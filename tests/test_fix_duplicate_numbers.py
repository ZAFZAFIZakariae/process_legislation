import os
import sys
import types

# Provide a tiny stub for tiktoken so tests run in environments without the
# optional dependency.
tok_stub = types.SimpleNamespace(
    encoding_for_model=lambda _model: types.SimpleNamespace(
        encode=lambda s: [], decode=lambda t: ""
    )
)
sys.modules.setdefault("tiktoken", tok_stub)

# Stub for openai as well; only ``api_key`` attribute is accessed during tests.
openai_stub = types.SimpleNamespace(api_key=None)
sys.modules.setdefault("openai", openai_stub)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pipeline import gpt_helpers as gpt


def normalize(structure):
    gpt.finalize_structure(structure)
    gpt.fix_duplicate_numbers(structure)
    return [n.get("number") for n in structure]


def test_collapses_footnote_digit():
    items = [
        {"type": "فصل", "number": "1", "text": "first"},
        {"type": "فصل", "number": "22", "text": "second"},
        {"type": "فصل", "number": "3", "text": "third"},
    ]
    assert normalize(items) == ["1", "2", "3"]


def test_preserves_legitimate_double_digits():
    items = [
        {"type": "فصل", "number": "21"},
        {"type": "فصل", "number": "22"},
    ]
    assert normalize(items) == ["21", "22"]


def test_strips_prefixed_footnote_digits():
    items = [
        {"type": "فصل", "number": "6"},
        {"type": "فصل", "number": "17"},
        {"type": "فصل", "number": "8"},
    ]
    assert normalize(items) == ["6", "7", "8"]


def test_handles_three_digit_prefix():
    items = [
        {"type": "فصل", "number": "9"},
        {"type": "فصل", "number": "110"},
        {"type": "فصل", "number": "11"},
    ]
    assert normalize(items) == ["9", "10", "11"]


def test_keeps_legitimate_high_numbers():
    items = [
        {"type": "فصل", "number": "16"},
        {"type": "فصل", "number": "17"},
        {"type": "فصل", "number": "18"},
    ]
    assert normalize(items) == ["16", "17", "18"]
