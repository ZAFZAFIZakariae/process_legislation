import os
import json
import re
import tempfile
import shutil
from typing import Optional
try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None
from sqlalchemy import create_engine, text
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
from pipeline.structured_ner import annotate_json

try:
    import networkx as nx  # optional
    from pyvis.network import Network
except Exception:  # pragma: no cover
    nx = None
    Network = None

from ner import extract_entities, postprocess_result, parse_marked_text
from ocr import pdf_to_arabic_text
from highlight import canonical_num, highlight_text, render_ner_html
from crossref_postgres import get_article_hits, find_person_docs, format_article_popup
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


@app.context_processor
def inject_globals() -> dict:
    cfg = load_settings()
    links = [
        ("home", "Home", url_for("home")),
        ("view_legislation", "Moroccan Legislation", url_for("view_legislation")),
        ("view_legal_documents", "Legal Documents", url_for("view_legal_documents")),
    ]
    return {"settings": cfg, "nav_links": links}


# Database connection string
DB_DSN = os.environ.get(
    "DB_DSN", "postgresql+psycopg://postgres:postgres@localhost:5432/legislation"
)
engine = create_engine(DB_DSN)

# Configuration for model and API credentials
SETTINGS_FILE = "settings.json"


def apply_settings(cfg: dict) -> None:
    """Apply API credentials from *cfg* to environment variables."""
    if cfg.get("provider") == "azure":
        os.environ["AZURE_OPENAI_API_KEY"] = cfg.get("azure_key", "")
        os.environ["AZURE_OPENAI_ENDPOINT"] = cfg.get("azure_endpoint", "")
        os.environ.pop("OPENAI_API_KEY", None)
    else:
        os.environ["OPENAI_API_KEY"] = cfg.get("openai_key", "")
        os.environ.pop("AZURE_OPENAI_API_KEY", None)
        os.environ.pop("AZURE_OPENAI_ENDPOINT", None)


def load_settings() -> dict:
    """Load settings from *SETTINGS_FILE* (creating defaults if missing)."""
    default = {
        "provider": "openai",
        "model": "gpt-4o",
        "openai_key": "",
        "azure_key": "",
        "azure_endpoint": "",
    }
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = default.copy()
    else:
        for k, v in default.items():
            data.setdefault(k, v)
    apply_settings(data)
    return data


def save_settings(data: dict) -> None:
    """Persist *data* to *SETTINGS_FILE* and apply credentials."""
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    apply_settings(data)


def get_model() -> str:
    """Return the currently configured GPT model."""
    return load_settings().get("model", "gpt-3.5-turbo-16k")

# Initialise settings and credentials at import time
load_settings()

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


def _collect_article_texts(data):
    """Return mapping of article numbers to text from *data*."""
    texts = {}

    def _collect(node):
        if isinstance(node, dict):
            typ = node.get("type")
            if typ in {"الفصل", "مادة"}:
                num = canonical_num(node.get("number"))
                if num:
                    texts[num] = node.get("text", "")
            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    _collect(child)
        elif isinstance(node, list):
            for item in node:
                _collect(item)

    _collect(data)
    return texts

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


def extract_general_structure(text: str) -> list[dict]:
    """Split *text* into paragraph blocks for generic legal documents."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    return [{"text": b} for b in blocks]


def process_legal_document(
    input_path: str, uploaded_name: str, model: str, tmp_dir: str
) -> tuple[dict, str]:
    """Process a document without Moroccan-specific chunking."""
    if uploaded_name.lower().endswith(".pdf"):
        if convert_to_text is None:
            raise RuntimeError("PDF support not available")
        txt_path = convert_to_text(input_path, tmp_dir)
        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        with open(input_path, "r", encoding="utf-8") as f:
            text = f.read()
    structure = extract_general_structure(text)
    return {"structure": structure}, text


@app.route('/settings', methods=['POST'])
def settings_route():
    cfg = load_settings()
    cfg['provider'] = request.form.get('provider', cfg.get('provider'))
    cfg['model'] = request.form.get('model', cfg.get('model'))
    cfg['openai_key'] = request.form.get('openai_key', cfg.get('openai_key'))
    cfg['azure_key'] = request.form.get('azure_key', cfg.get('azure_key'))
    cfg['azure_endpoint'] = request.form.get('azure_endpoint', cfg.get('azure_endpoint'))
    save_settings(cfg)
    return ('', 204)


@app.route('/', methods=['GET', 'POST'])
def home():
    """Render the main interface and handle uploads/SQL queries."""
    cfg = load_settings()
    result_html = None
    error = None
    sql = ''
    saved_file: str | None = None
    saved_to: str | None = None
    process_error: str | None = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'query':
            sql = request.form.get('sql', '')
            try:
                with engine.connect() as con:
                    if pd:
                        df = pd.read_sql_query(sql, con)
                        result_html = df.to_html(index=False)
                    else:  # pragma: no cover - fallback when pandas missing
                        rows = con.execute(text(sql)).fetchall()
                        headers = rows[0].keys() if rows else []
                        result_html = (
                            '<table><thead><tr>'
                            + ''.join(f'<th>{h}</th>' for h in headers)
                            + '</tr></thead><tbody>'
                            + ''.join(
                                '<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>'
                                for row in rows
                            )
                            + '</tbody></table>'
                        )
            except Exception as exc:  # pragma: no cover - display error
                error = str(exc)
        elif action == 'process':
            uploaded = request.files.get('file')
            if not uploaded:
                process_error = 'No file uploaded'
            elif convert_to_text is None and uploaded.filename.lower().endswith('.pdf'):
                process_error = 'Structure pipeline not available'
            else:
                suffix = os.path.splitext(uploaded.filename)[1] or '.txt'
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    uploaded.save(tmp.name)
                    input_path = tmp.name
                try:
                    tmp_dir = tempfile.mkdtemp()
                    model = cfg.get('model', 'gpt-3.5-turbo-16k')
                    output_type = request.form.get('output_type', 'legislation')
                    ner_saved = None
                    if output_type == 'legal':
                        result, raw_text = process_legal_document(
                            input_path, uploaded.filename, model, tmp_dir
                        )
                    else:
                        if run_passes is None:
                            raise RuntimeError('Structure pipeline not available')
                        txt_path = convert_to_text(input_path, tmp_dir)
                        result = run_passes(txt_path, model)
                        hier = postprocess_structure(result.get('structure', []))
                        flatten_articles(hier)
                        hier = merge_duplicates(hier)
                        remove_duplicate_articles(hier)
                        attach_stray_articles(hier)
                        result['structure'] = hier
                        with open(txt_path, 'r', encoding='utf-8') as f:
                            raw_text = f.read()

                    if request.form.get('decision_parser'):
                        try:  # pragma: no cover - optional dependency
                            from pipeline.structured_decision_parser import (
                                run_structured_decision_parser,
                            )
                            result['decision'] = run_structured_decision_parser(
                                result, model
                            )
                        except Exception:
                            pass
                    if request.form.get('structured_ner') and run_structured_ner:
                        result, ner_saved, raw_text, _ = run_structured_ner(
                            result, model
                        )
                    base = os.path.splitext(uploaded.filename)[0]
                    os.makedirs('data_txt', exist_ok=True)
                    with open(
                        os.path.join('data_txt', f'{base}.txt'), 'w', encoding='utf-8'
                    ) as f:
                        f.write(raw_text)
                    if output_type == 'legal':
                        os.makedirs('legal_output', exist_ok=True)
                        out_path = os.path.join('legal_output', f'{base}.json')
                        data_to_save = {
                            "structure": result.get('structure', []),
                            "text": raw_text,
                        }
                        if request.form.get('decision_parser') and result.get('decision'):
                            data_to_save['decision'] = result['decision']
                    else:
                        os.makedirs('output', exist_ok=True)
                        out_path = os.path.join('output', f'{base}.json')
                        data_to_save = result
                    with open(out_path, 'w', encoding='utf-8') as f:
                        json.dump(data_to_save, f, ensure_ascii=False, indent=2)
                    if request.form.get('structured_ner') and ner_saved:
                        os.makedirs('ner_output', exist_ok=True)
                        ner_json = os.path.join('ner_output', f'{base}_ner.json')
                        with open(ner_json, 'w', encoding='utf-8') as f:
                            json.dump(ner_saved, f, ensure_ascii=False, indent=2)
                    saved_file = base
                    saved_to = output_type
                    try:  # pragma: no cover - optional dependency
                        from db.postgres_import import import_json_dir
                        if os.path.isdir('output'):
                            import_json_dir('output')
                        if os.path.isdir('legal_output'):
                            import_json_dir('legal_output')
                        if os.path.isdir('ner_output'):
                            import_json_dir('ner_output')
                    except Exception as exc:
                        process_error = str(exc)
                except Exception as exc:  # pragma: no cover - show error
                    process_error = str(exc)
                finally:
                    os.unlink(input_path)
                    shutil.rmtree(tmp_dir, ignore_errors=True)
    return render_template(
        'home.html',
        result_html=result_html,
        error=error,
        sql=sql,
        saved_file=saved_file,
        saved_to=saved_to,
        process_error=process_error,
    )

@app.route('/entities', methods=['GET', 'POST'])
def index():
    cfg = load_settings()
    model = cfg.get('model', 'gpt-3.5-turbo-16k')
    if request.method == 'POST':
        uploaded = request.files.get('file')
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

            # Helper to attach first best hit as popup for an entity id
            def _attach_article_popup_for_ent(ent_id: str, law_hint: Optional[str], art_hint: str) -> None:
                hits = get_article_hits(
                    article_number_raw=art_hint,
                    law_number_raw=law_hint,
                    limit=3,
                )
                if hits:
                    html_snip = format_article_popup(hits[0])
                    article_texts[f"ID_{ent_id}"] = html_snip

            # 1) If your NER produced explicit ARTICLE entities, resolve via law context when available
            for ent in entities:
                if ent.get("type") == "ARTICLE":
                    art_txt = ent.get("normalized") or ent.get("text") or ""
                    law_hint: Optional[str] = None
                    for rel in relations:
                        s = str(rel.get("source_id"))
                        t = str(rel.get("target_id"))
                        if s == str(ent.get("id")):
                            tgt_ent = next((e for e in entities if str(e.get("id")) == t), None)
                            if tgt_ent and tgt_ent.get("type") in {"LAW", "DECREE", "DAHIR", "STATUTE"}:
                                law_hint = tgt_ent.get("normalized") or tgt_ent.get("text")
                                break
                        if t == str(ent.get("id")):
                            src_ent = next((e for e in entities if str(e.get("id")) == s), None)
                            if src_ent and src_ent.get("type") in {"LAW", "DECREE", "DAHIR", "STATUTE"}:
                                law_hint = src_ent.get("normalized") or src_ent.get("text")
                                break
                    _attach_article_popup_for_ent(str(ent.get("id")), law_hint, art_txt)

            # 2) For INTERNAL_REF or “reference-like” entities, mine likely article numbers and attempt lookups
            import re
            for ent in entities:
                if ent.get("type") in {"INTERNAL_REF", "REFERENCE", "CITATION"}:
                    txt = ent.get("normalized") or ent.get("text") or ""
                    cand_nums = re.findall(r"\d+[./]?\d*", txt)
                    if not cand_nums:
                        continue
                    law_hint = None
                    for rel in relations:
                        if str(rel.get("source_id")) == str(ent.get("id")):
                            tgt = next((e for e in entities if str(e.get("id")) == str(rel.get("target_id"))), None)
                            if tgt and tgt.get("type") in {"LAW", "DECREE", "DAHIR", "STATUTE"}:
                                law_hint = tgt.get("normalized") or tgt.get("text")
                                break
                    for num in cand_nums:
                        hits = get_article_hits(
                            article_number_raw=num,
                            law_number_raw=law_hint,
                            limit=1,
                        )
                        if hits:
                            article_texts[f"ID_{ent.get('id')}"] = format_article_popup(hits[0])
                            break

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
    cfg = load_settings()
    model = cfg.get('model', 'gpt-3.5-turbo-16k')
    if request.method == 'POST':
        uploaded = request.files.get('file')
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

                    txt_dir = 'data_txt'
                    os.makedirs(txt_dir, exist_ok=True)
                    txt_out = os.path.join(txt_dir, f'{base}.txt')
                    with open(txt_out, 'w', encoding='utf-8') as f:
                        f.write(raw_text)

                    os.makedirs('output', exist_ok=True)
                    out_path = os.path.join('output', f'{base}.json')
                    with open(out_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)

                    ner_dir = 'ner_output'
                    os.makedirs(ner_dir, exist_ok=True)
                    ner_json = os.path.join(ner_dir, f'{base}_ner.json')
                    with open(ner_json, 'w', encoding='utf-8') as f:
                        json.dump(ner_saved, f, ensure_ascii=False, indent=2)

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
    cfg = load_settings()
    model = cfg.get('model', 'gpt-3.5-turbo-16k')
    if request.method == 'POST' and parse_decision:
        uploaded = request.files.get('file')
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


def _collect_legislation_documents() -> dict[str, dict[str, str]]:
    """Return mapping of legislation base names to structure and NER paths."""
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
                if base in docs:
                    docs[base]['ner'] = os.path.join('ner_output', f)
    return docs


def _collect_legal_documents() -> dict[str, str]:
    """Return mapping of base names to legal document paths."""
    docs: dict[str, str] = {}
    if os.path.isdir('legal_output'):
        for f in os.listdir('legal_output'):
            if f.endswith('.json'):
                base = f.rsplit('.', 1)[0]
                docs[base] = os.path.join('legal_output', f)
    return docs


def _load_annotation(name: str) -> tuple[str, list[dict], list[dict], str, str]:
    """Load raw text and NER data for *name* along with file paths."""
    txt_path = os.path.join('data_txt', f'{name}.txt')
    if not os.path.exists(txt_path):
        alt = os.path.join('court_decision_txt', f'{name}.txt')
        if os.path.exists(alt):
            txt_path = alt
        article_texts = _collect_article_texts(data)
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


def _save_annotation(
    text: str,
    entities: list[dict],
    relations: list[dict],
    txt_path: str,
    ner_path: str,
    structure_path: str | None = None,
) -> None:
    """Persist raw *text* and NER annotations back to disk."""

    os.makedirs(os.path.dirname(txt_path), exist_ok=True)
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())

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
        clean_entities.append(
            {k: v for k, v in ent.items() if k not in {'start_char', 'end_char'}}
        )

    with open(ner_path, 'w', encoding='utf-8') as f:
        json.dump(
            {'entities': clean_entities, 'relations': relations},
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.flush()
        os.fsync(f.fileno())

    if structure_path and os.path.exists(structure_path):
        def _strip_markers(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    obj[k] = _strip_markers(v)
                return obj
            if isinstance(obj, list):
                return [_strip_markers(v) for v in obj]
            if isinstance(obj, str):
                return re.sub(r'<([^,<>]+), id:[^>]+>', r'\1', obj)
            return obj

        with open(structure_path, 'r', encoding='utf-8') as sf:
            struct = json.load(sf)
        struct = _strip_markers(struct)
        annotate_json(struct, clean_entities)
        with open(structure_path, 'w', encoding='utf-8') as sf:
            json.dump(struct, sf, ensure_ascii=False, indent=2)
            sf.flush()
            os.fsync(sf.fileno())


@app.route('/legislation')
def view_legislation():
    docs = _collect_legislation_documents()
    files = sorted(docs.keys())
    name = request.args.get('file')
    data = None
    decision = None
    entities = None
    text = None
    text = None
    doc = docs.get(name)
    if doc:
        with open(doc['structure'], 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        # Some JSON files produced by the pipeline store the structured
        # legislation under a top-level "structure" key and any court decision
        # sections under a parallel "decision" key.  Expose both pieces to the
        # template so the UI can present the decision blocks separately while
        # still rendering the structured legislation tree.
        if isinstance(loaded, dict) and 'structure' in loaded:
            data = loaded.get('structure')
            decision = loaded.get('decision')
        else:
            data = loaded
        article_texts = _collect_article_texts(data)
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
                s_ent = ent_map.get(src)
                t_ent = ent_map.get(tgt)
                if (
                    typ in {'refers_to', 'jumps_to'}
                    and s_ent
                    and t_ent
                    and s_ent.get('type') == 'INTERNAL_REF'
                    and t_ent.get('type') == 'ARTICLE'
                ):
                    num = canonical_num(t_ent.get('normalized') or t_ent.get('text'))
                    art_txt = article_texts.get(num, '') if num else ''
                    s_ent.setdefault('articles', []).append(f"الفصل {num}: {art_txt}")
                    label = RELATION_LABELS.get(typ, typ)
                    msg = f"{s_ent.get('text', '')} {label} {t_ent.get('text', '')}".strip()
                    t_ent.setdefault('references', []).append(msg)
                    continue
                label = RELATION_LABELS.get(typ, typ)
                s_txt = s_ent.get('text', '') if s_ent else ''
                t_txt = t_ent.get('text', '') if t_ent else ''
                msg = f"{s_txt} {label} {t_txt}".strip()
                cat = 'references' if typ in {'refers_to', 'jumps_to'} else 'relations'
                if s_ent:
                    s_ent.setdefault(cat, []).append(msg)
                if t_ent:
                    t_ent.setdefault(cat, []).append(msg)
            entities = list(ent_map.values())
    return render_template(
        'legislation.html',
        files=files,
        selected=name,
        data=data,
        decision=decision,
        entities=entities,
    )


@app.route('/legal_documents')
def view_legal_documents():
    docs = _collect_legal_documents()
    files = sorted(docs.keys())
    name = request.args.get('file')
    data = None
    decision = None
    entities = None
    text = None
    doc = docs.get(name)
    if doc:
        with open(doc, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        data = loaded.get('structure')
        decision = loaded.get('decision')
        if isinstance(data, list):
            texts = []
            for block in data:
                if isinstance(block, dict) and block.get('text'):
                    texts.append(block.get('text', ''))
            text = "\n\n".join(texts) if texts else None
        article_texts = _collect_article_texts(data)
        ner_path = os.path.join('ner_output', f'{name}_ner.json')
        if os.path.exists(ner_path):
            with open(ner_path, 'r', encoding='utf-8') as nf:
                ner_data = json.load(nf)
            entities = ner_data.get('entities', [])
            relations = ner_data.get('relations', [])
            ent_map = {str(e.get('id')): e for e in entities}
            for rel in relations:
                src = str(rel.get('source_id'))
                tgt = str(rel.get('target_id'))
                typ = rel.get('type')
                s_ent = ent_map.get(src)
                t_ent = ent_map.get(tgt)
                if (
                    typ in {'refers_to', 'jumps_to'}
                    and s_ent
                    and t_ent
                    and s_ent.get('type') == 'INTERNAL_REF'
                    and t_ent.get('type') == 'ARTICLE'
                ):
                    num = canonical_num(t_ent.get('normalized') or t_ent.get('text'))
                    art_txt = article_texts.get(num, '') if num else ''
                    s_ent.setdefault('articles', []).append(f"الفصل {num}: {art_txt}")
                    label = RELATION_LABELS.get(typ, typ)
                    msg = f"{s_ent.get('text', '')} {label} {t_ent.get('text', '')}".strip()
                    t_ent.setdefault('references', []).append(msg)
                    continue
                label = RELATION_LABELS.get(typ, typ)
                s_txt = s_ent.get('text', '') if s_ent else ''
                t_txt = t_ent.get('text', '') if t_ent else ''
                msg = f"{s_txt} {label} {t_txt}".strip()
                cat = 'references' if typ in {'refers_to', 'jumps_to'} else 'relations'
                if s_ent:
                    s_ent.setdefault(cat, []).append(msg)
                if t_ent:
                    t_ent.setdefault(cat, []).append(msg)
            entities = list(ent_map.values())
    return render_template(
        'legal_documents.html',
        files=files,
        selected=name,
        text=text,
        decision=decision,
        entities=entities,
    )


@app.route("/person/<path:name>")
def person_occurrences(name: str):
    docs = find_person_docs(name, limit=200)
    items: list[str] = []
    for d in docs:
        title = d.get("short_title") or d.get("file_name") or f"Doc {d['document_id']}"
        items.append(
            f'<li><a href="/legislation?file={d["file_name"]}">{title}</a> '
            f'({d.get("doc_number") or "—"})</li>'
        )
    return (
        f"<h2>الوثائق التي تحتوي: {name}</h2><ul>"
        f"{''.join(items) or '<li>لا يوجد</li>'}</ul>"
    )


def _edit_document(docs: dict[str, dict[str, str]], name: str, view_endpoint: str):
    if name not in docs:
        return "File not found", 404

    doc = docs.get(name, {})
    structure_path = doc.get('structure')

    is_decision = request.path.startswith('/decision')
    full_doc: dict | None = None
    structure: dict | None = None
    if structure_path and os.path.exists(structure_path):
        with open(structure_path, 'r', encoding='utf-8') as sf:
            loaded = json.load(sf)
        if is_decision and isinstance(loaded, dict) and 'decision' in loaded:
            full_doc = loaded
            structure = loaded.get('decision')
        else:
            structure = loaded
            full_doc = loaded

    text, entities, relations, txt_path, ner_path = _load_annotation(name)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save':
            content = request.form.get('content', '')
            try:
                text, entities = ae_parse_marked_text(content)
                _save_annotation(text, entities, relations, txt_path, ner_path, structure_path)
                return redirect(url_for(view_endpoint, file=name))
            except Exception as exc:
                return render_template(
                    'edit_annotations.html',
                    file=name,
                    data=structure,
                    raw=content,
                    entities=entities,
                    error=str(exc),
                )

        if action == 'add':
            args = SimpleNamespace(
                add=(request.form.get('start'), request.form.get('end'), request.form.get('type')),
                norm=request.form.get('norm'),
                text=request.form.get('text'),
            )
            ae_add_entity(args, text, entities)
            ae_fix_offsets(text, {'entities': entities})
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
            if request.form.get('text'):
                items.append(f"text={request.form.get('text')}")
            args = SimpleNamespace(update=items)
            ae_update_entity(args, entities)
            ae_fix_offsets(text, {'entities': entities})
            for ent in entities:
                if str(ent.get('id')) == uid:
                    try:
                        s = int(ent.get('start_char', -1))
                        e = int(ent.get('end_char', -1))
                    except Exception:
                        s = e = -1
                    if 0 <= s < e <= len(text):
                        ent['text'] = text[s:e]
                    break
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
        elif action == 'add_struct':
            key = request.form.get('category')
            val = request.form.get('text', '')
            if structure_path and full_doc and isinstance(full_doc, dict):
                target = full_doc.get('decision') if is_decision else full_doc
                if isinstance(target, dict):
                    lst = target.get(key)
                    if isinstance(lst, list):
                        lst.append(val)
                        with open(structure_path, 'w', encoding='utf-8') as sf:
                            json.dump(full_doc, sf, ensure_ascii=False, indent=2)
        elif action == 'delete_struct':
            key = request.form.get('category')
            idx = request.form.get('index')
            if structure_path and full_doc and isinstance(full_doc, dict):
                target = full_doc.get('decision') if is_decision else full_doc
                try:
                    i = int(idx)
                except Exception:
                    i = -1
                lst = target.get(key) if isinstance(target, dict) else None
                if isinstance(lst, list) and 0 <= i < len(lst):
                    del lst[i]
                    with open(structure_path, 'w', encoding='utf-8') as sf:
                        json.dump(full_doc, sf, ensure_ascii=False, indent=2)

        _save_annotation(text, entities, relations, txt_path, ner_path, structure_path)

        text, entities, relations, _, _ = _load_annotation(name)

        if structure_path and os.path.exists(structure_path):
            with open(structure_path, 'r', encoding='utf-8') as sf:
                loaded = json.load(sf)
            if is_decision and isinstance(loaded, dict):
                structure = loaded.get('decision')
                full_doc = loaded
            else:
                structure = loaded
                full_doc = loaded

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


@app.route('/legislation/edit', methods=['GET', 'POST'])
def edit_legislation():
    docs = _collect_legislation_documents()
    name = request.args.get('file')
    return _edit_document(docs, name, 'view_legislation')


@app.route('/legal_documents/edit', methods=['GET', 'POST'])
def edit_legal_document():
    docs = {k: {'structure': v} for k, v in _collect_legal_documents().items()}
    name = request.args.get('file')
    return _edit_document(docs, name, 'view_legal_documents')


@app.route('/decision/edit', methods=['GET', 'POST'])
def edit_decision():
    """Edit court decision documents from either source."""
    docs = _collect_legislation_documents()
    legal_docs = _collect_legal_documents()
    for k, v in legal_docs.items():
        docs.setdefault(k, {})['structure'] = v
    name = request.args.get('file')
    view = 'view_legal_documents' if name in legal_docs else 'view_legislation'
    return _edit_document(docs, name, view)


@app.route('/query', methods=['GET', 'POST'])
def run_query():
    """Execute a read-only SQL query against the database."""
    result_html = None
    error = None
    sql = ''
    if request.method == 'POST':
        sql = request.form.get('sql', '')
        try:
            with engine.connect() as con:
                df = pd.read_sql_query(sql, con)
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
