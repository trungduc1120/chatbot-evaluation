import argparse
import os
import sys
import time

import pandas as pd
import requests
import re


def main():
    parser = argparse.ArgumentParser(description="Simple batch runner for test chat API")
    parser.add_argument("--excel", default="/home/vdsmart/eyepro-insight/tools/đánh giá SLM.xlsx", help="Excel path (default: input.xlsx)")
    parser.add_argument("--url", default="http://localhost:8001/chat", help="API URL (default: http://localhost:8001/chat)")
    parser.add_argument("--user_id", default="TDHH6", help="User ID (default: TDH6)")
    parser.add_argument("--school", default="test3", help="School (default: test3)")
    parser.add_argument("--output", default="batch_chat_results.csv", help="CSV log output path")
    args = parser.parse_args()

    if not os.path.exists(args.excel):
        print(f"Excel file not found: {args.excel}")
        sys.exit(1)

    # 1) Get questions from sheet "Câu hỏi", column A (question) and column E (school), starting row 2 (header present)
    try:
        df = pd.read_excel(args.excel, sheet_name="Câu hỏi", header=0)
    except Exception as e:
        print(f"Failed to read Excel: {e}")
        sys.exit(1)

    # Questions in column A (index 0), School in column E (index 4), both starting at row 2 (header at row 1)
    questions_series = df.iloc[:, 0]
    schools_series = df.iloc[:, 4]
    questions = []
    schools = []
    for q_val, s_val in zip(questions_series.tolist(), schools_series.tolist()):
        q_str = str(q_val).strip() if pd.notna(q_val) else ""
        if not q_str:
            questions.append("")
            schools.append("")
            continue
        s_str = str(s_val).strip() if pd.notna(s_val) else ""
        questions.append(q_str)
        schools.append(s_str)

    # 2) Loop through questions
    session = requests.Session()
    logs = []

    # Prepare user_id incrementing: split base and numeric suffix if present
    base_user_id = args.user_id
    match = re.match(r'^(.*?)(\d+)$', base_user_id)
    base_prefix = match.group(1) if match else base_user_id
    base_number = int(match.group(2)) if match else None

    for offset, question in enumerate(questions):
        # Excel row numbering with header at row 1 => first data row is row 2
        excel_row = 2 + offset
        if not question:
            continue
        school_cell = schools[offset] if offset < len(schools) else ""
        school_value = school_cell if school_cell else args.school
        # Compute per-row user_id
        if base_number is not None:
            effective_user_id = f"{base_prefix}{base_number + offset}"
        else:
            effective_user_id = f"{base_prefix}{excel_row}"
        payload = {"user_id": effective_user_id, "school": school_value, "message": question}
        started_at = time.time()
        status = None
        reply = ""
        err = ""
        try:
            resp = session.post(args.url, json=payload, timeout=180)
            status = resp.status_code
            try:
                data = resp.json()
                # Support both single reply and multiple replies
                if isinstance(data, dict) and isinstance(data.get("replies"), list) and data.get("replies"):
                    # Join multiple replies for CSV readability
                    joined = []
                    for item in data.get("replies", []):
                        model = item.get("model", "model") if isinstance(item, dict) else "model"
                        content = item.get("content", "") if isinstance(item, dict) else str(item)
                        joined.append(f"[{model}]\n{content}")
                    reply = "\n\n".join(joined)
                else:
                    reply = data.get("reply", "") if isinstance(data, dict) else resp.text
            except Exception:
                reply = resp.text
        except Exception as e:
            err = str(e)

        elapsed = time.time() - started_at

        # 3) Log input, output, time
        print(f"Row ~{excel_row}: time={elapsed:.2f}s status={status} user_id={effective_user_id} school={school_value}\nQ: {question}\nA: {reply[:2000]}\n---")
        log_row = {
            "excel_row": excel_row,
            "question": question,
            "school": school_value,
            "user_id": effective_user_id,
            "reply": reply,
            "status_code": status,
            "elapsed_seconds": round(elapsed, 2),
            "error": err,
        }
        # Also store raw replies JSON if available
        try:
            data_for_raw = resp.json() if 'resp' in locals() else None
            if isinstance(data_for_raw, dict) and isinstance(data_for_raw.get("replies"), list):
                log_row["replies_json"] = data_for_raw["replies"]
                # Extract model names for summary columns
                model_names = []
                for item in data_for_raw.get("replies", []):
                    if isinstance(item, dict):
                        model_names.append(str(item.get("model", "unknown-model")))
                    else:
                        model_names.append("unknown-model")
                log_row["models"] = ", ".join(model_names)
                log_row["num_models"] = len(model_names)
                # Emit a row per model with its individual content for easy viewing
                for item in data_for_raw.get("replies", []):
                    if not isinstance(item, dict):
                        continue
                    per_model = {
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
                    logs.append(per_model)
                log_row["row_type"] = "summary"
        except Exception:
            pass
        logs.append(log_row)

    pd.DataFrame(logs).to_csv(args.output, index=False)
    print(f"Saved log to {args.output}")


if __name__ == "__main__":
    main()


