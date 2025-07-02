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
from highlight import canonical_num, highlight_text
try:
    from decision_parser import process_file as parse_decision
except Exception:  # pragma: no cover - optional dependency
    parse_decision = None

app = Flask(__name__)

# Arabic labels for relation types
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


@app.route('/')
def home():
    return render_template('home.html')

@app.route('/entities', methods=['GET', 'POST'])
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
                        rel_label = RELATION_LABELS.get(typ, typ)
                        msg = f"{s_txt} {rel_label} {t_txt}".strip()
                        existing = tooltip_map.get(src)
                        if existing:
                            tooltip_map[src] = '<br/>'.join([existing, msg])
                        else:
                            tooltip_map[src] = msg

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

            # Build popup text for article references
            ref_article_texts: dict[str, str] = {}
            for ent in entities:
                if ent.get('type') != 'INTERNAL_REF':
                    continue
                lines: list[str] = []
                for tgt in ref_targets.get(str(ent.get('id')), []):
                    tgt_ent = id_to_ent.get(str(tgt))
                    if tgt_ent and tgt_ent.get('type') == 'ARTICLE':
                        num = canonical_num(tgt_ent.get('normalized') or tgt_ent.get('text'))
                        if not num:
                            continue
                        art_txt = article_texts.get(num, '')
                        lines.append(f"الفصل {num}<br/>{art_txt}")
                if lines:
                    ref_article_texts[f"ID_{ent.get('id')}"] = '<br/><br/>'.join(lines)
            article_texts.update(ref_article_texts)

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

@app.route('/decision', methods=['GET', 'POST'])
def parse_decision_route():
    if request.method == 'POST' and parse_decision:
        uploaded = request.files.get('file')
        model = request.form.get('model', 'gpt-3.5-turbo-16k')
        if uploaded:
            suffix = '.pdf' if uploaded.filename.lower().endswith('.pdf') else '.txt'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                uploaded.save(tmp.name)
                tmp_path = tmp.name
            try:
                result = parse_decision(tmp_path, model)
            finally:
                os.unlink(tmp_path)
            pretty = json.dumps(result, ensure_ascii=False, indent=2)
            return render_template('decision.html', result_json=pretty)
    return render_template('decision.html', result_json=None)


if __name__ == '__main__':
    app.run(debug=True)
