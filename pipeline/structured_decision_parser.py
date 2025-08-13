import argparse
import json
import os

try:  # Prefer relative import when available
    from ..decision_parser import load_prompt, call_openai, DEFAULT_MODEL
    from ..ner import json_to_text
except Exception:  # Allow running as a script
    from decision_parser import load_prompt, call_openai, DEFAULT_MODEL  # type: ignore
    from ner import json_to_text  # type: ignore


def run_structured_decision_parser(data: dict, model: str = DEFAULT_MODEL) -> dict:
    """Parse a structured JSON *data* representing a court decision.

    The structured JSON is converted to plain text before being sent to the
    model.  The model response, expected to be JSON, is returned.
    """
    text = json_to_text(data)
    prompt = load_prompt(text)
    return call_openai(prompt, model)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract decision sections from structured JSON",
    )
    parser.add_argument("--input", required=True, help="Path to input JSON file")
    parser.add_argument(
        "--output", help="Optional path for JSON output; defaults to decision_output/"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model name")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = run_structured_decision_parser(data, args.model)

    if args.output:
        out_path = args.output
    else:
        os.makedirs("decision_output", exist_ok=True)
        base = os.path.splitext(os.path.basename(args.input))[0]
        out_path = os.path.join("decision_output", f"{base}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[+] Saved JSON to {out_path}")


if __name__ == "__main__":
    main()
