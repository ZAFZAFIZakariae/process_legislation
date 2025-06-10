# process_legislation

Utilities for OCR, entity extraction, and GPT‑based structuring of Moroccan legal documents.

# Contents

.
├── gpt.py            # Parse legislation into a nested JSON structure
├── ner.py            # Named‑entity extraction helper
├── ocr.py            # Azure Form Recognizer wrapper for PDF OCR
├── interface.py      # Streamlit interface for the NER pipeline
├── prompts/          # Prompt templates used by the scripts
├── data_pdf/         # Example PDFs
└── test_data/        # Sample text files
Requirements

## Install the Python dependencies (OpenAI SDK, tiktoken, Azure Form Recognizer, Streamlit, pandas, etc.):

pip install openai tiktoken azure-ai-formrecognizer==3.3.3 streamlit pandas
Environment Variables

## Set these variables so the scripts can access the APIs:

OPENAI_API_KEY – API key for OpenAI’s chat completions.
AZURE_ENDPOINT – Endpoint URL for the Azure Form Recognizer service (used by ocr.py).
AZURE_KEY – Key for the Azure Form Recognizer service.
OCR a PDF

python ocr.py --input path/to/document.pdf
This saves the extracted Arabic text as <document>.txt next to the PDF.

## Parse Legislation with GPT

python gpt.py --input path/to/document.pdf --output_dir output
If --input is a PDF, the file is OCR’d first.
Output is a JSON file (<document>.json) describing the legislation’s structure.
You can choose a different model with --model, e.g. gpt-4.

## Named‑Entity Extraction

python ner.py --input path/to/text.txt --output_dir ner_out
The script creates entities.csv and relations.csv in the output directory.
Use a PDF file as input to trigger OCR automatically.

Streamlit Interface
Run the lightweight demo interface:

streamlit run interface.py
Upload a PDF or text file, then view and download the extracted entities and relations.

## Sample Data

data_pdf/ contains example PDFs for testing.
test_data/ has two short text samples that can be used with ner.py or the interface.
