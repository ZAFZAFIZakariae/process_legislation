import os
import sys
import json
import argparse
import re

import tiktoken

try:  # Prefer relative import when running as a package
    from . import gpt_helpers as gpt
except Exception:  # Allow running as a script
    try:
        import gpt_helpers as gpt  # type: ignore
    except Exception as exc:  # pragma: no cover - missing dependency
        raise ImportError("gpt_helpers module is required") from exc


def run_passes(txt_path: str, model: str) -> dict:
    """Run Pass 1 and Pass 2 on the given text file and return raw JSON."""
    gpt.adjust_for_model(model)
    with open(txt_path, "r", encoding="utf-8") as f:
        arabic_text = gpt.clean_ocr_lines(f.read())

    has_preamble_heading = bool(re.search(r"\bقسم\s+تمهيدي\b", arabic_text))

    # ---- Pass 1 ----
    first_chunk = gpt.split_for_pass1(arabic_text)
    msgs1 = gpt.build_messages_for_pass1(first_chunk)
    raw_full = gpt.call_gpt_on_chunk(msgs1, json_mode=True)
    full_obj = json.loads(raw_full) if isinstance(raw_full, str) else raw_full
    structure_tree = full_obj.get("structure", [])
    gpt.finalize_structure(structure_tree)

    def collect_annexes(nodes: list) -> tuple[list, list]:
        remaining: list = []
        annexes: list = []

        for node in nodes:
            typ = gpt.canonical_type(node.get("type", ""))
            if typ not in gpt.ARTICLE_TYPES:
                title_parts = [node.get("type", ""), str(node.get("number", "")), node.get("title", "")]
                title = " ".join([p for p in title_parts if p]).strip()

                texts: list[str] = []

                def gather(n: dict) -> None:
                    if n.get("text"):
                        texts.append(n["text"])
                    for ch in n.get("children", []) or []:
                        gather(ch)

                gather(node)
                annexes.append({"annex_title": title, "annex_text": "\n".join(texts).strip()})
            else:
                if node.get("children"):
                    node["children"], extra = collect_annexes(node["children"])
                    annexes.extend(extra)
                remaining.append(node)

        return remaining, annexes

    # ---- Pass 2 ----
    pass2_chunks = gpt.split_for_pass2(arabic_text)
    inherited = ""
    prev_tail = ""
    for idx, chunk in enumerate(pass2_chunks, 1):
        msgs2 = gpt.build_messages_for_pass2(prev_tail + chunk, inherited)
        raw_articles = gpt.call_gpt_on_chunk(msgs2, json_mode=False)

        inherit_line, json_part = ("", raw_articles)
        if isinstance(raw_articles, str):
            inherit_line, json_part = gpt.extract_inherited(raw_articles)
            if inherit_line:
                inherited_info = gpt.parse_inherited_fields(inherit_line)
                inherited = inherit_line + "\n"
            else:
                inherited = ""
                inherited_info = None
        else:
            inherited_info = None
            inherited = ""

        chunk_content = json_part
        if isinstance(chunk_content, str):
            chunk_content = gpt.remove_code_fences(chunk_content)

        chunk_array = []
        try:
            chunk_data = json.loads(chunk_content) if isinstance(chunk_content, str) else chunk_content
            if isinstance(chunk_data, dict):
                chunk_array = [chunk_data]
            elif isinstance(chunk_data, list):
                chunk_array = chunk_data
        except Exception:
            print(f"⚠️  Chunk #{idx} returned invalid JSON; attempting repair")
            repaired = gpt.repair_chunk_json(raw_articles)
            chunk_array = repaired if repaired is not None else []

        target_tree = structure_tree
        if inherit_line and inherited_info:
            inherited_info["type"] = gpt.canonical_type(inherited_info["type"])
            parent = gpt.find_node(structure_tree, inherited_info["type"], inherited_info["number"])
            if parent is None:
                parent = {
                    "type": inherited_info["type"],
                    "number": inherited_info["number"],
                    "title": inherited_info.get("title", ""),
                    "text": "" if gpt.canonical_type(inherited_info["type"]) not in gpt.ARTICLE_TYPES else "",
                    "children": [],
                }
                structure_tree.append(parent)
            target_tree = parent.get("children", [])

        # gpt.merge_chunk_structure(target_tree, chunk_array)
        # Append chunk data without merging so the output preserves each chunk
        # exactly as extracted
        target_tree.extend(chunk_array)

        enc = tiktoken.encoding_for_model(gpt.GPT_MODEL)
        tok = enc.encode(chunk)
        tail = tok[-100:] if len(tok) >= 100 else tok
        prev_tail = enc.decode(tail)

    structure_tree, annex_list = collect_annexes(structure_tree)
    full_obj["structure"] = structure_tree
    full_obj["annexes"] = annex_list
    full_obj["has_preamble_heading"] = has_preamble_heading
    return full_obj


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Pass 1 and Pass 2 on a text file")
    parser.add_argument("--input", required=True, help="Path to OCR'd text file")
    parser.add_argument("--output", required=True, help="Where to store intermediate JSON")
    parser.add_argument("--model", default=gpt.GPT_MODEL, help="OpenAI model name")
    args = parser.parse_args()

    try:
        result = run_passes(args.input, args.model)
        with open(args.output, "w", encoding="utf-8") as fout:
            json.dump(result, fout, ensure_ascii=False, indent=2)
        print(f"[+] Saved raw structure to: {args.output}")
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
