import argparse
import os
import sys
import time

import pandas as pd
import requests
import re


def main():
    parser = argparse.ArgumentParser(description="Simple batch runner for test chat API")
    parser.add_argument("--excel", default="/home/vdsmart/eyepro-insight/tools/Câu hỏi ETUGI.xlsx", help="Excel path (default: input.xlsx)")
    parser.add_argument("--url", default="http://10.0.0.69:9621/query", help="API URL (default: http://10.0.0.69:9621/query)")
    parser.add_argument("--user_id", default="TDHH6", help="User ID (default: TDH6)")
    parser.add_argument("--output", default="batch_chat_results_2.csv", help="CSV log output path")
    args = parser.parse_args()

    if not os.path.exists(args.excel):
        print(f"Excel file not found: {args.excel}")
        sys.exit(1)

    # 1) Get questions from sheet "Câu hỏi", column A (question) and column E (school), starting row 2 (header present)
    try:
        df = pd.read_excel(args.excel, sheet_name="Sheet1", header=0)
    except Exception as e:
        print(f"Failed to read Excel: {e}")
        sys.exit(1)

    # Prepare log file (create if missing) and remember whether we need headers
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    output_exists = os.path.exists(args.output)
    if not output_exists:
        open(args.output, "w").close()
    write_header = os.path.getsize(args.output) == 0

    def append_log_rows(rows):
        """Append current batch of rows to CSV immediately."""
        nonlocal write_header
        if not rows:
            return
        pd.DataFrame(rows).to_csv(
            args.output, mode="a", header=write_header, index=False
        )
        write_header = False

    # 2) Loop through questions row-by-row to keep question/school aligned
    session = requests.Session()

    # Prepare user_id incrementing: split base and numeric suffix if present
    base_user_id = args.user_id
    match = re.match(r'^(.*?)(\d+)$', base_user_id)
    base_prefix = match.group(1) if match else base_user_id
    base_number = int(match.group(2)) if match else None

    for offset, (_, row) in enumerate(df.iterrows()):
        # Excel row numbering with header at row 1 => first data row is row 2
        print(row)
        excel_row = 2 + offset

        # Extract question and school from the current row
        question = str(row.get("Câu hỏi", "")).strip()
        # Take value directly from column "School"
        school_cell = row.get("School", "")
        print(f"School column value: '{school_cell}'")
        school_value = str(school_cell).strip() if pd.notna(school_cell) else ""

        if not question:
            continue
        # Compute per-row user_id
        if base_number is not None:
            effective_user_id = f"{base_prefix}{base_number + offset}"
        else:
            effective_user_id = f"{base_prefix}{excel_row}"
        payload = {"query": question, "mode": "local", "school": school_value}
        print(payload)
        started_at = time.time()
        status = None
        reply = ""
        err = ""
        try:
            resp = session.post(args.url, json=payload, timeout=180)
            status = resp.status_code
            try:
                data = resp.json()
                # New response schema: {"response": "...", "references": [...]}
                if isinstance(data, dict):
                    if "response" in data:
                        reply = str(data.get("response", ""))
                    # Backward compatibility with old schema
                    elif isinstance(data.get("replies"), list) and data.get("replies"):
                        joined = []
                        for item in data.get("replies", []):
                            model = item.get("model", "model") if isinstance(item, dict) else "model"
                            content = item.get("content", "") if isinstance(item, dict) else str(item)
                            joined.append(f"[{model}]\n{content}")
                        reply = "\n\n".join(joined)
                    else:
                        reply = data.get("reply", "") if isinstance(data, dict) else resp.text
                else:
                    reply = resp.text
            except Exception:
                reply = resp.text
        except Exception as e:
            err = str(e)

        elapsed = time.time() - started_at

        # 3) Log input, output, time
        print(f"Row ~{excel_row}: time={elapsed:.2f}s status={status} user_id={effective_user_id} school={school_value}\nQ: {question}\nA: {reply[:2000]}\n---")
        rows_to_write = [
            {
                "excel_row": excel_row,
                "question": question,
                "school": school_value,
                "user_id": effective_user_id,
                "reply": reply,
                "status_code": status,
                "elapsed_seconds": round(elapsed, 2),
                "error": err,
            }
        ]
        # Also store raw replies JSON if available
        try:
            data_for_raw = resp.json() if 'resp' in locals() else None
            if isinstance(data_for_raw, dict) and isinstance(data_for_raw.get("replies"), list):
                rows_to_write[0]["replies_json"] = data_for_raw["replies"]
                # Extract model names for summary columns
                model_names = []
                for item in data_for_raw.get("replies", []):
                    if isinstance(item, dict):
                        model_names.append(str(item.get("model", "unknown-model")))
                    else:
                        model_names.append("unknown-model")
                rows_to_write[0]["models"] = ", ".join(model_names)
                rows_to_write[0]["num_models"] = len(model_names)
                # Emit a row per model with its individual content for easy viewing
                for item in data_for_raw.get("replies", []):
                    if not isinstance(item, dict):
                        continue
                    rows_to_write.append(
                        {
                            "excel_row": excel_row,
                            "question": question,
                            "school": school_value,
                            "user_id": effective_user_id,
                            "model": item.get("model", "unknown-model"),
                            "reply": item.get("content", ""),
                            "status_code": status,
                            "elapsed_seconds": round(elapsed, 2),
                            "error": err,
                            "row_type": "model",
                        }
                    )
                rows_to_write[0]["row_type"] = "summary"
        except Exception:
            pass
        append_log_rows(rows_to_write)

    print(f"Appended logs to {args.output}")


if __name__ == "__main__":
    main()


