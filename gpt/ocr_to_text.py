import os
import sys
import argparse

try:
    from ..ocr import pdf_to_arabic_text
except Exception:
    try:
        from ocr import pdf_to_arabic_text
    except Exception:
        def pdf_to_arabic_text(path: str) -> str:
            raise RuntimeError("OCR functionality is unavailable in this environment")


def convert_to_text(input_path: str, output_dir: str) -> str:
    """Return path to .txt with Arabic text extracted from input."""
    os.makedirs(output_dir, exist_ok=True)

    if input_path.lower().endswith(".pdf"):
        base = os.path.basename(input_path).rsplit(".", 1)[0]
        txt_path = os.path.join(output_dir, f"{base}.txt")
        text = pdf_to_arabic_text(input_path)
        with open(txt_path, "w", encoding="utf-8") as fout:
            fout.write(text)
        return txt_path
    elif input_path.lower().endswith(".txt"):
        txt_path = os.path.join(output_dir, os.path.basename(input_path))
        with open(input_path, "r", encoding="utf-8") as fin, open(txt_path, "w", encoding="utf-8") as fout:
            fout.write(fin.read())
        return txt_path
    else:
        raise ValueError("Input must be a PDF or .txt")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert PDF or .txt to a cleaned text file")
    parser.add_argument("--input", required=True, help="Path to PDF or text file")
    parser.add_argument("--output_dir", required=True, help="Directory for the resulting .txt")
    args = parser.parse_args()

    try:
        txt_path = convert_to_text(args.input, args.output_dir)
        print(f"[+] Saved text to: {txt_path}")
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
