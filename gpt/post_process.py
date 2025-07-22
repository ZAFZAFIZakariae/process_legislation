import os
import sys
import json
import argparse

try:
    from .. import gpt
except Exception:
    import gpt


def finalize_from_file(raw_json_path: str, output_path: str) -> None:
    """Load intermediate JSON and save the fully processed structure."""
    with open(raw_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    structure_tree = data.get("structure", [])
    has_preamble_heading = data.get("has_preamble_heading", False)

    rank_map = gpt.compute_rank_map(structure_tree)
    gpt.fix_hierarchy(structure_tree, rank_map)
    gpt.finalize_structure(structure_tree)
    if has_preamble_heading and gpt.find_node(structure_tree, "قسم", "0") is None:
        structure_tree.insert(0, {"type": "قسم", "number": "0", "title": "", "text": "", "children": []})
        gpt.finalize_structure(structure_tree)
    gpt.remove_empty_duplicate_articles(structure_tree)
    gpt.drop_empty_non_article_nodes(structure_tree)
    gpt.fill_missing_articles(structure_tree)
    gpt.fill_missing_sections(structure_tree)
    gpt.finalize_structure(structure_tree)
    gpt.sort_sections(structure_tree)
    gpt.remove_empty_duplicate_articles(structure_tree)
    gpt.deduplicate_articles(structure_tree)
    gpt.break_cycles(structure_tree)

    data["structure"] = structure_tree
    with open(output_path, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-process raw structure JSON")
    parser.add_argument("--input", required=True, help="Path to intermediate JSON")
    parser.add_argument("--output", required=True, help="Path for final JSON")
    args = parser.parse_args()

    try:
        finalize_from_file(args.input, args.output)
        print(f"[+] Saved final JSON: {args.output}")
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
