import os
import html
import tempfile
import pandas as pd
import streamlit as st

try:
    from .ner import extract_entities, postprocess_result
    from .ocr import pdf_to_arabic_text
except Exception:  # Allow running without package context
    from ner import extract_entities, postprocess_result  # type: ignore
    from ocr import pdf_to_arabic_text  # type: ignore


def highlight_text(text: str, entities: list[dict]) -> str:
    """Return HTML for the text with entity spans anchored for linking."""
    parts: list[str] = []
    last = 0
    for ent in sorted(entities, key=lambda e: e.get("start_char", 0)):
        start = ent.get("start_char", 0)
        end = ent.get("end_char", 0)
        if start < last:
            continue
        parts.append(html.escape(text[last:start]))
        span_text = html.escape(text[start:end])
        parts.append(f'<span id="{ent["id"]}"><mark>{span_text}</mark></span>')
        last = end
    parts.append(html.escape(text[last:]))
    return "".join(parts)

st.set_page_config(page_title="Legal NER Assistant")
st.title("Legal NER Assistant")

uploaded = st.file_uploader("Upload a PDF or text file", type=["pdf", "txt"])
model = st.text_input("OpenAI model", value="gpt-3.5-turbo-16k")

if uploaded and st.button("Extract Entities"):
    if uploaded.name.lower().endswith(".pdf"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name
        text = pdf_to_arabic_text(tmp_path)
        os.unlink(tmp_path)
    else:
        text = uploaded.read().decode("utf-8")

    result = extract_entities(text, model)
    postprocess_result(text, result)

    entities = result.get("entities", [])
    relations = result.get("relations", [])

    if entities:
        df_e = pd.DataFrame(entities)
        st.subheader("Entities")
        st.dataframe(df_e)
        csv = df_e.to_csv(index=False).encode("utf-8")
        st.download_button("Download entities.csv", csv, "entities.csv")

        st.subheader("Annotated Text")
        st.markdown(highlight_text(text, entities), unsafe_allow_html=True)

        st.subheader("Jump to entity")
        for e in entities:
            st.markdown(f"- [{e['text']}](#{e['id']})", unsafe_allow_html=True)

    if relations:
        df_r = pd.DataFrame(relations)
        st.subheader("Relations")
        st.dataframe(df_r)
        csv_r = df_r.to_csv(index=False).encode("utf-8")
        st.download_button("Download relations.csv", csv_r, "relations.csv")

    st.success("Extraction complete")
