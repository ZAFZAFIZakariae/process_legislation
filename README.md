# process_legislation

This repository contains utilities for processing Moroccan legal documents using OCR and GPT models. The tools handle PDF conversion, extraction of named entities, document structuring and lightweight web interfaces.

## Repository layout
```
├── gpt.py            # Parse legislation into a nested JSON structure
├── ner.py            # Named‑entity extraction helper
├── ocr.py            # Azure Form Recognizer wrapper for PDF OCR
├── interface.py      # Streamlit interface for the NER pipeline
├── decision_parser.py# Summarise court decisions to JSON
├── interface.py      # Streamlit interface for entity extraction and decision parsing
├── app.py            # Flask web app exposing the same features
├── prompts/          # Prompt templates used by the scripts
├── data_pdf/         # Example PDFs
└── test_data/        # Sample text files
Requirements
├── data_txt/         # Example text files
└── input_ner/        # Sample decision text
```
## Requirements

Install the required Python packages (OpenAI SDK, tiktoken, Azure Form Recognizer, Streamlit, Flask, pandas, etc.):

```bash
pip install openai tiktoken azure-ai-formrecognizer==3.3.3 streamlit flask pandas
```

# Environment variables

Set the following variables so the scripts can access the APIs:
```bash
OPENAI_API_KEY – API key for OpenAI chat completions.
AZURE_ENDPOINT – Endpoint URL for the Azure Form Recognizer service (used by ocr.py).
AZURE_KEY – Key for the Azure Form Recognizer service.
```
# OCR a PDF
```bash
python ocr.py --input path/to/document.pdf --output_dir data_txt
```
The script saves the extracted Arabic text as `<document>.txt` inside the chosen
directory (`data_txt` by default).

# Parse legislation with GPT
```bash
python gpt.py --input path/to/document.pdf --output_dir output
```
If the input is a PDF it is OCRed first. The result is a JSON file (<document>.json) describing the legislation’s structure. A different model can be selected using --model.

## Multi-step pipeline
The scripts in `pipeline/` expose the same functionality as a series of steps. Use these when you need finer control over intermediate files:

```bash
# Extract structure in two passes
python -m pipeline.extract_chunks --input path/to/text.txt --output structure_raw.json --model gpt-4o

# Post-process the raw output
python -m pipeline.post_process --input structure_raw.json --output structure_final.json

# Run the entire process in one command
python -m pipeline.run_pipeline --input path/to/document.pdf --output_dir output
```
Running them with `-m` ensures relative imports resolve correctly when executed from the repository root.

Running `pipeline.run_pipeline` now also performs named‑entity recognition on
the extracted text and writes two extra files alongside the structured JSON:

* `<document>_ner.json` – raw entities and relations
* `<document>_ner.html` – HTML with clickable entities highlighting references
  and relationships

# Named‑entity extraction
```bash
python ner.py --input path/to/file.json --output_dir ner_out
```
This creates entities.csv and relations.csv inside the output directory. The
input can be a PDF, plain text, or a structured JSON file. Using a PDF file as
input triggers automatic OCR.

Pass `--annotate_text` to also save a copy of the input text where entity spans
are wrapped in `[[ENT …]]` markers. The Streamlit and Flask interfaces accept
such marked files and will highlight the entities without re-running the model.

# Annotation editor
```bash
python annotation_editor.py annotated.txt --add 100 110 PERSON --norm "محمد"
python annotation_editor.py annotated.txt --delete PERSON_1
python annotation_editor.py annotated.txt --update PERSON_2 TYPE=JUDGE norm="القاضي"
python annotation_editor.py annotated.txt --replace-text 50 60 "نص جديد" --fix-offsets
```
Use this helper to modify entity markers in a text annotated with `--annotate_text`.

# Court decision parser
```bash
python decision_parser.py --input path/to/decision.pdf --output decision.json
```
The script summarises the major sections of a court decision into JSON.

# Flask web app
```bash
python app.py
```
Open the browser at http://localhost:5000 to access entity extraction, relationship graph visualisation and decision parsing.

# Import results into SQLite
To collect data from many processed documents run:
```bash
python import_db.py --init-db legislation.db
python import_db.py --import legislation.db
```
This creates `legislation.db` and imports all JSON files from the `output/` directory.

Example SQL to list every case judged by a given person:
```sql
SELECT Documents.short_title, Entities.text
FROM Entities
JOIN Documents ON Entities.document_id = Documents.id
WHERE Entities.type='JUDGE' AND Entities.text LIKE '%محمد%';
```
To inspect cross-document references you can export the relation graph:
```bash
python import_db.py --export-graph relations.graphml --db legislation.db
```
Load the generated GraphML file in networkx or Gephi for further analysis.

## Querying the database from the UI

Both the Flask and Streamlit interfaces include a page to run read‑only SQL
statements. Start the web app and open `/query` (Flask) or use the "SQL Query"
section in the Streamlit interface. Choose one of the predefined statements or
enter a custom query and the results will be displayed in a table.

Example using the built‑in query:

```sql
SELECT doc_type, COUNT(*) FROM Documents GROUP BY doc_type;
```
