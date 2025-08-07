import argparse
import json
from typing import Any, Dict

from .hierarchy_builder import (
    postprocess_structure,
    flatten_articles,
    normalize_numbers,
    merge_duplicates,
    remove_duplicate_articles,
    attach_stray_articles,
    prune_structure,
)


def post_process_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return structure JSON after hierarchy reconstruction and cleanup."""
    flat = data.get("structure", [])
    hier = postprocess_structure(flat)
    flatten_articles(hier)
    normalize_numbers(hier)
    hier = merge_duplicates(hier)
    remove_duplicate_articles(hier)
    attach_stray_articles(hier)
    # Moving stray articles under their proper parents can surface new
    # duplicates, so perform a final deduplication pass.
    remove_duplicate_articles(hier)
    hier = prune_structure(hier, at_root=True)
    data["structure"] = hier

    # Drop placeholder tables and annexes that carry no meaningful content.
    tables = []
    for table in data.get("tables_and_schedules", []) or []:
        if any(cell.strip() for row in table.get("rows", []) for cell in row.get("columns", [])):
            tables.append(table)
    data["tables_and_schedules"] = tables

    data["annexes"] = [a for a in data.get("annexes", []) or [] if a.get("annex_text", "").strip()]

    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post-process raw structure into a clean hierarchy",
    )
    parser.add_argument("--input", required=True, help="Path to structure_raw.json")
    parser.add_argument("--output", required=True, help="Where to save final JSON")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    data = post_process_data(data)

    with open(args.output, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2)
    print(f"[+] Saved post-processed structure to: {args.output}")


if __name__ == "__main__":
    main()
