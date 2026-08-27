import argparse
import os
import re
import sys
import csv


def parse_blocks(lines):
    block = {}
    in_user = False
    in_resp = False

    def flush_block():
        nonlocal block
        if block:
            # strip trailing whitespace
            for k in ("user_prompt", "response"):
                if k in block and isinstance(block[k], str):
                    block[k] = block[k].rstrip("\n")
            yield_block = block
            block = {}
            return yield_block
        return None

    for line in lines:
        s = line.rstrip("\n")
        # Separator or new block header indicates a boundary
        is_header = s.startswith("[") and "] model=" in s
        is_separator = (len(s) > 0 and set(s) == {"-"})

        if is_header or is_separator:
            # boundary: finish any response capture
            yielded = flush_block()
            if yielded:
                yield yielded
            in_user = False
            in_resp = False

            if is_header:
                # Start new block and capture model
                try:
                    model_part = s.split("]", 1)[1].strip()
                    if model_part.startswith("model="):
                        block["model"] = model_part.split("=", 1)[1]
                except Exception:
                    pass
            continue

        # While capturing, detect starts/ends
        if s.startswith("elapsed="):
            val = s.split("=", 1)[1].strip()
            if val.endswith("s"):
                val = val[:-1]
            block["elapsed"] = val
            continue

        if s.startswith("user_prompt="):
            in_user = True
            in_resp = False
            first = s.split("=", 1)[1]
            block["user_prompt"] = (first + "\n") if first else ""
            continue

        if s.startswith("response="):
            in_resp = True
            in_user = False
            first = s.split("=", 1)[1]
            block["response"] = (first + "\n") if first else ""
            continue

        # Stop collection if we hit other known keys
        if s.startswith(("status_code=", "sent_at=", "finished_at=", "system_prompt=")):
            in_user = False
            # Do not unset in_resp because response can include arbitrary text

        # Append content lines to current field
        if in_user:
            block["user_prompt"] = block.get("user_prompt", "") + s + "\n"
            continue
        if in_resp:
            block["response"] = block.get("response", "") + s + "\n"
            continue

        # ignore other lines

    # end of file
    yielded = flush_block()
    if yielded:
        yield yielded


def contains_star_separators(lines) -> bool:
    for s in lines:
        if s.strip().startswith("***") and set(s.strip()) == {"*"} and len(s.strip()) >= 5:
            return True
    return False


def parse_blocks_by_stars(lines):
    text = "".join(lines)
    # Split on lines made entirely of 5+ stars
    chunks = re.split(r"\n\*{5,}\n", text)
    for chunk in chunks:
        if not chunk or chunk.strip() == "":
            continue
        blk = {}
        # elapsed
        m_elapsed = re.search(r"^elapsed=([^\n\r]+)", chunk, flags=re.MULTILINE)
        if m_elapsed:
            val = m_elapsed.group(1).strip()
            if val.endswith("s"):
                val = val[:-1]
            blk["elapsed"] = val
        # user_prompt: from 'user_prompt=' up to '\nresponse='
        m_user = re.search(r"user_prompt=(.*?)\nresponse=", chunk, flags=re.DOTALL)
        if m_user:
            blk["user_prompt"] = m_user.group(1).rstrip("\n")
        # response: from 'response=' up to next '\nelapsed=' or end
        m_resp = re.search(r"response=(.*?)(?:\nelapsed=|\Z)", chunk, flags=re.DOTALL)
        if m_resp:
            blk["response"] = m_resp.group(1).rstrip("\n")
        if blk:
            yield blk


def convert(in_path: str, out_path: str, delimiter: str = ",", minimal: bool = False) -> int:
    if not os.path.exists(in_path):
        print(f"Input log not found: {in_path}")
        return 1
    with open(in_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    rows = []
    # Choose parsing strategy
    if contains_star_separators(lines):
        blocks_iter = parse_blocks_by_stars(lines)
    else:
        blocks_iter = parse_blocks(lines)
    for blk in blocks_iter:
        row = {
            "user_prompt": blk.get("user_prompt", ""),
            "respond": blk.get("response", ""),
            "model": blk.get("model", ""),
            "elapsed_time": blk.get("elapsed", ""),
        }
        rows.append(row)

    # Write CSV
    fieldnames = ["user_prompt", "respond", "model", "elapsed_time"]
    if minimal:
        fieldnames = ["user_prompt", "respond", "elapsed_time"]
    with open(out_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=fieldnames,
            delimiter=delimiter,
            quoting=csv.QUOTE_ALL,
            lineterminator="\n",
        )
        writer.writeheader()
        for r in rows:
            if minimal:
                writer.writerow({k: r.get(k, "") for k in fieldnames})
            else:
                writer.writerow(r)

    print(f"Wrote {len(rows)} rows to {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert OpenRouter multimodel logs to CSV")
    parser.add_argument("--input", default="/home/vdsmart/eyepro-insight/openrouter_multimodel_logs.txt", help="Path to log file")
    parser.add_argument("--output", default="/home/vdsmart/eyepro-insight/openrouter_multimodel_logs.csv", help="Path to output CSV")
    parser.add_argument("--delimiter", default=",", help="CSV delimiter (use ';' for some Excel locales)")
    parser.add_argument("--minimal", action="store_true", help="Output only user_prompt, respond, elapsed_time")
    args = parser.parse_args()
    return convert(args.input, args.output, delimiter=args.delimiter, minimal=args.minimal)


if __name__ == "__main__":
    sys.exit(main())


