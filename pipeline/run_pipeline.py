import argparse
import json
import os

from .ocr_to_text import convert_to_text
from .extract_chunks import run_passes
from .post_process import post_process_data


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


if __name__ == "__main__":
    main()
