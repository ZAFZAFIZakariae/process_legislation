import argparse
import json
import re
from typing import Any, Dict, List

from ner import extract_entities, postprocess_result, json_to_text


def _insert_brackets(text: str, entities: List[Dict[str, Any]]) -> str:
    """Wrap entity mentions in *text* with ``[TYPE:TEXT]`` markers."""
    # Deduplicate entity texts to avoid repeated nested markers
    seen = set()
    patterns = []
    for e in entities:
        ent_text = e.get("text", "")
        ent_type = e.get("type", "")
        if ent_text and (ent_text, ent_type) not in seen:
            patterns.append((ent_text, ent_type))
            seen.add((ent_text, ent_type))
    if not patterns:
        return text
    patterns.sort(key=lambda x: len(x[0]), reverse=True)
    for ent_text, ent_type in patterns:
        pattern = re.escape(ent_text)
        replacement = f"[{ent_type}:{ent_text}]" if ent_type else f"[{ent_text}]"
        text = re.sub(pattern, replacement, text)
    return text


def annotate_structure(structure: List[Dict[str, Any]], entities: List[Dict[str, Any]]) -> None:
    """Recursively insert entity markers into ``text`` and ``title`` fields."""
    for node in structure:
        txt = node.get("text")
        if isinstance(txt, str):
            node["text"] = _insert_brackets(txt, entities)
        title = node.get("title")
        if isinstance(title, str):
            node["title"] = _insert_brackets(title, entities)
        children = node.get("children")
        if isinstance(children, list):
            annotate_structure(children, entities)


def annotate_json(obj: Any, entities: List[Dict[str, Any]]) -> Any:
    """Recursively insert entity markers into all string fields of *obj*."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = annotate_json(v, entities)
        return obj
    if isinstance(obj, list):
        return [annotate_json(item, entities) for item in obj]
    if isinstance(obj, str):
        return _insert_brackets(obj, entities)
    return obj


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run NER over structured JSON and embed entity mentions in brackets.",
    )
    parser.add_argument("--input", required=True, help="Path to input JSON file")
    parser.add_argument("--output", required=True, help="Path to output JSON file")
    parser.add_argument("--model", default="gpt-4o", help="OpenAI model to use")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    text = json_to_text(data)
    ner_result = extract_entities(text, args.model)
    postprocess_result(text, ner_result)
    entities = ner_result.get("entities", [])
    annotate_json(data, entities)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
