import os
import html
import json
import re
import tempfile
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

try:
    import networkx as nx
    from pyvis.network import Network
except Exception:  # pragma: no cover - optional dependency may be missing
    nx = None
    Network = None

_DIGIT_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def canonical_num(value: str) -> str | None:
    """Return digits from text as a canonical string."""
    if not isinstance(value, str):
        return None
    s = value.translate(_DIGIT_TRANS)
    m = re.search(r"\d+(?:[./]\d+)*", s)
    return m.group(0) if m else None

try:
    from .ner import extract_entities, postprocess_result
    from .ocr import pdf_to_arabic_text
except Exception:  # Allow running without package context
    from ner import extract_entities, postprocess_result  # type: ignore
    from ocr import pdf_to_arabic_text  # type: ignore


def highlight_text(
    text: str,
    entities: list[dict],
    article_map: dict[str, str] | None = None,
    ref_targets: dict[str, list[str]] | None = None,
    tooltips: dict[str, str] | None = None,
    article_texts: dict[str, str] | None = None,
) -> str:
    """Return HTML for the text with entity spans anchored for linking."""
    popup = (
        "<div id=\"article-popup\" style=\"display:none;position:fixed;top:10%;"
        "left:10%;width:80%;max-height:80%;overflow:auto;background-color:white;"
        "border:1px solid #888;padding:10px;z-index:1000;\">"
        "<button onclick=\"document.getElementById('article-popup').style.display='none';\" style=\"float:left;\">X</button>"
        "<div id=\"article-popup-content\"></div></div>"
    )

    parts: list[str] = []
    last = 0
    for ent in sorted(entities, key=lambda e: int(e.get("start_char", 0))):
        try:
            start = int(ent.get("start_char", 0))
            end = int(ent.get("end_char", 0))
        except Exception:
            continue
        if (
            start < last
            or start < 0
            or end <= start
            or start >= len(text)
            or end > len(text)
        ):
            continue
        parts.append(html.escape(text[last:start]))
        span_text = html.escape(text[start:end])
        tooltip = ""
        rel_attr = ""
        if tooltips is not None:
            tip = tooltips.get(str(ent.get("id")))
            if tip:
                esc_tip = html.escape(tip)
                tooltip = f' title="{esc_tip}"'
                rel_attr = f' data-rel="{esc_tip}"'

        target: str | None = None
        if ref_targets is not None:
            targets = ref_targets.get(str(ent.get("id")))
            if targets:
                target = str(targets[0])

        if target is None and ent.get("type") == "ARTICLE" and article_map is not None:
            num = canonical_num(ent.get("normalized") or ent.get("text"))
            if num is not None and num in article_map:
                target = article_map[num]

        inner = f'<mark id="ent-{ent["id"]}" class="entity-mark"{tooltip}>{span_text}</mark>'
        if target or rel_attr:
            art_data = ""
            if article_texts is not None and ent.get("type") == "ARTICLE":
                num = canonical_num(ent.get("normalized") or ent.get("text"))
                if num is not None and num in article_texts:
                    art = article_texts[num].replace("\n", "<br/>")
                    art_data = f' data-article="{html.escape(art)}"'
            click_js = (
                "var a=this.getAttribute('data-article');"
                "var r=this.getAttribute('data-rel');"
                "var c=a||r;"
                " if(c){var p=document.getElementById('article-popup');"
                " var s=document.getElementById('article-popup-content');"
                " if(s){s.innerHTML=c;} if(p){p.style.display='block';}}"
            )
            parts.append(
                f'<span id="{ent["id"]}" class="ner-span"><a href="javascript:void(0)"{art_data}{rel_attr} onclick="{click_js}">{inner}</a></span>'
            )
        else:
            parts.append(
                f'<span id="{ent["id"]}" class="ner-span">{inner}</span>'
            )
        last = end
    parts.append(html.escape(text[last:]))
    html_str = "".join(parts)
    return popup + f'<div dir="rtl">{html_str}</div>'


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
selected_json = st.selectbox("Structured JSON", json_files) if json_files else None
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
                tooltip_map[src] = f"{s_txt} {typ} {t_txt}".strip()

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
                article_texts,
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
