import argparse
import os
import json

from .ocr_to_text import convert_to_text
from .extract_chunks import run_passes
from .post_process import finalize_from_file


def run_pipeline(input_path: str, output_dir: str, model: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    txt_path = convert_to_text(input_path, output_dir)
    intermediate = os.path.join(output_dir, "structure_raw.json")
    result = run_passes(txt_path, model)
    with open(intermediate, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    final_path = os.path.join(output_dir, "structure_final.json")
    finalize_from_file(intermediate, final_path)
    return final_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Full multi-step processing pipeline")
    parser.add_argument("--input", required=True, help="PDF or text file")
    parser.add_argument("--output_dir", required=True, help="Directory for output files")
    parser.add_argument("--model", default="gpt-3.5-turbo-16k", help="OpenAI model name")
    args = parser.parse_args()

    final_path = run_pipeline(args.input, args.output_dir, args.model)
    print(f"[+] Finished pipeline. Final JSON: {final_path}")


if __name__ == "__main__":
    main()
