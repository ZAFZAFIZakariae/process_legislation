import argparse
import json
import re
from typing import Any, List, Dict


TYPE_MAP = {
    "المادة": "مادة",
    "القسم": "قسم",
    "الباب": "باب",
    "الفصل": "فصل",
    "الجزء": "جزء",
    "الفرع": "فرع",
}

# Structural types we allow to keep in the final hierarchy.  Anything outside
# this list is treated as noise and pruned during the cleanup phase.
ALLOWED_TYPES = {"قسم", "باب", "فصل", "جزء", "فرع", "مادة"}


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


def normalize_numbers(children: List[Dict[str, Any]]) -> None:
    """Clean up article numbers that may contain stray prefix digits.

    OCR artifacts and footnotes occasionally introduce spurious leading digits
    before the actual article number (e.g. ``814`` instead of ``14`` or ``923``
    instead of ``23``).  This function trims such digits to restore the proper
    numbering so downstream merging and sorting operate on the correct values.
    The heuristic is conservative: if a purely numeric ``number`` field has more
    than two digits and starts with ``8`` or ``9``, and the remainder forms a
    valid number, we drop the first digit.
    """

    for node in children:
        num = str(node.get("number", "")).strip()
        if num.isdigit() and len(num) > 2 and num[0] in {"8", "9"}:
            tail = num[1:]
            if tail.isdigit():
                node["number"] = tail
        if node.get("children"):
            normalize_numbers(node["children"])


def merge_duplicates(children: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge nodes with the same type/number while normalising their fields.

    The raw structure often contains duplicate entries for headings where one
    node only carries the number and another carries the actual text.  Articles
    (``مادة``) are handled separately in :func:`remove_duplicate_articles` so we
    deliberately avoid merging them here to preserve the position of the most
    informative occurrence.
    """

    seen: Dict[tuple, Dict[str, Any]] = {}
    result: List[Dict[str, Any]] = []

    for node in children:
        node_type = canonical_type(node.get("type", ""))
        node["type"] = node_type
        number = str(node.get("number", "")).strip()
        node["number"] = number
        key = (node_type, number)

        if node_type == "مادة":
            # Defer article deduplication to ``remove_duplicate_articles`` so
            # that we can keep the occurrence that appears later in the
            # document (often the one containing the real text rather than a
            # stray footnote reference).
            result.append(node)
            continue

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
    def parse_num(n: Any) -> tuple[int, Any]:
        try:
            return (0, int(str(n)))
        except Exception:
            return (1, str(n))

    # Determine the different node types present amongst the children.  When a
    # mixture of structural elements exists (for example ``فرع`` nodes alongside
    # ``مادة`` nodes) we should not reorder them globally as that would disturb
    # the original document flow.  In such cases we keep the existing order and
    # only sort recursively inside each child.  If all children share the same
    # type we sort them numerically by their ``number`` field.
    types = {canonical_type(child.get("type", "")) for child in children}
    if len(types) == 1:
        children.sort(key=lambda x: parse_num(x.get("number")))

    for node in children:
        if node.get("children"):
            sort_children(node["children"])


def flatten_articles(children: List[Dict[str, Any]]) -> None:
    """Promote article nodes from being nested inside other articles.

    When the raw structure is produced some articles are erroneously captured as
    children of the preceding article.  Articles should always be siblings under
    a section or chapter heading.  This function walks the tree and, whenever an
    article has article children, it moves those children to be siblings of the
    parent article.
    """

    i = 0
    while i < len(children):
        node = children[i]
        node_type = canonical_type(node.get("type", ""))
        if node_type == "مادة" and node.get("children"):
            children[i + 1 : i + 1] = node["children"]
            node["children"] = []
            # continue processing including the inserted nodes
        else:
            if node.get("children"):
                flatten_articles(node["children"])
        i += 1


def remove_duplicate_articles(children: List[Dict[str, Any]]) -> None:
    """Deduplicate article nodes while preserving global ordering.

    Some source documents contain multiple occurrences of the same article
    number scattered throughout different sections.  The authoritative version
    is the one that best respects the overall sequential order of articles in the
    document.  To determine this we collect every article along with its
    traversal order, select a single occurrence for each number that appears
    *after* the previous article's position, and merge any remaining duplicates
    into that kept node.
    """

    # Collect all article occurrences with a global traversal index so we can
    # later choose the occurrence that preserves the natural ordering of
    # articles.
    order = 0
    occurrences: Dict[str, List[tuple[int, List[Dict[str, Any]], int, Dict[str, Any]]]] = {}

    def walk(nodes: List[Dict[str, Any]]):
        nonlocal order
        for idx, node in enumerate(nodes):
            node_type = canonical_type(node.get("type", ""))
            if node_type == "مادة":
                num = str(node.get("number", "")).strip()
                if not num.isdigit():
                    continue
                occurrences.setdefault(num, []).append((order, nodes, idx, node))
                order += 1
            if node.get("children"):
                walk(node["children"])

    walk(children)

    # Determine which occurrence of each article number to keep.  We iterate
    # through the numbers in numeric order and for each pick the earliest
    # occurrence whose traversal order comes after the previously selected
    # article.  This ensures the final sequence of articles is monotonically
    # increasing.
    chosen: Dict[str, tuple[int, List[Dict[str, Any]], int, Dict[str, Any]]] = {}
    last_order = -1
    for num in sorted(occurrences, key=lambda x: int(str(x))):
        occs = sorted(occurrences[num], key=lambda x: x[0])
        selected = None
        for occ in occs:
            if occ[0] > last_order:
                selected = occ
                break
        if selected is None:
            selected = occs[-1]
        chosen[num] = selected
        last_order = selected[0]

    # Merge duplicates into the chosen node and mark others for removal.
    for num, occs in occurrences.items():
        keep_order, keep_parent, keep_idx, keep_node = chosen[num]
        for occ in occs:
            order_idx, parent, idx, node = occ
            if occ is chosen[num]:
                continue
            if len(node.get("text", "")) > len(keep_node.get("text", "")):
                keep_node["text"] = node.get("text", "")
            keep_node.setdefault("children", []).extend(node.get("children", []))
            parent[idx] = None

    def cleanup(nodes: List[Dict[str, Any]]):
        i = 0
        while i < len(nodes):
            node = nodes[i]
            if node is None:
                nodes.pop(i)
                continue
            if node.get("children"):
                cleanup(node["children"])
            i += 1

    cleanup(children)


def attach_stray_articles(children: List[Dict[str, Any]]) -> None:
    """Attach article nodes that appear alongside structural siblings.

    In some raw structures articles (``مادة``) are emitted as direct children of a
    section or chapter even though subsequent nodes introduce a new structural
    level such as a ``فصل``.  These articles logically belong to the preceding
    structural node (e.g. the last ``باب``/``فصل``).  This function walks the
    tree and whenever it encounters such stray articles it moves them beneath the
    most recent structural ancestor.
    """

    i = 0
    last_struct: Dict[str, Any] | None = None
    while i < len(children):
        node = children[i]
        node_type = canonical_type(node.get("type", ""))

        if node_type in {"قسم", "باب", "فصل"}:
            # Occasionally a ``فصل`` heading is emitted at the same hierarchical
            # level as its preceding ``باب``.  When this happens we should nest
            # the chapter under the most recent ``باب`` instead of leaving it as
            # a sibling.  This mirrors the logic used for stray article nodes
            # below.
            if (
                node_type == "فصل"
                and last_struct is not None
                and canonical_type(last_struct.get("type", "")) == "باب"
            ):
                last_struct.setdefault("children", []).append(node)
                children.pop(i)
                attach_stray_articles(node.get("children", []))
                continue

            attach_stray_articles(node.get("children", []))
            last_struct = node
            i += 1
            continue

        if node_type == "مادة" and last_struct is not None:
            target = last_struct
            if canonical_type(target.get("type", "")) in {"قسم", "باب"}:
                sub = target.get("children", [])
                if sub and canonical_type(sub[-1].get("type", "")) == "فصل":
                    target = sub[-1]
            target.setdefault("children", []).append(node)
            children.pop(i)
            continue

        if node.get("children"):
            attach_stray_articles(node["children"])
        i += 1


def prune_structure(children: List[Dict[str, Any]], *, at_root: bool = False) -> List[Dict[str, Any]]:
    """Remove spurious nodes and stray root-level articles.

    ``extract_chunks`` sometimes yields miscellaneous commentary or OCR noise
    that appears as sibling nodes within the hierarchy.  This function removes
    any node whose ``type`` isn't recognised, strips entries with non-numeric
    ``number`` fields, and drops articles that float at the document root.
    """

    pruned: List[Dict[str, Any]] = []
    for node in children:
        node_type = canonical_type(node.get("type", ""))
        number = str(node.get("number", "")).strip()

        # Ignore unknown structural types altogether
        if node_type not in ALLOWED_TYPES:
            continue

        # Skip articles that appear directly under the root; they are typically
        # duplicated snippets that should live inside one of the sections.
        if at_root and node_type == "مادة":
            continue

        # If a node declares a number, ensure it is purely numeric.  Textual
        # values such as "القسم" or footnote markers are discarded.
        if number and not number.isdigit():
            continue

        node["type"] = node_type
        node["number"] = number

        if node.get("children"):
            node["children"] = prune_structure(node["children"], at_root=False)

        pruned.append(node)

    return pruned


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruct hierarchical structure")
    parser.add_argument("--input", required=True, help="Path to structure_raw.json")
    parser.add_argument("--output", required=True, help="Path for hierarchical JSON")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    flat_structure = data.get("structure", [])
    hier = postprocess_structure(flat_structure)
    flatten_articles(hier)
    normalize_numbers(hier)
    hier = merge_duplicates(hier)
    remove_duplicate_articles(hier)
    attach_stray_articles(hier)
    # ``attach_stray_articles`` may move articles beneath new parents which can
    # re-introduce duplicates.  Run a final deduplication pass to ensure only one
    # instance of each article number remains within a section.
    remove_duplicate_articles(hier)
    hier = prune_structure(hier, at_root=True)
    data["structure"] = hier
    with open(args.output, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
