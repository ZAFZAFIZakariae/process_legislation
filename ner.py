import os
import json
import argparse
import tempfile
from typing import Dict, Any

import re
from datetime import datetime

try:
    import openai
except Exception:  # pragma: no cover - optional dependency may be missing

    class _Dummy:
        def __getattr__(self, name):
            raise RuntimeError("openai package is not available")

    openai = _Dummy()

try:
    from dateutil import parser as date_parser  # type: ignore
except Exception:  # pragma: no cover - optional dependency may be missing
    date_parser = None

try:
    from unidecode import unidecode  # type: ignore
except Exception:  # pragma: no cover - optional dependency may be missing

    def unidecode(text: str) -> str:  # type: ignore
        return text


try:  # Prefer relative import when available
    from .ocr import pdf_to_arabic_text
except Exception:
    try:
        from ocr import pdf_to_arabic_text  # type: ignore
    except Exception:

        def pdf_to_arabic_text(path: str) -> str:
            raise RuntimeError(
                "OCR functionality is unavailable in this environment"
            )


NER_PROMPT_FILE = os.path.join(
    os.path.dirname(__file__), "prompts", "ner_prompt.txt"
)
DEFAULT_MODEL = "gpt-3.5-turbo-16k"

openai.api_key = os.getenv("OPENAI_API_KEY", "DUMMY")


# Arabic to Western digit translation table
_DIGIT_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Map of Arabic month names to month numbers for simple date parsing
_MONTHS = {
    "يناير": 1,
    "فبراير": 2,
    "مارس": 3,
    "أبريل": 4,
    "ابريل": 4,
    "ماي": 5,
    "يونيو": 6,
    "يوليوز": 7,
    "غشت": 8,
    "شتنبر": 9,
    "أكتوبر": 10,
    "اكتوبر": 10,
    "نوفمبر": 11,
    "دجنبر": 12,
}


NAME_ENTITY_TYPES = {
    "PERSON",
    "JUDGE",
    "LAWYER",
    "COURT_CLERK",
    "ATTORNEY_GENERAL",
    "GOVERNMENT_BODY",
    "COURT",
    "AGENCY",
}

_FEMININE_FORMS = {
    "مديرة": "مدير",
    "قاضية": "قاضي",
    "محامية": "محامي",
    "رئيسة": "رئيس",
    "مستشارة": "مستشار",
    "كاتبة": "كاتب",
    "السيدة": "سيد",
    "سيدة": "سيد",
    "وزيرة": "وزير",
}


def _canonical_number(text: str) -> str | None:
    """Return digits from text as a canonical string."""
    if not isinstance(text, str):
        return None
    s = text.translate(_DIGIT_TRANS)
    m = re.search(r"\d+(?:[./]+[^\d]*\d+)*", s)
    if not m:
        return None
    digits = re.findall(r"\d+", m.group(0))
    seps = re.findall(r"[./]+", m.group(0))
    num = digits[0]
    for sep, d in zip(seps, digits[1:]):
        num += sep[0] + d
    return num


def _parse_date(text: str) -> str | None:
    """Parse Arabic or ISO date text to YYYY-MM-DD."""
    if not isinstance(text, str):
        return None
    s = text.translate(_DIGIT_TRANS)
    if date_parser is not None:
        try:
            dt = date_parser.parse(s, dayfirst=True, fuzzy=True)
            return dt.date().isoformat()
        except Exception:
            pass
    m = re.search(r"(\d{1,2})\s+(\S+)\s+(\d{4})", s)
    if m:
        day = int(m.group(1))
        month_name = m.group(2)
        year = int(m.group(3))
        month = _MONTHS.get(month_name)
        if month:
            try:
                return datetime(year, month, day).strftime("%Y-%m-%d")
            except Exception:
                pass
    try:
        return datetime.fromisoformat(s.strip()).strftime("%Y-%m-%d")
    except Exception:
        return None


def normalize_arabic(text: str) -> str:
    """Simplistic normalization for Arabic names."""
    tokens: list[str] = []
    for word in text.split():
        w = word
        if w.startswith("ال") and len(w) > 2:
            w = w[2:]
        if w in _FEMININE_FORMS:
            w = _FEMININE_FORMS[w]
        elif w.endswith("وات"):
            w = w[:-3] + "ة"
        elif w.endswith("ات"):
            w = w[:-2] + "ة"
        elif w.endswith("ون") or w.endswith("ين"):
            w = w[:-2]
        tokens.append(w)
    return " ".join(tokens)


def normalize_entities(result: Dict[str, Any]) -> None:
    """Populate missing normalized values for entities in-place."""
    for ent in result.get("entities", []):
        typ = ent.get("type")
        text = ent.get("text", "")
        if ent.get("normalized") and typ not in {
            "LAW",
            "DECRET",
            "ARTICLE",
            "CHAPTER",
            "SECTION",
        }:
            continue
        norm: str | None = None
        if typ == "DATE":
            norm = _parse_date(text)
        elif typ in {"LAW", "DECRET"}:
            num = _canonical_number(text)
            if num:
                # include the Arabic legal type when available
                if "ظهير" in text:
                    norm = f"{num} الظهير الشريف"
                elif "القانون التنظيمي" in text:
                    norm = f"{num} القانون التنظيمي"
                elif "القانون" in text:
                    norm = f"{num} القانون"
                elif "دستور" in text:
                    norm = f"{num} الدستور"
                elif "مرسوم" in text:
                    norm = f"{num} المرسوم"
                elif "قرار" in text:
                    norm = f"{num} القرار"
                else:
                    norm = num
        elif typ in {"ARTICLE", "CHAPTER", "SECTION"}:
            nums = re.findall(r"[0-9٠-٩]+", text.translate(_DIGIT_TRANS))
            if "المادة" in text or "مادة" in text or "المواد" in text or "مواد" in text or "المادتين" in text:
                heading = "المادة"
            elif "الفصل" in text or "فصل" in text or "الفصول" in text or "فصول" in text or "الفصلين" in text:
                heading = "الفصل"
            elif "الباب" in text or "باب" in text:
                heading = "الباب"
            elif "القسم" in text or "قسم" in text:
                heading = "القسم"
            else:
                heading = {
                    "ARTICLE": "الفصل",
                    "CHAPTER": "الباب",
                    "SECTION": "القسم",
                }.get(typ, "")
            if len(nums) > 1:
                joined = "_".join(str(int(n)) for n in nums)
                norm = f"{heading} {joined}" if heading else joined
            else:
                num = _canonical_number(text)
                if num:
                    norm = f"{num} {heading}" if heading else num
        elif typ in {"OFFICIAL_JOURNAL", "CASE"}:
            norm = _canonical_number(text)
        elif typ in NAME_ENTITY_TYPES:
            cleaned = normalize_arabic(text)
            norm = unidecode(cleaned) if cleaned else ""
        else:
            norm = unidecode(text) if text else ""
        if norm:
            ent["normalized"] = norm


def fix_entity_offsets(text: str, result: Dict[str, Any]) -> None:
    """Correct misaligned start/end offsets for entities in-place."""
    entities = result.get("entities", [])
    used: list[tuple[int, int]] = []

    def _overlaps(r1: tuple[int, int], r2: tuple[int, int]) -> bool:
        return not (r1[1] <= r2[0] or r1[0] >= r2[1])

    for ent in entities:
        ent_text = str(ent.get("text", ""))
        try:
            start = int(ent.get("start_char", -1))
            end = int(ent.get("end_char", -1))
        except Exception:
            start = -1
            end = -1

        if not ent_text:
            continue
        if start == -1 or end == -1:
            # skip entities with unknown offsets
            continue

        # if the current offsets already match an unused occurrence keep them
        if (
            0 <= start < end <= len(text)
            and text[start:end] == ent_text
            and not any(_overlaps((start, end), r) for r in used)
        ):
            used.append((start, end))
            continue

        # search for the entity text within ±50 characters of the original start
        search_start = max(0, start - 50)
        search_end = min(len(text), start + 50 + len(ent_text))
        snippet = text[search_start:search_end]

        occs: list[tuple[int, int]] = []
        idx = snippet.find(ent_text)
        while idx != -1:
            occs.append((search_start + idx, search_start + idx + len(ent_text)))
            idx = snippet.find(ent_text, idx + 1)

        def _assign_from(occurrences: list[tuple[int, int]]) -> bool:
            occurrences.sort(key=lambda r: abs(r[0] - start))
            for s, e in occurrences:
                if not any(_overlaps((s, e), r) for r in used):
                    ent["start_char"] = s
                    ent["end_char"] = e
                    used.append((s, e))
                    return True
            return False

        found = _assign_from(occs)
        if not found:
            occs = []
            idx = text.find(ent_text)
            while idx != -1:
                occs.append((idx, idx + len(ent_text)))
                idx = text.find(ent_text, idx + 1)
            if occs:
                _assign_from(occs)


def expand_article_ranges(text: str, result: Dict[str, Any]) -> None:
    """Detect ranges like 'من 7 إلى 12' and create ARTICLE entities."""
    entities = result.setdefault("entities", [])
    relations = result.setdefault("relations", [])

    seq: dict[str, int] = {}

    def next_id(typ: str, canonical: str) -> str:
        base = f"{typ}_{canonical}"
        seq[base] = seq.get(base, 0) + 1
        return f"{base}_{seq[base]}"

    # Initialize counters from existing IDs
    for e in entities:
        m = re.match(r"([A-Z_]+_[^_]+)_(\\d+)$", str(e.get("id", "")))
        if m:
            base = m.group(1)
            num = int(m.group(2))
            if num > seq.get(base, 0):
                seq[base] = num

    art_map: dict[str, str] = {}
    for e in entities:
        if e.get("type") == "ARTICLE":
            canon_num = _canonical_number(
                e.get("normalized") or e.get("text", "")
            )
            if canon_num:
                art_map.setdefault(canon_num, e.get("id"))

    pattern = re.compile(
        r"من\s+(?:الفصل\s+)?([0-9٠-٩]+)\s+(?:إ?لى|الى)\s+(?:الفصل\s+)?([0-9٠-٩]+)"
    )

    for m in pattern.finditer(text):
        start = _canonical_number(m.group(1))
        end = _canonical_number(m.group(2))
        if not start or not end:
            continue
        a = int(start)
        b = int(end)
        if a > b:
            a, b = b, a
        canonical = f"{a}-{b}"
        ref_id = next_id("INTERNAL_REF", canonical)
        entities.append(
            {
                "id": ref_id,
                "type": "INTERNAL_REF",
                "text": m.group(0),
                "start_char": m.start(),
                "end_char": m.end(),
                "normalized": f"الفصل {canonical}",
            }
        )

        num_positions: dict[str, tuple[int, int]] = {}
        for dm in re.finditer(r"[0-9٠-٩]+", m.group(0)):
            canon = _canonical_number(dm.group(0))
            if canon:
                num_positions[str(int(canon))] = (
                    m.start() + dm.start(),
                    m.start() + dm.end(),
                )

        for num in range(a, b + 1):
            num_str = str(num)
            art_id = art_map.get(num_str)
            if not art_id:
                art_id = next_id("ARTICLE", num_str)
                s, e = num_positions.get(num_str, (-1, -1))
                entities.append(
                    {
                        "id": art_id,
                        "type": "ARTICLE",
                        "text": num_str,
                        "start_char": s,
                        "end_char": e,
                    }
                )
                art_map[num_str] = art_id
            relations.append(
                {
                    "relation_id": f"REL_refers_to_{ref_id}_{art_id}",
                    "type": "refers_to",
                    "source_id": ref_id,
                    "target_id": art_id,
                }
            )


def expand_article_lists(text: str, result: Dict[str, Any]) -> None:
    """Detect lists like 'الفصلين 25 و29' or 'الفصول: 1، 3، 4'."""
    entities = result.setdefault("entities", [])
    relations = result.setdefault("relations", [])

    seq: dict[str, int] = {}

    def next_id(typ: str, canonical: str) -> str:
        base = f"{typ}_{canonical}"
        seq[base] = seq.get(base, 0) + 1
        return f"{base}_{seq[base]}"

    # Initialize ID counters from existing entities
    for e in entities:
        m = re.match(r"([A-Z_]+_[^_]+)_(\d+)$", str(e.get("id", "")))
        if m:
            base = m.group(1)
            num = int(m.group(2))
            if num > seq.get(base, 0):
                seq[base] = num

    art_map: dict[str, str] = {}
    for e in entities:
        if e.get("type") == "ARTICLE":
            canon_num = _canonical_number(e.get("normalized") or e.get("text", ""))
            if canon_num:
                art_map.setdefault(canon_num, e.get("id"))

    pattern = re.compile(
        r"(?:الفصلين|الفصول)\s*:?[\s\u00A0]*((?:[0-9٠-٩]+(?:\s*[،,]\s*|\s*و\s*))*[0-9٠-٩]+)"
    )

    for m in pattern.finditer(text):
        num_text = m.group(1)
        nums_with_pos: list[tuple[str, int, int]] = []
        for nm in re.finditer(r"[0-9٠-٩]+", num_text):
            c = _canonical_number(nm.group(0))
            if c:
                nums_with_pos.append(
                    (
                        str(int(c)),
                        m.start(1) + nm.start(),
                        m.start(1) + nm.end(),
                    )
                )
        nums = [n for n, _, _ in nums_with_pos]
        if not nums:
            continue
        joined = "_".join(nums)
        ref_id = next_id("INTERNAL_REF", joined)
        entities.append(
            {
                "id": ref_id,
                "type": "INTERNAL_REF",
                "text": m.group(0),
                "start_char": m.start(),
                "end_char": m.end(),
                "normalized": f"الفصل {joined}",
            }
        )

        for num, s_pos, e_pos in nums_with_pos:
            art_id = art_map.get(num)
            if not art_id:
                art_id = next_id("ARTICLE", num)
                entities.append(
                    {
                        "id": art_id,
                        "type": "ARTICLE",
                        "text": num,
                        "start_char": s_pos,
                        "end_char": e_pos,
                    }
                )
                art_map[num] = art_id
            relations.append(
                {
                    "relation_id": f"REL_refers_to_{ref_id}_{art_id}",
                    "type": "refers_to",
                    "source_id": ref_id,
                    "target_id": art_id,
                }
            )


def _remove_overlapping_articles(result: Dict[str, Any]) -> None:
    """Remove ARTICLE entities fully contained in INTERNAL_REF spans."""
    entities = result.get("entities", [])
    ref_ranges = [
        (
            int(e.get("start_char", -1)),
            int(e.get("end_char", -1)),
        )
        for e in entities
        if e.get("type") == "INTERNAL_REF"
    ]
    if not ref_ranges:
        return

    cleaned: list[dict] = []
    removed_ids: set[str] = set()
    for e in entities:
        start = int(e.get("start_char", -1))
        end = int(e.get("end_char", -1))
        if e.get("type") == "ARTICLE":
            text = str(e.get("text", ""))
            nums = re.findall(r"[0-9٠-٩]+", text.translate(_DIGIT_TRANS))
            contained = any(rs <= start and end <= re for rs, re in ref_ranges)
            overlaps = any(not (end <= rs or start >= re) for rs, re in ref_ranges)
            if contained or (len(nums) > 1 and overlaps):
                removed_ids.add(str(e.get("id")))
                continue
        cleaned.append(e)
    result["entities"] = cleaned

    if removed_ids:
        relations = result.get("relations", [])
        result["relations"] = [
            r
            for r in relations
            if str(r.get("source_id")) not in removed_ids
            and str(r.get("target_id")) not in removed_ids
        ]


def remove_articles_inside_dates(result: Dict[str, Any]) -> None:
    """Remove ARTICLE entities whose offsets fall completely within a DATE span."""
    entities = result.get("entities", [])
    date_ranges = [
        (
            int(e.get("start_char", -1)),
            int(e.get("end_char", -1)),
        )
        for e in entities
        if e.get("type") == "DATE"
    ]
    if not date_ranges:
        return
    cleaned: list[dict] = []
    for e in entities:
        start = int(e.get("start_char", -1))
        end = int(e.get("end_char", -1))
        if e.get("type") == "ARTICLE" and any(ds <= start and end <= de for ds, de in date_ranges):
            continue
        cleaned.append(e)
    result["entities"] = cleaned


def assign_numeric_ids(result: Dict[str, Any]) -> None:
    """Replace entity and relation IDs with simple incremental numbers."""
    entities = result.get("entities", [])
    relations = result.get("relations", [])
    id_map: dict[str, int] = {}
    for idx, ent in enumerate(entities, start=1):
        old = str(ent.get("id", ""))
        id_map[old] = idx
        ent["id"] = idx
    for idx, rel in enumerate(relations, start=1):
        rel["relation_id"] = idx
        src = str(rel.get("source_id", ""))
        tgt = str(rel.get("target_id", ""))
        rel["source_id"] = id_map.get(src, src)
        rel["target_id"] = id_map.get(tgt, tgt)


def postprocess_result(text: str, result: Dict[str, Any]) -> None:
    """Apply post-processing steps to raw NER result."""
    expand_article_ranges(text, result)
    expand_article_lists(text, result)
    fix_entity_offsets(text, result)
    remove_articles_inside_dates(result)
    _remove_overlapping_articles(result)
    normalize_entities(result)
    assign_numeric_ids(result)


def load_prompt(text: str) -> str:
    with open(NER_PROMPT_FILE, "r", encoding="utf-8") as f:
        prompt = f.read()
    return prompt.replace("{{TEXT}}", text)


def call_openai(prompt: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": "You extract named entities from Moroccan legal text.",
        },
        {"role": "user", "content": prompt},
    ]
    resp = openai.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content
    return json.loads(content)


def extract_entities(text: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    prompt = load_prompt(text)
    return call_openai(prompt, model)


def extract_from_file(
    path: str, model: str = DEFAULT_MODEL
) -> tuple[Dict[str, Any], str]:
    if path.lower().endswith(".pdf"):
        text = pdf_to_arabic_text(path)
    else:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    result = extract_entities(text, model)
    postprocess_result(text, result)
    return result, text


def save_as_csv(result: Dict[str, Any], output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    entities = result.get("entities", [])
    relations = result.get("relations", [])
    ent_path = os.path.join(output_dir, "entities.csv")
    rel_path = os.path.join(output_dir, "relations.csv")
    import csv

    with open(ent_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "type",
                "text",
                "start_char",
                "end_char",
                "normalized",
            ],
        )
        writer.writeheader()
        for e in entities:
            writer.writerow(
                {
                    "id": e.get("id", ""),
                    "type": e.get("type", ""),
                    "text": e.get("text", ""),
                    "start_char": e.get("start_char", ""),
                    "end_char": e.get("end_char", ""),
                    "normalized": e.get("normalized", ""),
                }
            )
    with open(rel_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["relation_id", "type", "source_id", "target_id"]
        )
        writer.writeheader()
        for r in relations:
            writer.writerow(
                {
                    "relation_id": r.get("relation_id", ""),
                    "type": r.get("type", ""),
                    "source_id": r.get("source_id", ""),
                    "target_id": r.get("target_id", ""),
                }
            )
    print(f"[+] Saved entities to {ent_path}")
    print(f"[+] Saved relations to {rel_path}")


def text_with_markers(text: str, entities: list[dict]) -> str:
    """Return *text* with entity spans wrapped in explicit markers."""
    parts: list[str] = []
    last = 0
    for ent in sorted(entities, key=lambda e: int(e.get("start_char", 0))):
        try:
            start = int(ent.get("start_char", -1))
            end = int(ent.get("end_char", -1))
        except Exception:
            continue
        if start < last or start < 0 or end <= start or end > len(text):
            continue
        parts.append(text[last:start])
        attrs: list[str] = [f"id={ent.get('id')}", f"type={ent.get('type')}"]
        norm = ent.get("normalized")
        if norm:
            esc = str(norm).replace('"', "\\\"")
            attrs.append(f"norm=\"{esc}\"")
        attr_str = " ".join(attrs)
        parts.append(f"[[ENT {attr_str}]]{text[start:end]}[[/ENT]]")
        last = end
    parts.append(text[last:])
    return "".join(parts)


def parse_marked_text(marked: str) -> tuple[str, list[dict]]:
    """Return plain text and entity list from *marked* text."""
    text_parts: list[str] = []
    entities: list[dict] = []
    pos = 0
    out_pos = 0
    pattern = re.compile(r"\[\[ENT([^\]]*)\]\]")
    end_pat = re.compile(r"\[\[/ENT\]\]")
    while True:
        m = pattern.search(marked, pos)
        if not m:
            text_parts.append(marked[pos:])
            break
        text_parts.append(marked[pos:m.start()])
        attr_txt = m.group(1).strip()
        attr: dict[str, str] = {}
        for am in re.finditer(r"(\w+)=('([^']*)'|\"([^\"]*)\"|\S+)", attr_txt):
            key = am.group(1)
            val = am.group(3) or am.group(4) or am.group(2)
            attr[key] = val
        close = end_pat.search(marked, m.end())
        if not close:
            break
        span_text = marked[m.end(): close.start()]
        start_char = out_pos
        end_char = out_pos + len(span_text)
        entities.append(
            {
                "id": attr.get("id"),
                "type": attr.get("type"),
                "text": span_text,
                "start_char": start_char,
                "end_char": end_char,
                "normalized": attr.get("norm"),
            }
        )
        text_parts.append(span_text)
        out_pos = end_char
        pos = close.end()
    plain = "".join(text_parts)
    return plain, entities


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract legal NER using OpenAI"
    )
    parser.add_argument(
        "--input", required=True, help="Path to a PDF or text file"
    )
    parser.add_argument(
        "--output_dir", required=True, help="Directory for CSV output"
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help="OpenAI model name"
    )
    parser.add_argument(
        "--annotate_text",
        action="store_true",
        help="Save annotated text with entity markers",
    )
    args = parser.parse_args()

    result, text = extract_from_file(args.input, args.model)
    out_json = os.path.join(args.output_dir, "ner_result.json")
    os.makedirs(args.output_dir, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[+] Saved raw JSON to {out_json}")

    save_as_csv(result, args.output_dir)

    if args.annotate_text:
        annotated = text_with_markers(text, result.get("entities", []))
        path = os.path.join(args.output_dir, "annotated.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(annotated)
        print(f"[+] Saved annotated text to {path}")


if __name__ == "__main__":
    main()
