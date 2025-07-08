import argparse
import re

try:
    from .ner import parse_marked_text, text_with_markers, fix_entity_offsets
except Exception:  # pragma: no cover - allow standalone use
    from ner import parse_marked_text, text_with_markers, fix_entity_offsets  # type: ignore


def _next_id(entities: list[dict]) -> str:
    nums: list[int] = []
    for e in entities:
        sid = str(e.get("id", ""))
        m = re.search(r"(\d+)$", sid)
        if m:
            try:
                nums.append(int(m.group(1)))
            except Exception:
                pass
    n = max(nums) + 1 if nums else 1
    return f"ENT_{n}"


def load_file(path: str) -> tuple[str, list[dict]]:
    with open(path, "r", encoding="utf-8") as f:
        data = f.read()
    if "[[ENT" in data:
        text, entities = parse_marked_text(data)
    else:
        text = data
        entities = []
    return text, entities


def save_file(path: str, text: str, entities: list[dict]) -> None:
    marked = text_with_markers(text, entities)
    with open(path, "w", encoding="utf-8") as f:
        f.write(marked)


def add_entity(args, text: str, entities: list[dict]) -> None:
    start, end, typ = int(args.add[0]), int(args.add[1]), args.add[2]
    if not (0 <= start < end <= len(text)):
        raise ValueError("Invalid start/end for add")
    ent = {
        "id": _next_id(entities),
        "type": typ,
        "text": text[start:end],
        "start_char": start,
        "end_char": end,
    }
    if args.norm:
        ent["normalized"] = args.norm
    entities.append(ent)


def delete_entity(args, entities: list[dict]) -> None:
    entities[:] = [e for e in entities if str(e.get("id")) != args.delete]


def update_entity(args, entities: list[dict]) -> None:
    uid = args.update[0]
    fields = args.update[1:]
    target = None
    for e in entities:
        if str(e.get("id")) == uid:
            target = e
            break
    if target is None:
        raise ValueError(f"Entity {uid} not found")
    for item in fields:
        if "=" not in item:
            continue
        key, val = item.split("=", 1)
        if key.lower() == "type":
            target["type"] = val
        elif key.lower() in {"norm", "normalized"}:
            target["normalized"] = val
        elif key.lower() == "start":
            target["start_char"] = int(val)
        elif key.lower() == "end":
            target["end_char"] = int(val)


def replace_text(args, text: str, entities: list[dict]) -> str:
    start, end = int(args.replace_text[0]), int(args.replace_text[1])
    new_text = args.replace_text[2]
    if not (0 <= start <= end <= len(text)):
        raise ValueError("Invalid start/end for replace-text")
    delta = len(new_text) - (end - start)
    text = text[:start] + new_text + text[end:]
    kept: list[dict] = []
    for e in entities:
        s = int(e.get("start_char", 0))
        e_end = int(e.get("end_char", 0))
        if e_end <= start:
            kept.append(e)
            continue
        if s >= end:
            e["start_char"] = s + delta
            e["end_char"] = e_end + delta
            kept.append(e)
            continue
        if s < start:
            e["end_char"] = min(e_end, start)
            e["text"] = text[e["start_char"] : e["end_char"]]
            kept.append(e)
    entities[:] = kept
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Edit annotated entity markers")
    parser.add_argument("file", help="Annotated text file")
    parser.add_argument("--add", nargs=3, metavar=("START", "END", "TYPE"))
    parser.add_argument("--norm", metavar="VAL")
    parser.add_argument("--delete", metavar="ID")
    parser.add_argument("--update", nargs="+", metavar="ITEM")
    parser.add_argument("--replace-text", nargs=3, metavar=("START", "END", "TEXT"))
    parser.add_argument("--fix-offsets", action="store_true")
    args = parser.parse_args()

    ops = [args.add, args.delete, args.update, args.replace_text]
    if sum(op is not None for op in ops) != 1:
        parser.error("Specify exactly one of --add, --delete, --update or --replace-text")

    text, entities = load_file(args.file)

    if args.add:
        add_entity(args, text, entities)
    elif args.delete:
        delete_entity(args, entities)
    elif args.update:
        update_entity(args, entities)
    elif args.replace_text:
        text = replace_text(args, text, entities)

    if args.fix_offsets:
        fix_entity_offsets(text, {"entities": entities})

    save_file(args.file, text, entities)
    print(f"[+] Updated {args.file}")


if __name__ == "__main__":
    main()
