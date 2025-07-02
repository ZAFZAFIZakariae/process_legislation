import os
import html
import json
import re
import tempfile
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from highlight import canonical_num, highlight_text

try:
    from .decision_parser import process_file as parse_decision
except Exception:  # Allow running without package context
    try:
        from decision_parser import process_file as parse_decision  # type: ignore
    except Exception:  # pragma: no cover - missing dependency
        parse_decision = None

try:
    import networkx as nx
    from pyvis.network import Network
except Exception:  # pragma: no cover - optional dependency may be missing
    nx = None
    Network = None

# Map relation types to Arabic labels for popups
RELATION_LABELS = {
    "enacted_by": "صادر بمقتضى",
    "published_in": "نشر في",
    "effective_on": "ساري المفعول اعتبارًا من",
    "contains": "يضم",
    "approved_by": "صودق عليه من طرف",
    "signed_by": "وقعه",
    "amended_by": "عُدّل بواسطة",
    "implements": "يطبق",
    "decides": "يبت في",
    "judged_by": "حكم من طرف",
    "represented_by": "يمثل بواسطة",
    "clerk_for": "كاتب ضبط لدى",
    "prosecuted_by": "تابعته",
    "refers_to": "يشير إلى",
    "jumps_to": "يحيل على",
}


def load_law_articles(dir_path: str = "output") -> dict[str, dict[str, str]]:
    """Return mapping of law number to article texts from JSON files."""
    mapping: dict[str, dict[str, str]] = {}
    for name in os.listdir(dir_path):
        if not name.endswith(".json"):
            continue
        path = os.path.join(dir_path, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            law = canonical_num(data.get("metadata", {}).get("document_number"))
            if not law:
                continue
            articles: dict[str, str] = {}

            def _collect(nodes: list[dict]) -> None:
                for node in nodes:
                    if node.get("type") in {"الفصل", "مادة"}:
                        num = canonical_num(node.get("number"))
                        if num and node.get("text"):
                            articles[num] = node.get("text", "")
                    if node.get("children"):
                        _collect(node["children"])

            _collect(data.get("structure", []))
            if articles:
                mapping[law] = articles
        except Exception as exc:  # pragma: no cover
            print(f"Failed to load {path}: {exc}")
    return mapping


LAW_ARTICLES = load_law_articles()

try:
    from .ner import extract_entities, postprocess_result
    from .ocr import pdf_to_arabic_text
except Exception:  # Allow running without package context
    from ner import extract_entities, postprocess_result  # type: ignore
    from ocr import pdf_to_arabic_text  # type: ignore


def build_graph(entities: list[dict], relations: list[dict]) -> str | None:
    """Return HTML for a relation graph or None if dependencies missing."""
    if nx is None or Network is None:
        return None

    G = nx.DiGraph()
    for ent in entities:
        eid = ent.get("id")
        label = ent.get("normalized") or ent.get("text")
        G.add_node(eid, label=label, title=ent.get("type"))

    for rel in relations:
        src = rel.get("source_id")
        tgt = rel.get("target_id")
        typ = rel.get("type")
        if src in G and tgt in G:
            G.add_edge(src, tgt, title=typ)

    net = Network(height="600px", width="100%", directed=True)
    net.from_nx(G)
    html_str = net.generate_html()  # type: ignore
    script = """
    <script type="text/javascript">
    function highlightEntities(ids) {
        document.querySelectorAll('.entity-mark').forEach(function(el) {
            el.classList.remove('selected');
        });
        ids.forEach(function(id){
            var el = document.getElementById('ent-'+id);
            if (el) {
                el.classList.add('selected');
            }
        });
    }
    network.on('click', function(params){
        if (params.nodes.length > 0) {
            var node = params.nodes[0];
            var connected = network.getConnectedNodes(node);
            connected.push(node);
            highlightEntities(connected);
            var target = document.getElementById('ent-'+node);
            if (target) { target.scrollIntoView({behavior:'smooth', block:'center'}); }
        }
    });
    </script>
    """
    return html_str.replace("</body>", script + "</body>")


st.set_page_config(page_title="Legal NER Assistant")
st.title("Legal NER Assistant")
st.markdown(
    """
    <style>
    .ner-span { direction: rtl; }
    .entity-mark { background-color: #FFFF00; }
    .entity-mark.selected { background-color: orange; }
    </style>
    """,
    unsafe_allow_html=True,
)

article_map: dict[str, str] = {}
article_texts: dict[str, str] = {}
articles_html = ""
json_files = [f for f in os.listdir("output") if f.endswith(".json")]
selected_json = (
    st.selectbox("Structured JSON", json_files) if json_files else None
)
if selected_json:
    path = os.path.join("output", selected_json)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sections: list[str] = []

    def _collect(nodes: list[dict]) -> None:
        for node in nodes:
            typ = node.get("type")
            if typ in {"الفصل", "مادة"}:
                num = canonical_num(node.get("number"))
                if num:
                    anchor = f"article-{num}"
                    article_map[num] = anchor
                    article_texts[num] = node.get("text", "")
                    title = html.escape(f"{typ} {node.get('number', '')}")
                    text_html = html.escape(node.get("text", ""))
                    sections.append(
                        f'<div id="{anchor}"><strong>{title}</strong><p>{text_html}</p></div>'
                    )
            if node.get("children"):
                _collect(node["children"])

    _collect(data.get("structure", []))
    articles_html = "\n\n".join(sections)

uploaded = st.file_uploader("Upload a PDF or text file", type=["pdf", "txt"])
model = st.text_input("OpenAI model", value="gpt-3.5-turbo-16k")

if uploaded and parse_decision and st.button("Parse Court Decision"):
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded.name)[1]) as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name
    try:
        result = parse_decision(tmp_path, model)
        st.subheader("Decision JSON")
        st.json(result)
    finally:
        os.unlink(tmp_path)
    st.stop()

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

    ref_targets: dict[str, list[str]] = {}
    tooltip_map: dict[str, str] = {}
    id_to_text = {str(e.get("id")): e.get("text", "") for e in entities}
    for rel in relations:
        src = str(rel.get("source_id"))
        tgt = str(rel.get("target_id"))
        typ = rel.get("type")
        if src and tgt:
            ref_targets.setdefault(src, []).append(tgt)
            if typ:
                s_txt = id_to_text.get(src, "")
                t_txt = id_to_text.get(tgt, "")
                rel_label = RELATION_LABELS.get(typ, typ)
                msg = f"{s_txt} {rel_label} {t_txt}".strip()
                existing = tooltip_map.get(src)
                if existing:
                    tooltip_map[src] = "<br/>".join([existing, msg])
                else:
                    tooltip_map[src] = msg

    article_popup_texts: dict[str, str] = {}
    id_to_ent = {str(e.get("id")): e for e in entities}
    for ent in entities:
        if ent.get("type") != "ARTICLE":
            continue
        num = canonical_num(ent.get("normalized") or ent.get("text"))
        if not num:
            continue
        law_nums: list[str] = []
        for tgt in ref_targets.get(str(ent.get("id")), []):
            tgt_ent = id_to_ent.get(str(tgt))
            if tgt_ent and tgt_ent.get("type") in {"LAW", "DECREE"}:
                ln = canonical_num(tgt_ent.get("normalized") or tgt_ent.get("text"))
                if ln:
                    law_nums.append(ln)
        search_laws = law_nums or list(LAW_ARTICLES.keys())
        found = None
        for ln in search_laws:
            amap = LAW_ARTICLES.get(ln)
            if amap and num in amap:
                found = f"{ln}: {amap[num]}"
                break
        if not found:
            found = "No matching article found"
        article_popup_texts[num] = found

    # Include popup text for references to multiple articles
    ref_article_texts: dict[str, str] = {}
    for ent in entities:
        if ent.get("type") != "INTERNAL_REF":
            continue
        lines: list[str] = []
        for tgt in ref_targets.get(str(ent.get("id")), []):
            tgt_ent = id_to_ent.get(str(tgt))
            if tgt_ent and tgt_ent.get("type") == "ARTICLE":
                num = canonical_num(tgt_ent.get("normalized") or tgt_ent.get("text"))
                if not num:
                    continue
                art_txt = article_popup_texts.get(num, "")
                lines.append(f"الفصل {num}<br/>{art_txt}")
        if lines:
            ref_article_texts[f"ID_{ent.get('id')}"] = "<br/><br/>".join(lines)
    article_popup_texts.update(ref_article_texts)

    if entities:
        df_e = pd.DataFrame(entities)

        with st.expander("Entities"):
            st.dataframe(df_e)
            csv = df_e.to_csv(index=False).encode("utf-8")
            st.download_button("Download entities.csv", csv, "entities.csv")

        st.subheader("Annotated Text")
        st.markdown(
            highlight_text(
                text,
                entities,
                article_map,
                ref_targets,
                tooltip_map,
                article_popup_texts,
            ),
            unsafe_allow_html=True,
        )

        with st.expander("Jump to entity"):
            jump_links: list[str] = ["<ul>"]
            for e in entities:
                anchor = e.get("id")
                text_html = html.escape(e.get("text", ""))
                jump_links.append(
                    f'<li><a href="javascript:void(0)" onclick="document.getElementById(\'{anchor}\').scrollIntoView();">{text_html}</a></li>'
                )
            jump_links.append("</ul>")
            st.markdown("\n".join(jump_links), unsafe_allow_html=True)

        if articles_html:
            with st.expander("Articles"):
                st.markdown(articles_html, unsafe_allow_html=True)

    if relations:
        df_r = pd.DataFrame(relations)
        st.subheader("Relations")
        st.dataframe(df_r)
        csv_r = df_r.to_csv(index=False).encode("utf-8")
        st.download_button("Download relations.csv", csv_r, "relations.csv")

        graph_html = build_graph(entities, relations)
        if graph_html:
            st.subheader("Relation Graph")
            components.html(graph_html, height=650, scrolling=True)
        else:
            st.info("Network graph requires networkx and pyvis packages")

    st.success("Extraction complete")
