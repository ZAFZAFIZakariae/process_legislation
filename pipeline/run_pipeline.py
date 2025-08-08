import argparse
import json
import os

from .ocr_to_text import convert_to_text
from .extract_chunks import run_passes
from .post_process import post_process_data

try:
    from ..ner import extract_entities, postprocess_result  # type: ignore
    from ..highlight import render_ner_html  # type: ignore
except Exception:  # pragma: no cover
    from ner import extract_entities, postprocess_result  # type: ignore
    from highlight import render_ner_html  # type: ignore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OCR (if needed), extract chunks, and build structured JSON",
    )
    parser.add_argument("--input", required=True, help="Path to PDF or text file")
    parser.add_argument("--output_dir", required=True, help="Directory for outputs")
    parser.add_argument("--model", default="gpt-4o", help="OpenAI model to use")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    txt_path = convert_to_text(args.input, args.output_dir)
    base = os.path.basename(txt_path).rsplit(".", 1)[0]
    raw_json = os.path.join(args.output_dir, f"{base}_raw.json")
    final_json = os.path.join(args.output_dir, f"{base}.json")

    raw_data = run_passes(txt_path, args.model)
    with open(raw_json, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)

    final_data = post_process_data(raw_data)
    with open(final_json, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)

    print(f"[+] Saved raw structure to: {raw_json}")
    print(f"[+] Saved final structure to: {final_json}")

    with open(txt_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    ner_result = extract_entities(raw_text, args.model)
    postprocess_result(raw_text, ner_result)
    ner_json = os.path.join(args.output_dir, f"{base}_ner.json")
    with open(ner_json, "w", encoding="utf-8") as f:
        json.dump(ner_result, f, ensure_ascii=False, indent=2)

    html = render_ner_html(raw_text, ner_result)
    html_path = os.path.join(args.output_dir, f"{base}_ner.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[+] Saved NER result to: {ner_json}")
    print(f"[+] Saved NER HTML to: {html_path}")


if __name__ == "__main__":
    main()
