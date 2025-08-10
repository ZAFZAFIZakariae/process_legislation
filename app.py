import os
import json
import re
import tempfile
import shutil
try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None
import sqlite3
from flask import Flask, render_template, request, redirect, url_for
from types import SimpleNamespace

from annotation_editor import (
    add_entity as ae_add_entity,
    delete_entity as ae_delete_entity,
    update_entity as ae_update_entity,
    replace_text as ae_replace_text,
    fix_entity_offsets as ae_fix_offsets,
    text_with_markers as ae_text_with_markers,
    parse_marked_text as ae_parse_marked_text,
)

try:
    import networkx as nx  # optional
    from pyvis.network import Network
except Exception:  # pragma: no cover
    nx = None
    Network = None

from ner import extract_entities, postprocess_result, parse_marked_text
from ocr import pdf_to_arabic_text
from highlight import canonical_num, highlight_text, render_ner_html
try:
    from decision_parser import process_file as parse_decision
except Exception:  # pragma: no cover - optional dependency
    parse_decision = None

try:  # Optional pipeline for structure extraction
    from pipeline.ocr_to_text import convert_to_text
    from pipeline.extract_chunks import run_passes
    from pipeline.hierarchy_builder import (
        attach_stray_articles,
        flatten_articles,
        merge_duplicates,
        postprocess_structure,
        remove_duplicate_articles,
    )
    from pipeline.structured_ner import run_structured_ner
except BaseException:  # pragma: no cover - missing dependency
    convert_to_text = None
    run_passes = None
    run_structured_ner = None

app = Flask(__name__)

# Path to the SQLite database used for querying
DB_PATH = os.environ.get("DB_PATH", "legislation.db")

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

# Example queries shown in the web interface
PREDEFINED_QUERIES = {
    "Cases judged by a person": (
        "SELECT Documents.short_title, Entities.text "
        "FROM Entities JOIN Documents ON Entities.document_id = Documents.id "
        "WHERE Entities.type='JUDGE' AND Entities.text LIKE '%محمد%';"
    ),
    "Documents per type": "SELECT doc_type, COUNT(*) FROM Documents GROUP BY doc_type;",
}


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

            raw_text = text
            if '[[ENT' in text:
                text, entities = parse_marked_text(text)
                relations = []
            else:
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
                if not lines:
                    ref_text = str(ent.get('normalized') or ent.get('text') or '')
                    for raw in re.findall(r'[0-9٠-٩]+', ref_text):
                        num = canonical_num(raw)
                        if not num:
                            continue
                        art_txt = article_texts.get(num, '')
                        lines.append(f"الفصل {num}<br/>{art_txt}")
                if lines:
                    ref_article_texts[f"ID_{ent.get('id')}"] = '<br/><br/>'.join(lines)
            article_texts.update(ref_article_texts)

            annotated = highlight_text(raw_text, entities, None, ref_targets, tooltip_map, article_texts)

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


@app.route('/structure', methods=['GET', 'POST'])
def extract_structure():
    if run_passes is None or convert_to_text is None or run_structured_ner is None:
        return render_template('structure.html', error='Structure pipeline not available')
    if request.method == 'POST':
        uploaded = request.files.get('file')
        model = request.form.get('model', 'gpt-3.5-turbo-16k')
        if uploaded:
            suffix = os.path.splitext(uploaded.filename)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                uploaded.save(tmp.name)
                input_path = tmp.name
            try:
                tmp_dir = tempfile.mkdtemp()
                ner_html = None
                try:
                    txt_path = convert_to_text(input_path, tmp_dir)
                    result = run_passes(txt_path, model)
                    hier = postprocess_structure(result.get('structure', []))
                    flatten_articles(hier)
                    hier = merge_duplicates(hier)
                    remove_duplicate_articles(hier)
                    attach_stray_articles(hier)
                    result['structure'] = hier

                    result, ner_saved, raw_text, ner_raw = run_structured_ner(result, model)
                    ner_html = render_ner_html(raw_text, ner_raw)

                    base = os.path.basename(uploaded.filename).rsplit('.', 1)[0]
                    os.makedirs('output', exist_ok=True)
                    out_path = os.path.join('output', f'{base}.json')
                    with open(out_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)

                    ner_dir = 'ner_output'
                    os.makedirs(ner_dir, exist_ok=True)
                    ner_json = os.path.join(ner_dir, f'{base}_ner.json')
                    with open(ner_json, 'w', encoding='utf-8') as f:
                        json.dump(ner_saved, f, ensure_ascii=False, indent=2)

                    ner_html_path = os.path.join(ner_dir, f'{base}_ner.html')
                    with open(ner_html_path, 'w', encoding='utf-8') as f:
                        f.write(ner_html)
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                return render_template(
                    'structure.html',
                    result=result,
                    saved_file=os.path.basename(out_path),
                    ner_html=ner_html,
                )
            except Exception as exc:  # pragma: no cover - display error
                return render_template('structure.html', error=str(exc))
            finally:
                os.unlink(input_path)
    return render_template('structure.html')

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


def _collect_documents() -> dict[str, dict[str, str]]:
    """Return mapping of base names to structure and NER paths."""
    docs: dict[str, dict[str, str]] = {}
    if os.path.isdir('output'):
        for f in os.listdir('output'):
            if f.endswith('.json'):
                base = f.rsplit('.', 1)[0]
                docs.setdefault(base, {})['structure'] = os.path.join('output', f)
    if os.path.isdir('ner_output'):
        for f in os.listdir('ner_output'):
            if f.endswith('_ner.json'):
                base = f[:-9]  # remove '_ner.json'
                docs.setdefault(base, {})['ner'] = os.path.join('ner_output', f)
    return docs


def _load_annotation(name: str) -> tuple[str, list[dict], list[dict], str, str]:
    """Load raw text and NER data for *name* along with file paths."""
    txt_path = os.path.join('data_txt', f'{name}.txt')
    ner_path = os.path.join('ner_output', f'{name}_ner.json')
    text = ''
    if os.path.exists(txt_path):
        with open(txt_path, 'r', encoding='utf-8') as f:
            text = f.read()
    entities: list[dict] = []
    relations: list[dict] = []
    if os.path.exists(ner_path):
        with open(ner_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        entities = data.get('entities', [])
        relations = data.get('relations', [])
    # Compute entity offsets fresh from the raw text each time so the editor
    # can position selection brackets without relying on stored start/end
    # values.
    if text:
        lower = text.lower()
        cursor = 0
        for ent in entities:
            ent_txt = str(ent.get('text', ''))
            if not ent_txt:
                continue
            idx = lower.find(ent_txt.lower(), cursor)
            if idx == -1:
                idx = lower.find(ent_txt.lower())
            if idx != -1:
                ent['start_char'] = idx
                ent['end_char'] = idx + len(ent_txt)
                cursor = idx + len(ent_txt)
        ae_fix_offsets(text, {'entities': entities})
    return text, entities, relations, txt_path, ner_path


def _save_annotation(text: str, entities: list[dict], relations: list[dict], txt_path: str, ner_path: str) -> None:
    """Persist raw *text* and NER annotations back to disk."""
    os.makedirs(os.path.dirname(txt_path), exist_ok=True)
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(text)
    os.makedirs(os.path.dirname(ner_path), exist_ok=True)
    clean_entities: list[dict] = []
    for ent in entities:
        try:
            s = int(ent.get('start_char', -1))
            e = int(ent.get('end_char', -1))
            if 0 <= s < e <= len(text):
                ent['text'] = text[s:e]
        except Exception:
            pass
        clean_entities.append({k: v for k, v in ent.items() if k not in {'start_char', 'end_char'}})
    with open(ner_path, 'w', encoding='utf-8') as f:
        json.dump({'entities': clean_entities, 'relations': relations}, f, ensure_ascii=False, indent=2)


@app.route('/legislation')
def view_legislation():
    docs = _collect_documents()
    files = sorted(docs.keys())
    name = request.args.get('file')
    data = None
    entities = None
    doc = docs.get(name)
    if doc:
        with open(doc['structure'], 'r', encoding='utf-8') as f:
            data = json.load(f)
        ner_path = doc.get('ner')
        if ner_path and os.path.exists(ner_path):
            with open(ner_path, 'r', encoding='utf-8') as nf:
                ner_data = json.load(nf)
            entities = ner_data.get('entities', [])
            relations = ner_data.get('relations', [])
            ent_map = {str(e.get('id')): e for e in entities}
            for rel in relations:
                src = str(rel.get('source_id'))
                tgt = str(rel.get('target_id'))
                typ = rel.get('type')
                label = RELATION_LABELS.get(typ, typ)
                s_txt = ent_map.get(src, {}).get('text', '')
                t_txt = ent_map.get(tgt, {}).get('text', '')
                msg = f"{s_txt} {label} {t_txt}".strip()
                cat = 'references' if typ in {'refers_to', 'jumps_to'} else 'relations'
                if src in ent_map:
                    ent_map[src].setdefault(cat, []).append(msg)
                if tgt in ent_map:
                    ent_map[tgt].setdefault(cat, []).append(msg)
            entities = list(ent_map.values())
    return render_template(
        'legislation.html',
        files=files,
        selected=name,
        data=data,
        entities=entities,
    )


@app.route('/legislation/edit', methods=['GET', 'POST'])
def edit_legislation():
    docs = _collect_documents()
    name = request.args.get('file')
    if name not in docs:
        return "File not found", 404

    doc = docs.get(name, {})
    structure_path = doc.get('structure')
    structure = None
    if structure_path and os.path.exists(structure_path):
        with open(structure_path, 'r', encoding='utf-8') as sf:
            structure = json.load(sf)

    text, entities, relations, txt_path, ner_path = _load_annotation(name)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save':
            content = request.form.get('content', '')
            try:
                text, entities = ae_parse_marked_text(content)
                _save_annotation(text, entities, relations, txt_path, ner_path)
                return redirect(url_for('view_legislation', file=name))
            except Exception as exc:
                return render_template(
                    'edit_annotations.html',
                    file=name,
                    data=structure,
                    raw=content,
                    entities=entities,
                    error=str(exc),
                )

        # operations acting on existing annotations
        if action == 'add':
            args = SimpleNamespace(
                add=(request.form.get('start'), request.form.get('end'), request.form.get('type')),
                norm=request.form.get('norm'),
            )
            ae_add_entity(args, text, entities)
        elif action == 'delete':
            args = SimpleNamespace(delete=request.form.get('id'))
            ae_delete_entity(args, entities)
        elif action == 'update':
            uid = request.form.get('id')
            items = [uid]
            if request.form.get('type'):
                items.append(f"type={request.form.get('type')}")
            if request.form.get('norm'):
                items.append(f"norm={request.form.get('norm')}")
            if request.form.get('start'):
                items.append(f"start={request.form.get('start')}")
            if request.form.get('end'):
                items.append(f"end={request.form.get('end')}")
            args = SimpleNamespace(update=items)
            ae_update_entity(args, entities)
        elif action == 'replace':
            args = SimpleNamespace(
                replace_text=(
                    request.form.get('start'),
                    request.form.get('end'),
                    request.form.get('text'),
                )
            )
            text = ae_replace_text(args, text, entities)
        elif action == 'fix':
            ae_fix_offsets(text, {'entities': entities})

        _save_annotation(text, entities, relations, txt_path, ner_path)
        annotated = ae_text_with_markers(text, entities)
        return render_template(
            'edit_annotations.html',
            file=name,
            data=structure,
            raw=annotated,
            entities=entities,
            error=None,
        )
    annotated = ae_text_with_markers(text, entities)
    return render_template(
        'edit_annotations.html',
        file=name,
        data=structure,
        raw=annotated,
        entities=entities,
        error=None,
    )


@app.route('/query', methods=['GET', 'POST'])
def run_query():
    """Execute a read-only SQL query against the database."""
    result_html = None
    error = None
    sql = ''
    if request.method == 'POST':
        sql = request.form.get('sql', '')
        try:
            con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            df = pd.read_sql_query(sql, con)
            con.close()
            result_html = df.to_html(index=False)
        except Exception as exc:  # pragma: no cover - just display error
            error = str(exc)
    return render_template(
        'query.html',
        queries=PREDEFINED_QUERIES,
        sql=sql,
        result_html=result_html,
        error=error,
    )


if __name__ == '__main__':
    app.run(debug=True)
