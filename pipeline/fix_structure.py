from __future__ import annotations

import argparse
import json
import re
from typing import Any

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

HEADER_LINES = {
    "مديرية التشريع والدراسات",
    "مديرية التشريع والدرامات",
    "وزارة العدل",
    "المملكة المغربية",
}

RANK_MAP = {
    "قسم": 0,
    "جزء": 0,
    "باب": 1,
    "فصل": 2,
    "فرع": 3,
    "مادة": 4,
}

def canonical_type(t: str) -> str:
    if not isinstance(t, str):
        return ""
    s = t.strip()
    if s.startswith("ال"):
        s = s[2:]
    return ARTICLE_TYPE_MAP.get(s, s)


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
    if canonical_type(node.get("type")) in ARTICLE_TYPES:
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


def finalize_structure(tree: list, seen: set[int] | None = None) -> None:
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
        if node.get("type") not in ARTICLE_TYPES:
            node["text"] = ""
        else:
            node["text"] = clean_text(node.get("text", ""))
        if node.get("children"):
            finalize_structure(node["children"], seen)


def compute_rank_map(nodes: list) -> dict[str, int]:
    order: list[str] = []

    def walk(nlist: list) -> None:
        for n in nlist:
            typ = canonical_type(n.get("type", ""))
            if typ and typ not in order:
                order.append(typ)
            if n.get("children"):
                walk(n["children"])

    walk(nodes)
    return {t: i for i, t in enumerate(order)} or RANK_MAP


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
            for c in node.get("children", []):
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

    def try_int(val: Any) -> int | None:
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

    def sort_key(n: dict) -> tuple[int, Any]:
        val = try_int(n.get("number"))
        return (0, val) if val is not None else (1, str(n.get("number")))

    tree.sort(key=sort_key)


def merge_chunk_structure(full_tree: list, chunk_array: list) -> None:
    for node in chunk_array:
        if not isinstance(node, dict) or "number" not in node:
            print(f"[Debug] Skipping malformed node: {node}")
            continue
        node.setdefault("children", [])
        node["type"] = canonical_type(node.get("type", ""))
        match = next(
            (
                n
                for n in full_tree
                if canonical_type(n.get("type")) == node.get("type")
                and str(n.get("number")) == str(node["number"])
            ),
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
                        best.setdefault("children", []).extend(node["children"])
                    parent_list.remove(node)
                    continue
                else:
                    mapping[num] = node
            if node.get("children"):
                visit(node["children"])

    visit(nodes)


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
            node = dict(node)
            nodes[i] = node
            nid = id(node)
        seen.add(nid)
        active.add(nid)
        if node.get("children"):
            break_cycles(node["children"], active, seen)
        active.remove(nid)


def process(raw_json_path: str, output_path: str) -> None:
    with open(raw_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    tree = data.get("structure", [])
    has_preamble_heading = data.get("has_preamble_heading", False)

    rank_map = compute_rank_map(tree)
    fix_hierarchy(tree, rank_map)
    finalize_structure(tree)
    if has_preamble_heading and find_node(tree, "قسم", "0") is None:
        tree.insert(0, {"type": "قسم", "number": "0", "title": "", "text": "", "children": []})
        finalize_structure(tree)
    remove_empty_duplicate_articles(tree)
    drop_empty_non_article_nodes(tree)
    fill_missing_articles(tree)
    fill_missing_sections(tree)
    finalize_structure(tree)
    sort_sections(tree)
    remove_empty_duplicate_articles(tree)
    deduplicate_articles(tree)
    break_cycles(tree)

    data["structure"] = tree
    with open(output_path, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-process raw structure JSON")
    parser.add_argument("--input", required=True, help="Path to intermediate JSON")
    parser.add_argument("--output", required=True, help="Path for final JSON")
    args = parser.parse_args()
    process(args.input, args.output)


if __name__ == "__main__":
    main()
