"""Shared utilities for highlighting entities in text."""

from __future__ import annotations

import html
import re

try:  # Allow using within package or standalone
    from .ner import parse_marked_text  # type: ignore
except Exception:  # pragma: no cover - fallback
    try:
        from ner import parse_marked_text  # type: ignore
    except Exception:
        parse_marked_text = None

_DIGIT_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def canonical_num(value: str) -> str | None:
    """Extract a canonical digit sequence from *value* or return None."""
    if not isinstance(value, str):
        return None
    s = value.translate(_DIGIT_TRANS)
    import re

    m = re.search(r"\d+(?:[./]+[^\d]*\d+)*", s)
    if not m:
        return None
    digits = re.findall(r"\d+", m.group(0))
    seps = re.findall(r"[./]+", m.group(0))
    result = digits[0]
    for sep, d in zip(seps, digits[1:]):
        result += sep[0] + d
    return result


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


def render_ner_html(text: str, result: dict) -> str:
    """Return highlighted HTML for *text* given a NER *result* dict."""
    entities = result.get("entities", [])
    relations = result.get("relations", [])
    ref_targets: dict[str, list[str]] = {}
    tooltips: dict[str, str] = {}
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
                existing = tooltips.get(src)
                if existing:
                    tooltips[src] = "<br/>".join([existing, msg])
                else:
                    tooltips[src] = msg
    return highlight_text(text, entities, None, ref_targets, tooltips, None)


# HTML construction logic shared by interfaces

def highlight_text(
    text: str,
    entities: list[dict] | None = None,
    article_map: dict[str, str] | None = None,
    ref_targets: dict[str, list[str]] | None = None,
    tooltips: dict[str, str] | None = None,
    article_texts: dict[str, str] | None = None,
) -> str:
    """Return HTML for *text* with entity spans highlighted."""
    if "[[ENT" in text and parse_marked_text is not None:
        text, parsed = parse_marked_text(text)
        entities = parsed
    if entities is None:
        entities = []
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
        ent_text = str(ent.get("text", ""))
        if (
            start < last
            or start < 0
            or end <= start
            or start >= len(text)
            or end > len(text)
        ):
            continue

        # verify substring matches entity text
        if text[start:end] != ent_text:
            search_start = max(0, start - 50)
            search_end = min(len(text), start + 50 + len(ent_text))
            snippet = text[search_start:search_end]
            occs: list[tuple[int, int]] = []
            idx = snippet.find(ent_text)
            while idx != -1:
                occs.append((search_start + idx, search_start + idx + len(ent_text)))
                idx = snippet.find(ent_text, idx + 1)
            if not occs:
                # skip highlighting this entity
                continue
            occs.sort(key=lambda r: abs(r[0] - start))
            start, end = occs[0]
            if start < last or end > len(text) or end <= start:
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
        if article_texts is not None:
            art = None
            if ent.get("type") == "ARTICLE":
                num = canonical_num(ent.get("normalized") or ent.get("text"))
                if num is not None:
                    art = article_texts.get(num)
            if art is None:
                art = article_texts.get(f"ID_{ent.get('id')}")
            if art:
                art = re.sub(r"<([^,<>]+), id:[^>]+>", r"<mark>\1</mark>", art)
                art = art.replace("\n", "<br/>")
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


def _highlight_entities_simple(text: str, entities: list[dict]) -> str:
    """Insert ``<mark>`` tags around entity substrings in *text*.

    Offsets from the NER model are relative to the full document which makes
    them hard to apply to individual article snippets.  For highlighting inside
    structured JSON we simply search for entity texts within the snippet and
    wrap each occurrence in ``<mark>`` tags.  Longer entity texts are matched
    first to avoid partially highlighting nested names.
    """

    patterns = [re.escape(e.get("text", "")) for e in entities if e.get("text")]
    if not patterns:
        return text
    # Match longer entities before shorter ones to minimise partial matches.
    patterns.sort(key=len, reverse=True)
    regex = re.compile("|".join(patterns))

    def repl(match: re.Match[str]) -> str:
        return f"<mark>{match.group(0)}</mark>"

    return regex.sub(repl, text)


def highlight_structure(structure: list[dict], entities: list[dict]) -> None:
    """Recursively highlight entity mentions within *structure* in-place."""

    for node in structure:
        text = node.get("text")
        if isinstance(text, str):
            node["text"] = _highlight_entities_simple(text, entities)
        title = node.get("title")
        if isinstance(title, str):
            node["title"] = _highlight_entities_simple(title, entities)
        children = node.get("children")
        if children:
            highlight_structure(children, entities)
