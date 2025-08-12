import os
import re
import json
import copy

import tiktoken
import openai

# ------------------------------------------------------------
# API key setup
# ------------------------------------------------------------
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    print("\u26a0\ufe0f  OPENAI_API_KEY not set; using dummy key for offline mode.")
    openai.api_key = "DUMMY"

# ------------------------------------------------------------
# Model configuration
# ------------------------------------------------------------
GPT_MODEL = "gpt-3.5-turbo-16k"
MAX_CONTEXT = 16_384
MODEL_MAX_COMPLETION = 12_000
PASS1_MAX_TOKENS = 8_000


def adjust_for_model(name: str) -> None:
    """Update global token limits for the chosen model."""
    global GPT_MODEL, MAX_CONTEXT, MODEL_MAX_COMPLETION
    GPT_MODEL = name
    if name == "gpt-3.5-turbo":
        MAX_CONTEXT = 4_096
        MODEL_MAX_COMPLETION = 3_000
    elif name == "gpt-3.5-turbo-16k":
        MAX_CONTEXT = 16_384
        MODEL_MAX_COMPLETION = 12_000
    elif name.startswith("gpt-4-turbo") or name.startswith("gpt-4o"):
        MAX_CONTEXT = 128_000
        MODEL_MAX_COMPLETION = 4_000
    elif name.startswith("gpt-4"):
        MAX_CONTEXT = 8_192
        MODEL_MAX_COMPLETION = 4_000
    else:
        MAX_CONTEXT = 16_384
        MODEL_MAX_COMPLETION = 12_000


# ------------------------------------------------------------
# Prompt loading
# ------------------------------------------------------------

def load_prompts() -> tuple[str, str]:
    """Return the contents of prompt_1.txt and prompt_2.txt.

    When the pipeline modules are executed directly, the current file lives
    inside ``pipeline/`` while the prompts folder sits at the repository
    root. We therefore try ``pipeline/prompts`` first and fall back to the
    parent directory if the files are missing.
    """

    here = os.path.dirname(__file__)
    base = os.path.join(here, "prompts")
    if not os.path.exists(os.path.join(base, "prompt_1.txt")):
        base = os.path.join(here, "..", "prompts")

    with open(os.path.join(base, "prompt_1.txt"), "r", encoding="utf-8") as f1:
        p1 = f1.read()
    with open(os.path.join(base, "prompt_2.txt"), "r", encoding="utf-8") as f2:
        p2 = f2.read()

    if "====FIRST_CHUNK====" not in p1:
        raise RuntimeError("'====FIRST_CHUNK====' not found in prompt_1.txt")
    pass1 = p1.split("====FIRST_CHUNK====", 1)[1].strip()

    if "====SUBSEQUENT_CHUNK====" not in p2:
        raise RuntimeError("'====SUBSEQUENT_CHUNK====' not found in prompt_2.txt")
    pass2 = p2.split("====SUBSEQUENT_CHUNK====", 1)[1].strip()

    return pass1, pass2


pass1_instructions, pass2_instructions = load_prompts()

# ------------------------------------------------------------
# Type helpers
# ------------------------------------------------------------
ARTICLE_TYPE_MAP = {
    "الفصل": "فصل",
    "فصل": "فصل",
    "المادة": "مادة",
    "مادة": "مادة",
    "القسم": "قسم",
    "قسم": "قسم",
    "الباب": "باب",
    "باب": "باب",
    "الجزء": "جزء",
    "جزء": "جزء",
    "الفرع": "فرع",
    "فرع": "فرع",
}
ARTICLE_TYPES = set(ARTICLE_TYPE_MAP.keys())

_DIGIT_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

_ORDINAL_MAP = {
    "الأول": "1",
    "الأولى": "1",
    "الثاني": "2",
    "الثانية": "2",
    "الثالث": "3",
    "الثالثة": "3",
    "الرابع": "4",
    "الرابعة": "4",
    "الخامس": "5",
    "الخامسة": "5",
    "السادس": "6",
    "السادسة": "6",
    "السابع": "7",
    "السابعة": "7",
    "الثامن": "8",
    "الثامنة": "8",
    "التاسع": "9",
    "التاسعة": "9",
    "العاشر": "10",
    "العاشرة": "10",
    "الحادي عشر": "11",
    "الحادية عشرة": "11",
    "الثاني عشر": "12",
    "الثانية عشرة": "12",
    "الثالث عشر": "13",
    "الثالثة عشرة": "13",
    "الرابع عشر": "14",
    "الرابعة عشرة": "14",
    "تمهيدي": "0",
    "تمهيدية": "0",
}


def ordinal_to_int(val: str) -> int | None:
    if not isinstance(val, str):
        return None
    s = val.strip()
    mapped = _ORDINAL_MAP.get(s)
    if mapped is not None:
        s = mapped
    try:
        return int(s)
    except ValueError:
        return None


def canonical_type(t: str) -> str:
    if not isinstance(t, str):
        return ""
    s = t.strip()
    if s.startswith("ال"):
        s = s[2:]
    return ARTICLE_TYPE_MAP.get(s, s)


HEADER_LINES = {
    "مديرية التشريع والدراسات",
    "مديرية التشريع والدرامات",
    "وزارة العدل",
    "المملكة المغربية",
}


def clean_ocr_lines(text: str) -> str:
    cleaned: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s in HEADER_LINES:
            continue
        # Remove standalone page numbers like ``- 12 -`` or ``12``
        if re.match(r"^-?\s*\d+\s*-?$", s):
            continue
        # Drop lines that begin with a numeric footnote marker such as
        # ``8 - تم تغيير ...``.  These annotations are not part of the
        # legislative text and can confuse downstream parsing which may glue
        # the footnote digit to the article number (e.g. producing ``814``
        # instead of ``14``).
        if re.match(r"^\d+\s*-\s+", s):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def count_tokens_for_messages(messages: list[dict], model: str) -> int:
    encoding = tiktoken.encoding_for_model(model)
    total = 0
    for msg in messages:
        total += 4
        total += len(encoding.encode(msg["role"]))
        total += len(encoding.encode(msg["content"]))
    total += 2
    return total


# ------------------------------------------------------------
# Chunk splitting
# ------------------------------------------------------------

def split_for_pass1(arabic_text: str) -> str:
    enc = tiktoken.encoding_for_model(GPT_MODEL)
    tokens = enc.encode(arabic_text)
    prompt_msgs = [
        {"role": "system", "content": "You are an expert in Moroccan legislation text structuring."},
        {"role": "user", "content": pass1_instructions + "\n"},
    ]
    prompt_tokens = count_tokens_for_messages(prompt_msgs, GPT_MODEL)
    reply_reserve = 1000 if MAX_CONTEXT <= 4_096 else 500
    available = MAX_CONTEXT - prompt_tokens - reply_reserve
    slice_len = max(0, min(len(tokens), available, PASS1_MAX_TOKENS))
    slice_tokens = tokens[:slice_len]
    return enc.decode(slice_tokens)


def smart_token_split(arabic_text: str, token_limit: int, model: str) -> list[str]:
    enc = tiktoken.encoding_for_model(model)
    tokens = enc.encode(arabic_text)
    chunks = []
    idx = 0
    total = len(tokens)
    while idx < total:
        end = min(idx + token_limit, total)
        slice_tokens = tokens[idx:end]
        slice_text = enc.decode(slice_tokens)
        cut = slice_text.rfind("\n")
        if cut < 0:
            for punct in ["۔", "؟", ".", "!", ";"]:
                pos = slice_text.rfind(punct)
                if pos > cut:
                    cut = pos
        if 0 <= cut < len(slice_text) - 1:
            prefix = slice_text[:cut+1]
            prefix_tokens = enc.encode(prefix)
            actual_end = idx + len(prefix_tokens)
        else:
            actual_end = end
        chunk = enc.decode(tokens[idx:actual_end])
        chunks.append(chunk)
        idx = actual_end
    return chunks


def compute_pass2_chunk_limit() -> int:
    dummy = build_messages_for_pass2("", "")
    overhead = count_tokens_for_messages(dummy, GPT_MODEL)
    reply_reserve = 1500 if MAX_CONTEXT <= 4_096 else 500
    available = MAX_CONTEXT - overhead - reply_reserve
    if MAX_CONTEXT <= 4_096:
        available = min(2000, available)
    elif GPT_MODEL == "gpt-3.5-turbo-16k":
        available = min(3000, available)
    elif MODEL_MAX_COMPLETION <= 4_000:
        available = min(3000, available)
    return max(100, min(5000, available))


def split_for_pass2(arabic_text: str) -> list[str]:
    enc = tiktoken.encoding_for_model(GPT_MODEL)
    tokens = enc.encode(arabic_text)
    chunk_limit = compute_pass2_chunk_limit()
    overlap = 256 if MAX_CONTEXT <= 4_096 else 256
    chunk_limit = max(100, chunk_limit - overlap)
    chunks = []
    i = 0
    prev_tail = []
    total = len(tokens)
    while i < total:
        window = prev_tail + tokens[i : min(i + chunk_limit, total)]
        if not window:
            break
        combined_text = enc.decode(window)
        subchunks = smart_token_split(combined_text, chunk_limit, GPT_MODEL)
        if subchunks:
            this_chunk = subchunks[0]
            chunk_tokens = enc.encode(this_chunk)
            if prev_tail:
                chunk_tokens = chunk_tokens[len(prev_tail):]
                this_chunk = enc.decode(chunk_tokens)
        else:
            # Fallback to using the raw window if smart split produced nothing
            chunk_tokens = window[len(prev_tail):] if prev_tail else window
            this_chunk = enc.decode(chunk_tokens)
        if not chunk_tokens:
            break
        chunks.append(this_chunk)
        prev_tail = chunk_tokens[-overlap:] if overlap else []
        i += len(chunk_tokens)
    return chunks

# ------------------------------------------------------------
# Message building and GPT interaction
# ------------------------------------------------------------

def build_messages_for_pass1(arabic_chunk: str) -> list[dict]:
    return [
        {"role": "system", "content": "You are an expert in Moroccan legislation text structuring."},
        {"role": "user", "content": pass1_instructions + "\n" + arabic_chunk + "\n<--- END ARABIC FIRST CHUNK."},
    ]


def build_messages_for_pass2(arabic_chunk: str, inherited: str = "") -> list[dict]:
    user_content = inherited + arabic_chunk
    return [
        {"role": "system", "content": "You are an expert in Moroccan legislation text structuring."},
        {"role": "user", "content": pass2_instructions + "\n" + user_content + "\n<--- END ARABIC SECOND CHUNK."},
    ]


def call_gpt_on_chunk(messages: list[dict], json_mode: bool = True) -> str:
    used = count_tokens_for_messages(messages, GPT_MODEL)
    remain = MAX_CONTEXT - used
    if remain <= 0:
        raise ValueError("No token budget left for GPT reply; prompt is too large.")
    max_completion = min(remain, MODEL_MAX_COMPLETION)
    params = {
        "model": GPT_MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_completion,
    }
    if json_mode:
        params["response_format"] = {"type": "json_object"}
    resp = openai.chat.completions.create(**params)
    content = resp.choices[0].message.content
    return content.strip() if isinstance(content, str) else content


def repair_chunk_json(raw: str) -> list | None:
    repair_messages = [
        {"role": "system", "content": "You fix malformed JSON arrays from Moroccan legislation extraction."},
        {"role": "user", "content": "Return a JSON object {\"result\": [...]}. If the array can't be recovered, use an empty array.\n" + str(raw)},
    ]
    try:
        fixed = call_gpt_on_chunk(repair_messages, json_mode=True)
        obj = json.loads(fixed) if isinstance(fixed, str) else fixed
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict) and isinstance(obj.get("result"), list):
            return obj["result"]
    except Exception as e:
        print(f"[Debug] repair_chunk_json failed: {e}")
    return None


def extract_inherited(reply: str) -> tuple[str, str]:
    text = reply.lstrip()
    if text.startswith("Inherited context:"):
        line, _, rest = text.partition("\n")
        return line.strip(), rest.lstrip()
    return "", reply


def parse_inherited_fields(line: str) -> dict | None:
    match = re.match(r"Inherited context:\s*type=([^,]+),\s*number=([^,]+),\s*title=\"([^\"]*)\"", line)
    if match:
        return {"type": match.group(1).strip(), "number": match.group(2).strip(), "title": match.group(3).strip()}
    return None


def remove_code_fences(text: str) -> str:
    if not isinstance(text, str):
        return text
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```\s*$', '', text)
    return text.strip()

# ------------------------------------------------------------
# Tree helpers
# ------------------------------------------------------------

def find_node(tree: list, typ: str, num: str) -> dict | None:
    typ = canonical_type(typ)
    for n in tree:
        if canonical_type(n.get("type")) == typ and str(n.get("number")) == str(num):
            return n
        child = find_node(n.get("children", []), typ, num)
        if child:
            return child
    return None


def clean_number(node: dict) -> None:
    if node.get("type") in ARTICLE_TYPES:
        num = node.get("number")
        if isinstance(num, int):
            node["number"] = str(num)
            return
        if isinstance(num, str):
            num = re.sub(r"^(?:الفصل|فصل|المادة|مادة|الباب|باب|القسم|قسم|الجزء|جزء)\s*", "", num).strip()
            num = num.translate(_DIGIT_TRANS)
            if num == "تمهيدي":
                num = "0"
            num = _ORDINAL_MAP.get(num, num)
            digits = re.search(r"\d+", num)
            if digits:
                node["number"] = str(int(digits.group(0)))
            else:
                try:
                    node["number"] = str(int(num))
                except Exception:
                    node["number"] = num


def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = re.sub(r"[A-Za-z]+", "", text)
    text = re.sub(r"\n\s*\d+\s*\n", "\n", text)
    text = re.sub(r"(?:مديرية التشريع والدراسات|مديرية التشريع والدرامات|وزارة العدل|المملكة المغربية)", "", text)
    text = re.sub(r"^-?\s*\d+\s*-?$", "", text, flags=re.MULTILINE)
    return text.strip()


def finalize_structure(tree: list, seen: set | None = None) -> None:
    """Normalise numbers and keep text for all nodes."""

    if seen is None:
        seen = set()
    for node in tree:
        if id(node) in seen:
            continue
        seen.add(id(node))
        node.pop("_placeholder", None)
        node["type"] = canonical_type(node.get("type", ""))
        if node.get("type") in ARTICLE_TYPES and node.get("number") is not None:
            node["number"] = str(node.get("number"))
        clean_number(node)
        if "text" in node:
            cleaned = clean_text(node["text"])
            if cleaned:
                node["text"] = cleaned
            else:
                node.pop("text")
        if node.get("children"):
            finalize_structure(node["children"], seen)


def fix_duplicate_numbers(tree: list) -> None:
    """Collapse article numbers polluted by OCR footnote digits.

    OCR systems sometimes glue a superscript footnote marker to the article
    number.  Depending on whether the marker appears before or after the
    number, this yields either a repeated digit (``22`` instead of ``2``) or a
    prefixed digit (``28`` instead of ``8`` or ``110`` instead of ``10``).

    This pass walks sibling lists and normalizes such numbers by comparing
    them to the expected sequential value.  Legitimate jumps such as ``22``
    following ``21`` are left untouched.
    """

    def _walk(nodes: list) -> None:
        last: dict[str, int] = {}
        for node in nodes:
            typ = canonical_type(node.get("type", ""))
            num = node.get("number")
            if typ in ARTICLE_TYPES and isinstance(num, str) and num.isdigit():
                prev = last.get(typ)
                val = int(num)
                if prev is not None:
                    expected = prev + 1
                    exp_str = str(expected)
                    if val != expected:
                        if num.endswith(exp_str):
                            # e.g. ``17`` after ``6`` -> ``7`` or ``110`` after
                            # ``9`` -> ``10`` where a footnote digit prefixes
                            # the real number.
                            val = expected
                            node["number"] = exp_str
                        elif len(num) == len(exp_str) * 2 and num == exp_str * 2:
                            # e.g. ``22`` after ``1`` -> ``2`` where the
                            # footnote digit was appended to the number.
                            val = expected
                            node["number"] = exp_str
                    else:
                        val = expected
                last[typ] = val
            if node.get("children"):
                _walk(node["children"])

    _walk(tree)


def break_cycles(nodes: list, active: set[int] | None = None, seen: set[int] | None = None) -> None:
    if active is None:
        active = set()
    if seen is None:
        seen = set()
    for i, node in enumerate(list(nodes)):
        nid = id(node)
        if nid in active:
            nodes.pop(i)
            continue
        if nid in seen:
            node = copy.deepcopy(node)
            nodes[i] = node
            nid = id(node)
        seen.add(nid)
        active.add(nid)
        if node.get("children"):
            break_cycles(node["children"], active, seen)
        active.remove(nid)


def remove_empty_duplicate_articles(tree: list) -> None:
    mapping: dict[tuple[str, str], list[tuple[dict, list, int]]] = {}

    def collect(nodes: list, depth: int) -> None:
        for node in list(nodes):
            typ = canonical_type(node.get("type"))
            key = (typ, str(node.get("number")))
            if typ in ARTICLE_TYPES:
                mapping.setdefault(key, []).append((node, nodes, depth))
            if node.get("children"):
                collect(node["children"], depth + 1)

    collect(tree, 0)

    for key, entries in mapping.items():
        if len(entries) <= 1:
            continue
        best_idx = max(
            range(len(entries)),
            key=lambda i: (entries[i][2], len(entries[i][0].get("text", ""))),
        )
        best_node, best_parent, _ = entries[best_idx]

        def is_descendant(parent: dict, child: dict) -> bool:
            for c in parent.get("children", []):
                if c is child or is_descendant(c, child):
                    return True
            return False

        def prune_target(node: dict, target: dict) -> None:
            children = node.get("children", [])
            node["children"] = [c for c in children if c is not target]
            for c in node["children"]:
                prune_target(c, target)

        for idx, (node, parent, _) in enumerate(entries):
            if idx == best_idx:
                continue
            if is_descendant(node, best_node):
                if node.get("text"):
                    if best_node.get("text"):
                        existing = best_node["text"]
                        new = node["text"]
                        if existing and not existing.endswith("\n") and not new.startswith("\n"):
                            best_node["text"] = existing + "\n" + new
                        else:
                            best_node["text"] = existing + new
                    else:
                        best_node["text"] = node["text"]
                prune_target(node, best_node)
                for child in list(node.get("children", [])):
                    merge_chunk_structure(best_node.setdefault("children", []), [child])
                if best_node in best_parent:
                    best_parent.remove(best_node)
                idx_in_parent = parent.index(node)
                parent[idx_in_parent] = best_node
                continue
            if node.get("text"):
                if best_node.get("text"):
                    existing = best_node["text"]
                    new = node["text"]
                    if existing and not existing.endswith("\n") and not new.startswith("\n"):
                        best_node["text"] = existing + "\n" + new
                    else:
                        best_node["text"] = existing + new
                else:
                    best_node["text"] = node["text"]
            if node.get("children"):
                best_node.setdefault("children", [])
                merge_chunk_structure(best_node["children"], node["children"])
            parent.remove(node)


def sort_sections(tree: list, seen: set[int] | None = None) -> None:
    if seen is None:
        seen = set()

    def try_int(val):
        if isinstance(val, str):
            ord_val = ordinal_to_int(val)
            if ord_val is not None:
                return ord_val
        try:
            return int(str(val))
        except (ValueError, TypeError):
            return None

    for node in tree:
        if id(node) in seen:
            continue
        seen.add(id(node))
        num_int = try_int(node.get("number"))
        if num_int is not None:
            node["number"] = num_int
        if node.get("children"):
            sort_sections(node["children"], seen)

    def sort_key(n):
        val = try_int(n.get("number"))
        return (0, val) if val is not None else (1, str(n.get("number")))

    tree.sort(key=sort_key)


def fill_missing_articles(nodes: list, seen: set[int] | None = None) -> None:
    if seen is None:
        seen = set()
    i = 0
    if nodes:
        first = nodes[0]
        if canonical_type(first.get("type")) == "مادة":
            try:
                first_num = int(str(first.get("number")))
            except Exception:
                first_num = None
            if first_num is not None and first_num > 1:
                missing = 1
                while missing < first_num:
                    placeholder = {
                        "type": "مادة",
                        "number": str(missing),
                        "title": "",
                        "text": "",
                        "children": [],
                        "_placeholder": True,
                    }
                    nodes.insert(i, placeholder)
                    missing += 1
                    i += 1
    while i < len(nodes) - 1:
        current = nodes[i]
        nxt = nodes[i + 1]
        if canonical_type(current.get("type")) == "مادة" and canonical_type(nxt.get("type")) == "مادة":
            try:
                cur_num = int(str(current.get("number")))
                next_num = int(str(nxt.get("number")))
            except Exception:
                i += 1
                continue
            missing = cur_num + 1
            while missing < next_num:
                placeholder = {
                    "type": "مادة",
                    "number": str(missing),
                    "title": "",
                    "text": "",
                    "children": [],
                    "_placeholder": True,
                }
                nodes.insert(i + 1, placeholder)
                missing += 1
                i += 1
        i += 1
    for node in nodes:
        if node.get("children"):
            node_id = id(node)
            if node_id in seen:
                continue
            seen.add(node_id)
            fill_missing_articles(node["children"], seen)


def fill_missing_sections(nodes: list, seen: set[int] | None = None) -> None:
    if seen is None:
        seen = set()
    i = 0
    if nodes:
        first = nodes[0]
        first_type = canonical_type(first.get("type"))
        if first_type != "مادة":
            try:
                first_num = int(str(first.get("number")))
            except Exception:
                first_num = None
            if first_num is not None and first_num > 1:
                missing = 1
                while missing < first_num:
                    placeholder = {
                        "type": first_type,
                        "number": str(missing),
                        "title": "",
                        "text": "",
                        "children": [],
                        "_placeholder": True,
                    }
                    nodes.insert(i, placeholder)
                    missing += 1
                    i += 1
    while i < len(nodes) - 1:
        current = nodes[i]
        nxt = nodes[i + 1]
        cur_type = canonical_type(current.get("type"))
        nxt_type = canonical_type(nxt.get("type"))
        if cur_type == nxt_type and cur_type != "مادة":
            try:
                cur_num = int(str(current.get("number")))
                next_num = int(str(nxt.get("number")))
            except Exception:
                i += 1
                continue
            missing = cur_num + 1
            while missing < next_num:
                placeholder = {
                    "type": cur_type,
                    "number": str(missing),
                    "title": "",
                    "text": "",
                    "children": [],
                    "_placeholder": True,
                }
                nodes.insert(i + 1, placeholder)
                missing += 1
                i += 1
        i += 1
    for node in nodes:
        if node.get("children"):
            node_id = id(node)
            if node_id in seen:
                continue
            seen.add(node_id)
            fill_missing_sections(node["children"], seen)


def drop_empty_non_article_nodes(nodes: list) -> None:
    for node in list(nodes):
        typ = canonical_type(node.get("type"))
        has_text = bool(node.get("text"))
        has_children = bool(node.get("children"))
        if not has_text and not has_children and typ != "مادة" and not node.get("_placeholder"):
            nodes.remove(node)
        elif has_children:
            drop_empty_non_article_nodes(node["children"])


def deduplicate_articles(nodes: list) -> None:
    mapping: dict[str, dict] = {}

    def visit(parent_list: list) -> None:
        for node in list(parent_list):
            typ = canonical_type(node.get("type"))
            if typ == "مادة":
                num = str(node.get("number"))
                if num in mapping:
                    best = mapping[num]
                    if len(node.get("text", "")) > len(best.get("text", "")):
                        best["text"] = node.get("text", "")
                    if node.get("children"):
                        merge_chunk_structure(best.setdefault("children", []), node["children"])
                    parent_list.remove(node)
                    continue
                else:
                    mapping[num] = node
            if node.get("children"):
                visit(node["children"])

    visit(nodes)

RANK_MAP = {
    "قسم": 0,
    "جزء": 0,
    "باب": 1,
    "فصل": 2,
    "فرع": 3,
    "مادة": 4,
}


def compute_rank_map(nodes: list) -> dict[str, int]:
    """Return a canonical ranking for the section types present in ``nodes``."""

    present: set[str] = set()

    def walk(nlist: list) -> None:
        for n in nlist:
            typ = canonical_type(n.get("type", ""))
            if typ:
                present.add(typ)
            if n.get("children"):
                walk(n["children"])

    walk(nodes)

    ordered = [t for t in RANK_MAP if t in present]
    ordered.extend(t for t in present if t not in RANK_MAP)
    return {t: i for i, t in enumerate(ordered)}


def fix_hierarchy(nodes: list, rank_map: dict[str, int] | None = None) -> None:
    if rank_map is None:
        rank_map = compute_rank_map(nodes)
    stack: list[tuple[dict, int]] = []
    new_root: list[dict] = []
    for node in nodes:
        typ = canonical_type(node.get("type", ""))
        rank = rank_map.get(typ, max(rank_map.values()) + 1)
        node.setdefault("children", [])
        while stack and rank <= stack[-1][1]:
            stack.pop()
        if stack:
            parent = stack[-1][0]
            parent.setdefault("children", [])
            parent["children"].append(node)
        else:
            new_root.append(node)
        stack.append((node, rank))
    nodes[:] = new_root
    for n in nodes:
        if n.get("children"):
            fix_hierarchy(n["children"], rank_map)


def merge_chunk_structure(full_tree: list, chunk_array: list):
    for node in chunk_array:
        if not isinstance(node, dict) or "number" not in node:
            print(f"[Debug] Skipping malformed node: {node}")
            continue
        node.setdefault("children", [])
        node["type"] = canonical_type(node.get("type", ""))
        match = next(
            (n for n in full_tree if canonical_type(n.get("type")) == node.get("type") and str(n.get("number")) == str(node["number"])),
            None,
        )
        if match is None:
            node.setdefault("children", [])
            if canonical_type(node.get("type")) not in ARTICLE_TYPES:
                node["text"] = ""
            clean_number(node)
            if canonical_type(node.get("type")) in ARTICLE_TYPES and node.get("text"):
                node["text"] = clean_text(node["text"])
            full_tree.append(node)
        else:
            match.setdefault("children", [])
            if canonical_type(match.get("type")) in ARTICLE_TYPES:
                new = clean_text(node.get("text", ""))
                if new:
                    existing = match.get("text", "")
                    if existing:
                        if not existing.endswith("\n") and not new.startswith("\n"):
                            match["text"] = existing + "\n" + new
                        else:
                            match["text"] = existing + new
                    else:
                        match["text"] = new
            if node.get("children"):
                merge_chunk_structure(match["children"], node["children"])
    finalize_structure(full_tree)
    sort_sections(full_tree)

