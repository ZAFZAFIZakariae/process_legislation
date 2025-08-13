import argparse
import json
import re
from typing import Any, Dict, List, Tuple

try:  # Prefer relative import when available
    from ..ner import extract_entities, postprocess_result, json_to_text
    # ``extract_entities`` ultimately calls ``ner.call_openai`` which now
    # includes defensive JSON recovery. Importing from ``ner`` here ensures
    # structured NER benefits from that logic without duplicating it.
except Exception:  # Allow running as a script
    from ner import extract_entities, postprocess_result, json_to_text  # type: ignore


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
            result.append(text[i : idx + slen])
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


def run_structured_ner(
    data: Dict[str, Any], model: str = "gpt-4o"
) -> Tuple[Dict[str, Any], Dict[str, Any], str, Dict[str, Any]]:
    """Run NER on *data* and annotate it with entity brackets.

    Returns a tuple ``(annotated_data, ner_clean, text, ner_raw)`` where:
    - ``annotated_data`` is the input data annotated in place,
    - ``ner_clean`` contains entities/relations without positional info suitable for saving,
    - ``text`` is the linearised text used for NER,
    - ``ner_raw`` is the full NER result with positional info for HTML rendering.
    """

    text = json_to_text(data)
    ner_raw = extract_entities(text, model)
    postprocess_result(text, ner_raw)

    entities = ner_raw.get("entities", [])
    relations = ner_raw.get("relations", [])

    stripped: List[Dict[str, Any]] = []
    for ent in entities:
        e = {k: v for k, v in ent.items() if k not in {"start_char", "end_char"}}
        stripped.append(e)

    annotate_json(data, stripped)

    ner_clean: Dict[str, Any] = {"entities": stripped}
    if relations:
        ner_clean["relations"] = relations

    return data, ner_clean, text, ner_raw


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

    annotated, ner_clean, _, _ = run_structured_ner(data, args.model)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(annotated, f, ensure_ascii=False, indent=2)

    if args.entities_output:
        with open(args.entities_output, "w", encoding="utf-8") as f:
            json.dump(ner_clean, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
