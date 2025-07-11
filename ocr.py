# ---------------------------------------------------------
# Install dependencies (run once if needed)
# ---------------------------------------------------------
#   pip install azure-ai-formrecognizer==3.3.3

import os
import sys
import argparse
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient

# -----------------------------------------------------------------------------
# 1) Read Azure Form Recognizer credentials from environment
# -----------------------------------------------------------------------------
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
AZURE_KEY      = os.getenv("AZURE_KEY")

if not AZURE_ENDPOINT or not AZURE_KEY:
    print("❌ Missing Azure credentials. Please set the AZURE_ENDPOINT and AZURE_KEY environment variables.")
    sys.exit(1)

def pdf_to_arabic_text(pdf_path: str) -> str:
    """
    Use Azure Form Recognizer's prebuilt-read model to OCR the PDF.
    Returns a single string containing all Arabic lines (newline separated).
    """
    client = DocumentAnalysisClient(
        endpoint=AZURE_ENDPOINT,
        credential=AzureKeyCredential(AZURE_KEY)
    )

    with open(pdf_path, "rb") as f:
        poller = client.begin_analyze_document(
            model_id="prebuilt-read",
            document=f
        )
        result = poller.result()

    all_lines = []
    for page in result.pages:
        for line in page.lines:
            all_lines.append(line.content)
    return "\n".join(all_lines)

def main():
    parser = argparse.ArgumentParser(
        description="OCR a Moroccan‐legislation PDF → save Arabic text to .txt"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a single PDF file."
    )
    parser.add_argument(
        "--output_dir",
        default="data_txt",
        help="Directory to save the resulting .txt file (default: %(default)s)"
    )
    args = parser.parse_args()

    pdf_path = args.input
    if not (os.path.isfile(pdf_path) and pdf_path.lower().endswith(".pdf")):
        print(f"❌ Input is not a PDF: {pdf_path}")
        sys.exit(1)

    arabic_text = pdf_to_arabic_text(pdf_path)
    base = os.path.basename(pdf_path).rsplit(".", 1)[0]
    out_dir = args.output_dir
    os.makedirs(out_dir, exist_ok=True)
    txt_path = os.path.join(out_dir, f"{base}.txt")

    with open(txt_path, "w", encoding="utf-8") as fout:
        fout.write(arabic_text)

    print(f"[+] Saved OCR’d Arabic text to: {txt_path}")

if __name__ == "__main__":
    main()
