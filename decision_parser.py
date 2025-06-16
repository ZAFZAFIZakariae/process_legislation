import os
import json
import argparse

try:
    import openai
except Exception:  # pragma: no cover - optional dependency may be missing

    class _Dummy:
        def __getattr__(self, name):
            raise RuntimeError("openai package is not available")

    openai = _Dummy()

try:  # Prefer relative import when running as part of a package
    from .ocr import pdf_to_arabic_text
except Exception:
    try:
        from ocr import pdf_to_arabic_text  # type: ignore
    except Exception:

        def pdf_to_arabic_text(path: str) -> str:
            raise RuntimeError("OCR functionality is unavailable in this environment")

PROMPT_FILE = os.path.join(os.path.dirname(__file__), "prompts", "decision_prompt.txt")
DEFAULT_MODEL = "gpt-3.5-turbo-16k"

openai.api_key = os.getenv("OPENAI_API_KEY", "DUMMY")


def load_prompt(text: str) -> str:
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        template = f.read()
    if "====DECISION_PROMPT====" in template:
        template = template.split("====DECISION_PROMPT====", 1)[1].strip()
    return template.replace("{{TEXT}}", text)


def call_openai(prompt: str, model: str = DEFAULT_MODEL) -> dict:
    messages = [
        {"role": "system", "content": "You summarise Moroccan court decisions."},
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


def process_file(path: str, model: str = DEFAULT_MODEL) -> dict:
    if path.lower().endswith(".pdf"):
        text = pdf_to_arabic_text(path)
    else:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    prompt = load_prompt(text)
    return call_openai(prompt, model)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract main sections from a court decision")
    parser.add_argument("--input", required=True, help="Path to a PDF or text file")
    parser.add_argument("--output", required=True, help="Path to save JSON output")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model name")
    args = parser.parse_args()

    result = process_file(args.input, args.model)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[+] Saved JSON to {args.output}")


if __name__ == "__main__":
    main()
