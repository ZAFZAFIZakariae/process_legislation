import argparse
import json
import re
from typing import Any, Dict, List

from ner import extract_entities, postprocess_result, json_to_text


def _remove_positions(obj: Any) -> None:
    """Recursively remove ``start_char`` and ``end_char`` keys from *obj*."""
    if isinstance(obj, dict):
        obj.pop("start_char", None)
        obj.pop("end_char", None)
        for v in obj.values():
            _remove_positions(v)
    elif isinstance(obj, list):
        for item in obj:
            _remove_positions(item)


def _replace_outside_tags(text: str, search: str, repl: str) -> str:
    """Return *text* with all occurrences of ``search`` replaced by ``repl``
    while skipping regions already wrapped in ``<>`` tags."""
    result: List[str] = []
    i = 0
    slen = len(search)
    while i < len(text):
        idx = text.find(search, i)
        if idx == -1:
            result.append(text[i:])
            break
        # check if we're inside an existing tag
        before = text[:idx]
        if before.rfind("<") > before.rfind(">"):
            # inside a tag – skip this occurrence
            result.append(text[i: idx + slen])
            i = idx + slen
            continue
        result.append(text[i:idx])
        result.append(repl)
        i = idx + slen
    return "".join(result)


def _insert_brackets(text: str, entities: List[Dict[str, Any]]) -> str:
    """Wrap entity mentions in *text* with ``<TEXT, id:ID>`` markers."""
    seen = set()
    patterns: List[tuple[str, str]] = []
    for e in entities:
        ent_text = e.get("text", "")
        ent_id = e.get("id", "")
        if ent_text and ent_id and (ent_text, ent_id) not in seen:
            patterns.append((ent_text, ent_id))
            seen.add((ent_text, ent_id))
    if not patterns:
        return text
    patterns.sort(key=lambda x: len(x[0]), reverse=True)
    for ent_text, ent_id in patterns:
        replacement = f"<{ent_text}, id:{ent_id}>"
        text = _replace_outside_tags(text, ent_text, replacement)
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
    parser.add_argument(
        "--entities-output",
        help="Optional path to save raw NER result (entities and relations)",
    )
    parser.add_argument("--model", default="gpt-4o", help="OpenAI model to use")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    text = json_to_text(data)
    ner_result = extract_entities(text, args.model)
    postprocess_result(text, ner_result)
    entities = ner_result.get("entities", [])
    relations = ner_result.get("relations", [])

    # remove positional information before saving/annotating
    _remove_positions(entities)
    _remove_positions(relations)

    annotate_json(data, entities)
    if relations:
        data["relations"] = relations

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if args.entities_output:
        ner_out = {"entities": entities}
        if relations:
            ner_out["relations"] = relations
        with open(args.entities_output, "w", encoding="utf-8") as f:
            json.dump(ner_out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
