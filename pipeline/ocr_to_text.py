import os
import sys
import argparse
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient

AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
AZURE_KEY = os.getenv("AZURE_KEY")

if not AZURE_ENDPOINT or not AZURE_KEY:
    print("❌ Missing Azure credentials. Please set the AZURE_ENDPOINT and AZURE_KEY environment variables.")
    sys.exit(1)


def pdf_to_arabic_text(pdf_path: str) -> str:
    """Use Azure Form Recognizer to OCR a PDF and return all Arabic text."""
    client = DocumentAnalysisClient(
        endpoint=AZURE_ENDPOINT,
        credential=AzureKeyCredential(AZURE_KEY),
    )

    with open(pdf_path, "rb") as f:
        poller = client.begin_analyze_document(model_id="prebuilt-read", document=f)
        result = poller.result()

    all_lines = []
    for page in result.pages:
        for line in page.lines:
            all_lines.append(line.content)
    return "\n".join(all_lines)


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
