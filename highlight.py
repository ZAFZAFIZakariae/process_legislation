"""Shared utilities for highlighting entities in text."""

from __future__ import annotations

import html

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


# HTML construction logic shared by interfaces

def highlight_text(
    text: str,
    entities: list[dict],
    article_map: dict[str, str] | None = None,
    ref_targets: dict[str, list[str]] | None = None,
    tooltips: dict[str, str] | None = None,
    article_texts: dict[str, str] | None = None,
) -> str:
    """Return HTML for *text* with entity spans highlighted."""
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
