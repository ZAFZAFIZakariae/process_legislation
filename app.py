import os
import html
import json
import tempfile
import pandas as pd
from flask import Flask, render_template, request

try:
    import networkx as nx  # optional
    from pyvis.network import Network
except Exception:  # pragma: no cover
    nx = None
    Network = None

from ner import extract_entities, postprocess_result
from ocr import pdf_to_arabic_text

app = Flask(__name__)

_DIGIT_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def canonical_num(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    s = value.translate(_DIGIT_TRANS)
    m = __import__("re").search(r"\d+(?:[./]\d+)*", s)
    return m.group(0) if m else None


def load_law_articles(dir_path: str = "output") -> dict[str, dict[str, str]]:
    """Load law articles from all JSON files under *dir_path*."""
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
        except Exception as exc:  # pragma: no cover - ignore bad files
            print(f"Failed to load {path}: {exc}")
    return mapping


LAW_ARTICLES = load_law_articles()


def highlight_text(
    text: str,
    entities: list[dict],
    article_map: dict[str, str] | None = None,
    ref_targets: dict[str, list[str]] | None = None,
    tooltips: dict[str, str] | None = None,
    article_texts: dict[str, str] | None = None,
) -> str:
    popup = (
        '<div id="article-popup" style="display:none;position:fixed;top:10%;'
        "left:10%;width:80%;max-height:80%;overflow:auto;background-color:white;"
        'border:1px solid #888;padding:10px;z-index:1000;">'
        "<button onclick=\"document.getElementById('article-popup').style.display='none';\" style=\"float:left;\">X</button>"
        '<div id="article-popup-content"></div></div>'
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

        if (
            target is None
            and ent.get("type") == "ARTICLE"
            and article_map is not None
        ):
            num = canonical_num(ent.get("normalized") or ent.get("text"))
            if num is not None and num in article_map:
                target = article_map[num]

        inner = f'<mark id="ent-{ent["id"]}" class="entity-mark"{tooltip}>{span_text}</mark>'
        art_data = ""
        if article_texts is not None and ent.get("type") == "ARTICLE":
            num = canonical_num(ent.get("normalized") or ent.get("text"))
            if num is not None and num in article_texts:
                art = article_texts[num].replace("\n", "<br/>")
                art_data = f' data-article="{html.escape(art)}"'

        if target or rel_attr or art_data:
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


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        uploaded = request.files.get('file')
        model = request.form.get('model', 'gpt-3.5-turbo-16k')
        if uploaded:
            if uploaded.filename.lower().endswith('.pdf'):
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                    uploaded.save(tmp.name)
                    text = pdf_to_arabic_text(tmp.name)
                os.unlink(tmp.name)
            else:
                text = uploaded.read().decode('utf-8')

            result = extract_entities(text, model)
            postprocess_result(text, result)

            entities = result.get('entities', [])
            relations = result.get('relations', [])

            ref_targets: dict[str, list[str]] = {}
            tooltip_map: dict[str, str] = {}
            id_to_text = {str(e.get('id')): e.get('text', '') for e in entities}
            for rel in relations:
                src = str(rel.get('source_id'))
                tgt = str(rel.get('target_id'))
                typ = rel.get('type')
                if src and tgt:
                    ref_targets.setdefault(src, []).append(tgt)
                    if typ:
                        s_txt = id_to_text.get(src, '')
                        t_txt = id_to_text.get(tgt, '')
                        tooltip_map[src] = f"{s_txt} {typ} {t_txt}".strip()

            article_texts: dict[str, str] = {}
            id_to_ent = {str(e.get('id')): e for e in entities}
            for ent in entities:
                if ent.get('type') != 'ARTICLE':
                    continue
                num = canonical_num(ent.get('normalized') or ent.get('text'))
                if not num:
                    continue
                law_nums: list[str] = []
                for tgt in ref_targets.get(str(ent.get('id')), []):
                    target_ent = id_to_ent.get(str(tgt))
                    if target_ent and target_ent.get('type') in {'LAW', 'DECREE'}:
                        ln = canonical_num(target_ent.get('normalized') or target_ent.get('text'))
                        if ln:
                            law_nums.append(ln)
                search_laws = law_nums or list(LAW_ARTICLES.keys())
                found_msg = None
                for ln in search_laws:
                    art_map = LAW_ARTICLES.get(ln)
                    if art_map and num in art_map:
                        found_msg = f"{ln}: {art_map[num]}"
                        break
                if not found_msg:
                    found_msg = "No matching article found"
                article_texts[num] = found_msg

            annotated = highlight_text(text, entities, None, ref_targets, tooltip_map, article_texts)

            df_e = pd.DataFrame(entities)
            entities_table = df_e.to_html(index=False)
            entities_csv = df_e.to_csv(index=False)

            relations_table = None
            relations_csv = ''
            graph_html = None
            if relations:
                df_r = pd.DataFrame(relations)
                relations_table = df_r.to_html(index=False)
                relations_csv = df_r.to_csv(index=False)
                graph_html = build_graph(entities, relations)

            return render_template(
                'index.html',
                annotated=annotated,
                entities_table=entities_table,
                entities_csv=entities_csv,
                relations_table=relations_table,
                relations_csv=relations_csv,
                graph_html=graph_html,
            )
    return render_template('index.html')


if __name__ == '__main__':
    app.run(debug=True)
