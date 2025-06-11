# ---------------------------------------------------------
# gpt.py
# ---------------------------------------------------------
# Install dependencies (once):
#   pip install openai tiktoken
# ---------------------------------------------------------

import os
import sys
import json
import argparse
import re

import tiktoken
import openai

try:  # Prefer relative import when running as a module
    from .ocr import pdf_to_arabic_text
except Exception:  # pragma: no cover - optional dependency may be missing
    try:
        from ocr import pdf_to_arabic_text  # type: ignore
    except Exception:
        def pdf_to_arabic_text(path: str) -> str:
            raise RuntimeError("OCR functionality is unavailable in this environment")

# ----------------------------------------------------------------------
# 1) Read OpenAI API key from environment
# ----------------------------------------------------------------------
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    # In test environments we fall back to a dummy key so the script can run
    print("⚠️  OPENAI_API_KEY not set; using dummy key for offline mode.")
    openai.api_key = "DUMMY"

# ----------------------------------------------------------------------
# 2) GPT model and token limits
# ----------------------------------------------------------------------
GPT_MODEL            = "gpt-3.5-turbo-16k"
MAX_CONTEXT          = 16_384      # 16 384 tokens total context
MODEL_MAX_COMPLETION = 12_000      # ≈ max reply tokens for gpt-3.5-turbo-16k
PASS1_MAX_TOKENS    = 8_000        # cap initial chunk sent in pass 1


def adjust_for_model(name: str) -> None:
    """Update global token limits based on the chosen model."""
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
        # Fallback to defaults
        MAX_CONTEXT = 16_384
        MODEL_MAX_COMPLETION = 12_000

# ----------------------------------------------------------------------
# 3) Load prompt files (prompt_1.txt, prompt_2.txt located in ./prompts)
# ----------------------------------------------------------------------
def load_prompts() -> tuple[str, str]:
    base = os.path.join(os.path.dirname(__file__), "prompts")
    with open(os.path.join(base, "prompt_1.txt"), "r", encoding="utf-8") as f1:
        p1 = f1.read()
    with open(os.path.join(base, "prompt_2.txt"), "r", encoding="utf-8") as f2:
        p2 = f2.read()

    if "====FIRST_CHUNK====" not in p1:
        print("❌ '====FIRST_CHUNK====' not found in prompt_1.txt")
        sys.exit(1)
    pass1_instructions = p1.split("====FIRST_CHUNK====", 1)[1].strip()

    if "====SUBSEQUENT_CHUNK====" not in p2:
        print("❌ '====SUBSEQUENT_CHUNK====' not found in prompt_2.txt")
        sys.exit(1)
    pass2_instructions = p2.split("====SUBSEQUENT_CHUNK====", 1)[1].strip()

    return pass1_instructions, pass2_instructions

pass1_instructions, pass2_instructions = load_prompts()

# Recognized article-type labels (with and without the definite article)
ARTICLE_TYPES = {"فصل", "الفصل", "مادة", "المادة"}

# ----------------------------------------------------------------------
# 4) Token counting helper
# ----------------------------------------------------------------------
def count_tokens_for_messages(messages: list[dict], model: str) -> int:
    encoding = tiktoken.encoding_for_model(model)
    total = 0
    for msg in messages:
        total += 4
        total += len(encoding.encode(msg["role"]))
        total += len(encoding.encode(msg["content"]))
    total += 2
    return total

# ----------------------------------------------------------------------
# 5) Split for Pass 1 (first PASS1_MAX_TOKENS Arabic tokens)
# ----------------------------------------------------------------------
def split_for_pass1(arabic_text: str) -> str:
    """Return the initial chunk of text for pass 1 within the token budget."""
    enc = tiktoken.encoding_for_model(GPT_MODEL)
    tokens = enc.encode(arabic_text)

    # Calculate how many tokens the prompt (without the chunk) uses
    prompt_msgs = [
        {"role": "system", "content": "You are an expert in Moroccan legislation text structuring."},
        {"role": "user", "content": pass1_instructions + "\n"},
    ]
    prompt_tokens = count_tokens_for_messages(prompt_msgs, GPT_MODEL)

    # Small context models need a bigger safety margin so the response
    # isn't truncated. Leave ~1k tokens for them, otherwise ~500.
    reply_reserve = 1000 if MAX_CONTEXT <= 4_096 else 500
    available = MAX_CONTEXT - prompt_tokens - reply_reserve
    slice_len = max(0, min(len(tokens), available, PASS1_MAX_TOKENS))

    slice_tokens = tokens[:slice_len]
    return enc.decode(slice_tokens)

# ----------------------------------------------------------------------
# 6) Smart split at newline/punctuation
# ----------------------------------------------------------------------
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

        prev_tail = slice_tokens[-100:] if (actual_end - idx) >= 100 else slice_tokens
        idx = actual_end
    return chunks

# ----------------------------------------------------------------------
# 7) Split for Pass 2 (model aware chunk size with 100 token overlap)
# ----------------------------------------------------------------------
def compute_pass2_chunk_limit() -> int:
    """Return token limit per Pass 2 chunk for the current model."""
    dummy_messages = build_messages_for_pass2("", "")
    overhead = count_tokens_for_messages(dummy_messages, GPT_MODEL)
    # Reserve a larger completion budget for small-context models because the
    # JSON output can easily exceed 1000 tokens.  Using too large a chunk causes
    # the model to truncate its reply, which results in invalid JSON and lost
    # sections.  By limiting the chunk size we leave more room for the reply and
    # obtain complete JSON.
    reply_reserve = 1500 if MAX_CONTEXT <= 4_096 else 500
    available = MAX_CONTEXT - overhead - reply_reserve

    # For 4k-context models, cap the chunk at ~2000 tokens to avoid replies
    # exceeding the remaining budget.  Large-context models (e.g. gpt‑4o) still
    # have a completion limit of only ~4000 tokens, so sending very large chunks
    # can lead to truncated JSON.  Cap those chunks at ~3000 tokens.
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
    # Account for the ~100 token overlap between chunks when context is small
    if MAX_CONTEXT <= 4_096:
        chunk_limit = max(100, chunk_limit - 100)
    overlap = 100 if MAX_CONTEXT <= 4_096 else 0
    chunks = []
    i = 0
    prev_tail = []
    total = len(tokens)

    while i < total:
        window = prev_tail + tokens[i : min(i + chunk_limit, total)]
        combined_text = enc.decode(window)

        subchunks = smart_token_split(combined_text, chunk_limit, GPT_MODEL)
        this_chunk = subchunks[0]

        chunk_tokens = enc.encode(this_chunk)
        if prev_tail:
            chunk_tokens = chunk_tokens[len(prev_tail):]
            this_chunk = enc.decode(chunk_tokens)

        chunks.append(this_chunk)

        prev_tail = chunk_tokens[-overlap:] if overlap else []
        i += len(chunk_tokens)

    return chunks

# ----------------------------------------------------------------------
# 8) Build messages for Pass 1
# ----------------------------------------------------------------------
def build_messages_for_pass1(arabic_chunk: str) -> list[dict]:
    return [
        {"role": "system", "content": "You are an expert in Moroccan legislation text structuring."},
        {"role": "user",   "content": pass1_instructions + "\n" + arabic_chunk + "\n<--- END ARABIC FIRST CHUNK."}
    ]

# ----------------------------------------------------------------------
# 9) Build messages for Pass 2
# ----------------------------------------------------------------------
def build_messages_for_pass2(arabic_chunk: str, inherited: str = "") -> list[dict]:
    user_content = inherited + arabic_chunk
    return [
        {"role": "system", "content": "You are an expert in Moroccan legislation text structuring."},
        {"role": "user",   "content": pass2_instructions + "\n" + user_content + "\n<--- END ARABIC SECOND CHUNK."}
    ]

# ----------------------------------------------------------------------
# 10) Call GPT (clamp max_tokens to model’s true limit)
# ----------------------------------------------------------------------
def call_gpt_on_chunk(messages: list[dict], json_mode: bool = True) -> str:
    used   = count_tokens_for_messages(messages, GPT_MODEL)
    remain = MAX_CONTEXT - used
    if remain <= 0:
        raise ValueError("No token budget left for GPT reply; prompt is too large.")

    # Allow up to MODEL_MAX_COMPLETION (approx ~12 000) or whatever remains, whichever is smaller
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

# ----------------------------------------------------------------------
# 11) Attempt to repair a malformed JSON array using GPT
# ----------------------------------------------------------------------
def repair_chunk_json(raw: str) -> list | None:
    """Ask the model to fix malformed JSON from a pass 2 chunk."""
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
    except Exception as e:  # pragma: no cover - best effort
        print(f"[Debug] repair_chunk_json failed: {e}")
    return None


def extract_inherited(reply: str) -> tuple[str, str]:
    """Return (inherited_line, json_part) if present, else ("", reply)."""
    text = reply.lstrip()
    if text.startswith("Inherited context:"):
        line, _, rest = text.partition("\n")
        return line.strip(), rest.lstrip()
    return "", reply


def parse_inherited_fields(line: str) -> dict | None:
    match = re.match(r"Inherited context:\\s*type=([^,]+),\\s*number=([^,]+),\\s*title=\\\"([^\\\"]*)\\\"", line)
    if match:
        return {
            "type": match.group(1).strip(),
            "number": match.group(2).strip(),
            "title": match.group(3).strip(),
        }
    return None


def remove_code_fences(text: str) -> str:
    """Strip leading/trailing markdown code fences from GPT replies."""
    if not isinstance(text, str):
        return text
    text = text.strip()
    text = re.sub(r'^```(?:json)?\\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```\\s*$', '', text)
    return text.strip()


def find_node(tree: list, typ: str, num: str) -> dict | None:
    """Recursively search for a node matching type and number."""
    for n in tree:
        if n.get("type") == typ and n.get("number") == num:
            return n
        child = find_node(n.get("children", []), typ, num)
        if child:
            return child
    return None


def clean_number(node: dict) -> None:
    """Remove heading words like 'الفصل' or 'المادة' from the number field."""
    if node.get("type") in ARTICLE_TYPES and isinstance(node.get("number"), str):
        node["number"] = re.sub(r"^(?:الفصل|فصل|المادة|مادة)\\s*", "", node["number"]).strip()


def clean_text(text: str) -> str:
    """Remove stray ASCII noise from article text."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r"[A-Za-z]+", "", text)
    text = re.sub(r"\\n\\s*\\d+\\s*\\n", "\\n", text)
    return text.strip()


def finalize_structure(tree: list) -> None:
    """Clean numbers/text and ensure only articles contain text."""
    for node in tree:
        clean_number(node)
        if node.get("type") not in ARTICLE_TYPES:
            node["text"] = ""
        else:
            node["text"] = clean_text(node.get("text", ""))
        if node.get("children"):
            finalize_structure(node["children"])

# ----------------------------------------------------------------------
# 12) Merge a chunk’s section‑array into the full tree
# ----------------------------------------------------------------------
def merge_chunk_structure(full_tree: list, chunk_array: list):
    """
    full_tree: list of nodes with keys {type, number, title, text, children}
    chunk_array: same structure for one chunk
    """
    for node in chunk_array:
        if not isinstance(node, dict) or "number" not in node:
            print(f"[Debug] Skipping malformed node: {node}")
            continue

        # Ensure the node always has a children list
        node.setdefault("children", [])

        # Match on both type and number to avoid merging nodes from different
        # levels that share the same numbering (e.g. "الباب الأول" vs
        # "الفصل الأول").
        match = next(
            (
                n
                for n in full_tree
                if n.get("type") == node.get("type")
                and n.get("number") == node["number"]
            ),
            None,
        )
        if match is None:
            # Append new nodes with an explicit children list
            node.setdefault("children", [])
            # Only articles should carry text; wipe it from higher level nodes
            if node.get("type") not in ARTICLE_TYPES:
                node["text"] = ""
            clean_number(node)
            if node.get("type") in ARTICLE_TYPES and node.get("text"):
                node["text"] = clean_text(node["text"])
            full_tree.append(node)
        else:
            # Existing nodes may not have the children key yet
            match.setdefault("children", [])
            if node.get("text") and match.get("type") in ARTICLE_TYPES:
                new = clean_text(node["text"])
                if match.get("text"):
                    existing = match["text"]
                    if existing and not existing.endswith("\\n") and not new.startswith("\\n"):
                        match["text"] = existing + "\\n" + new
                    else:
                        match["text"] = existing + new
                else:
                    match["text"] = new
            if node.get("children"):
                merge_chunk_structure(match["children"], node["children"])

# ----------------------------------------------------------------------
# 13) Main processing: OCR (if PDF) or read .txt, Pass 1, Pass 2, merge, save JSON
# ----------------------------------------------------------------------
def process_single_arabic(txt_path: str, output_dir: str) -> None:
    base     = os.path.basename(txt_path).rsplit(".", 1)[0]
    out_json = os.path.join(output_dir, f"{base}.json")

    print(f"\\n[*] Processing: {txt_path}")
    with open(txt_path, "r", encoding="utf-8") as f:
        arabic_text = f.read()

    # -------- PASS 1 --------
    print("[*] Pass 1: extracting metadata + skeleton of sections/subsections…")
    first_chunk = split_for_pass1(arabic_text)
    msgs1        = build_messages_for_pass1(first_chunk)

    used1  = count_tokens_for_messages(msgs1, GPT_MODEL)
    print(f"[Debug] Pass 1 prompt uses {used1} tokens; remaining = {MAX_CONTEXT - used1}")

    if (MAX_CONTEXT - used1) < 1000:
        print("⚠️  Fewer than 1000 tokens remain for GPT reply in Pass 1.")

    raw_full = ""
    try:
        raw_full = call_gpt_on_chunk(msgs1, json_mode=True)
        full_obj = json.loads(raw_full) if isinstance(raw_full, str) else raw_full
    except Exception as e:
        dbg = os.path.join(output_dir, "debug_pass1.txt")
        with open(dbg, "w", encoding="utf-8") as ff:
            ff.write(raw_full if isinstance(raw_full, str) else str(e))
        print(f"❌ Pass 1 failed: {e}")
        print(f"→ Saved debug to: {dbg}")
        return

    try:
        structure_tree = full_obj["structure"]
        if not isinstance(structure_tree, list):
            raise KeyError
        # Remove stray text from nodes that should never have it
        finalize_structure(structure_tree)
    except Exception:
        dbg = os.path.join(output_dir, "debug_pass1_structure.txt")
        with open(dbg, "w", encoding="utf-8") as ff:
            ff.write(raw_full)
        print("❌ Pass 1 returned unexpected JSON structure.")
        print(f"→ Saved debug to: {dbg}")
        return

    # -------- PASS 2 --------
    print("[*] Pass 2: extracting articles text in chunks…")
    pass2_chunks = split_for_pass2(arabic_text)
    inherited = ""
    prev_tail = ""
    for idx, chunk in enumerate(pass2_chunks, 1):
        print(f"[*] Processing chunk #{idx} ({len(chunk)} chars)")
        msgs2 = build_messages_for_pass2(prev_tail + chunk, inherited)
        raw_articles = ""
        try:
            raw_articles = call_gpt_on_chunk(msgs2, json_mode=False)
            print(raw_articles)  # debug print

            inherit_line, json_part = ("", raw_articles)
            if isinstance(raw_articles, str):
                inherit_line, json_part = extract_inherited(raw_articles)
                if inherit_line:
                    inherited_info = parse_inherited_fields(inherit_line)
                    inherited = inherit_line + "\n"
                else:
                    inherited = ""
            chunk_content = json_part
            if isinstance(chunk_content, str):
                chunk_content = remove_code_fences(chunk_content)

            try:
                chunk_data = json.loads(chunk_content) if isinstance(chunk_content, str) else chunk_content
                if isinstance(chunk_data, dict):
                    chunk_array = [chunk_data]
                elif isinstance(chunk_data, list):
                    chunk_array = chunk_data
                else:
                    raise ValueError("Not a JSON array")
            except Exception:
                print(f"⚠️  Chunk #{idx} returned invalid JSON; attempting repair")
                repaired = repair_chunk_json(raw_articles)
                chunk_array = repaired if repaired is not None else []

            if not chunk_array:
                print(f"⚠️  Chunk #{idx} produced no sections.")

            target_tree = structure_tree
            if inherit_line and inherited_info:
                parent = find_node(structure_tree, inherited_info["type"], inherited_info["number"])
                if parent is None:
                    parent = {
                        "type": inherited_info["type"],
                        "number": inherited_info["number"],
                        "title": inherited_info.get("title", ""),
                        "text": "" if inherited_info["type"] not in ARTICLE_TYPES else "",
                        "children": [],
                    }
                    structure_tree.append(parent)
                target_tree = parent.get("children", [])

            merge_chunk_structure(target_tree, chunk_array)
            print(f"[+] Merged {len(chunk_array)} nodes from chunk #{idx}")

            enc       = tiktoken.encoding_for_model(GPT_MODEL)
            tok       = enc.encode(chunk)
            tail      = tok[-100:] if len(tok) >= 100 else tok
            prev_tail = enc.decode(tail)

        except Exception as e:
            dbg = os.path.join(output_dir, f"debug_pass2_chunk_{idx}.txt")
            with open(dbg, "w", encoding="utf-8") as ff:
                ff.write(raw_articles if isinstance(raw_articles, str) else str(e))
            print(f"❌ Pass 2 chunk #{idx} failed: {e}")
            print(f"→ Saved debug to: {dbg}")
            continue

    # -------- Save final JSON --------
    finalize_structure(structure_tree)
    full_obj["structure"] = structure_tree
    with open(out_json, "w", encoding="utf-8") as fout:
        json.dump(full_obj, fout, ensure_ascii=False, indent=2)
    print(f"[+] Finished and saved JSON: {out_json}")

# ----------------------------------------------------------------------
# 14) Entrypoint: --input (PDF or .txt), --output_dir
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="OCR (if PDF) and parse Moroccan legislation into a nested section tree (JSON)."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a PDF or OCR’d .txt file."
    )
    parser.add_argument(
        "--output_dir",
        required=True,
        help="Directory where intermediate .txt (if PDF) and final JSON will be saved."
    )
    parser.add_argument(
        "--model",
        default=GPT_MODEL,
        help="OpenAI model name to use (default: %(default)s)",
    )
    args = parser.parse_args()
    adjust_for_model(args.model)

    input_path = args.input
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    if input_path.lower().endswith(".pdf"):
        print(f"[*] OCRing PDF: {input_path}")
        base     = os.path.basename(input_path).rsplit(".", 1)[0]
        txt_base = f"{base}.txt"
        txt_path = os.path.join(output_dir, txt_base)

        arabic_text = pdf_to_arabic_text(input_path)
        with open(txt_path, "w", encoding="utf-8") as ff:
            ff.write(arabic_text)

    elif input_path.lower().endswith(".txt"):
        txt_path = input_path
    else:
        print(f"❌ Input must be a PDF or .txt: {input_path}")
        sys.exit(1)

    process_single_arabic(txt_path, output_dir)

if __name__ == "__main__":
    main()
