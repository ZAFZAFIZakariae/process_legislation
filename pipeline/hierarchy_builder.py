import argparse
import json
from typing import Any, List, Dict


TYPE_MAP = {
    "المادة": "مادة",
    "القسم": "قسم",
    "الباب": "باب",
    "الفصل": "فصل",
    "الجزء": "جزء",
    "الفرع": "فرع",
}


def canonical_type(t: str) -> str:
    if not isinstance(t, str):
        return ""
    s = t.strip()
    if s.startswith("ال") and s[2:] in TYPE_MAP.values():
        s = s[2:]
    return TYPE_MAP.get(s, s)


def postprocess_structure(flat_structure: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    stack: List[Dict[str, Any]] = []
    root: List[Dict[str, Any]] = []

    for entry in flat_structure:
        level = canonical_type(entry.get("type", ""))
        entry["type"] = level
        entry.setdefault("children", [])

        if level == "قسم":
            stack = [entry]
            root.append(entry)
        elif level == "باب":
            while stack and stack[-1].get("type") != "قسم":
                stack.pop()
            if stack:
                stack[-1].setdefault("children", []).append(entry)
            stack.append(entry)
        elif level == "فصل":
            while stack and stack[-1].get("type") not in ["باب", "قسم"]:
                stack.pop()
            if stack:
                stack[-1].setdefault("children", []).append(entry)
            stack.append(entry)
        elif level in ["مادة", "المادة"]:
            while stack and stack[-1].get("type") not in ["فصل", "باب", "قسم"]:
                stack.pop()
            if stack:
                stack[-1].setdefault("children", []).append(entry)
            else:
                root.append(entry)
        else:
            root.append(entry)

    return root


def merge_duplicates(children: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[tuple, Dict[str, Any]] = {}
    result: List[Dict[str, Any]] = []
    for node in children:
        key = (node.get("type"), str(node.get("number")))
        if key in seen:
            existing = seen[key]
            if not existing.get("text") and node.get("text"):
                existing["text"] = node["text"]
            elif existing.get("text") and node.get("text") and existing["text"] != node["text"]:
                if not existing["text"].endswith("\n"):
                    existing["text"] += "\n"
                existing["text"] += node["text"]
            existing.setdefault("children", []).extend(node.get("children", []))
        else:
            seen[key] = node
            result.append(node)

    for node in result:
        if node.get("children"):
            node["children"] = merge_duplicates(node["children"])
    return result


def sort_children(children: List[Dict[str, Any]]) -> None:
    def parse_num(n: Any) -> Any:
        try:
            return int(str(n))
        except Exception:
            return str(n)

    children.sort(key=lambda x: parse_num(x.get("number")))
    for node in children:
        if node.get("children"):
            sort_children(node["children"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruct hierarchical structure")
    parser.add_argument("--input", required=True, help="Path to structure_raw.json")
    parser.add_argument("--output", required=True, help="Path for hierarchical JSON")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    flat_structure = data.get("structure", [])
    hier = postprocess_structure(flat_structure)
    hier = merge_duplicates(hier)
    sort_children(hier)

    data["structure"] = hier
    with open(args.output, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
