import os
import json
import argparse
import tempfile
from typing import Dict, Any

import openai

try:  # Prefer relative import when available
    from .ocr import pdf_to_arabic_text
except Exception:
    try:
        from ocr import pdf_to_arabic_text  # type: ignore
    except Exception:
        def pdf_to_arabic_text(path: str) -> str:
            raise RuntimeError("OCR functionality is unavailable in this environment")

NER_PROMPT_FILE = os.path.join(os.path.dirname(__file__), "prompts", "ner_prompt.txt")
DEFAULT_MODEL = "gpt-3.5-turbo-16k"

openai.api_key = os.getenv("OPENAI_API_KEY", "DUMMY")


def load_prompt(text: str) -> str:
    with open(NER_PROMPT_FILE, "r", encoding="utf-8") as f:
        prompt = f.read()
    return prompt.replace("{{TEXT}}", text)


def call_openai(prompt: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": "You extract named entities from Moroccan legal text."},
        {"role": "user", "content": prompt},
    ]
    resp = openai.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content
    return json.loads(content)


def extract_entities(text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    prompt = load_prompt(text)
    return call_openai(prompt, model)


def extract_from_file(path: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    if path.lower().endswith(".pdf"):
        text = pdf_to_arabic_text(path)
    else:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    return extract_entities(text, model)


def save_as_csv(result: Dict[str, Any], output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    entities = result.get("entities", [])
    relations = result.get("relations", [])
    ent_path = os.path.join(output_dir, "entities.csv")
    rel_path = os.path.join(output_dir, "relations.csv")
    import csv
    with open(ent_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "type", "text", "start_char", "end_char", "normalized"])
        writer.writeheader()
        for e in entities:
            writer.writerow({
                "id": e.get("id", ""),
                "type": e.get("type", ""),
                "text": e.get("text", ""),
                "start_char": e.get("start_char", ""),
                "end_char": e.get("end_char", ""),
                "normalized": e.get("normalized", ""),
            })
    with open(rel_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["relation_id", "type", "source_id", "target_id"])
        writer.writeheader()
        for r in relations:
            writer.writerow({
                "relation_id": r.get("relation_id", ""),
                "type": r.get("type", ""),
                "source_id": r.get("source_id", ""),
                "target_id": r.get("target_id", ""),
            })
    print(f"[+] Saved entities to {ent_path}")
    print(f"[+] Saved relations to {rel_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract legal NER using OpenAI")
    parser.add_argument("--input", required=True, help="Path to a PDF or text file")
    parser.add_argument("--output_dir", required=True, help="Directory for CSV output")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model name")
    args = parser.parse_args()

    result = extract_from_file(args.input, args.model)
    out_json = os.path.join(args.output_dir, "ner_result.json")
    os.makedirs(args.output_dir, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[+] Saved raw JSON to {out_json}")

    save_as_csv(result, args.output_dir)


if __name__ == "__main__":
    main()
