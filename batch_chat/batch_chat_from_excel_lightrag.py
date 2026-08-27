#!/usr/bin/env python3
"""
Batch runner đơn giản: chỉ lưu 3 cột (stt, câu hỏi, response), UTF-8 (BOM).
Retry các row có response trống. Dùng stt làm index duy nhất.
"""

import argparse
import json
import logging
import os
import sys
import time

import pandas as pd
import requests

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


DEFAULT_PAYLOAD = {
    "mode": "mix",
    "top_k": 40,
    "chunk_top_k": 20,
    "max_entity_tokens": 3000,
    "max_relation_tokens": 4000,
    "max_total_tokens": 20000,
    "only_need_context": False,
    "only_need_prompt": False,
    "stream": False,
    "history_turns": 0,
    "user_prompt": "",
    "enable_rerank": True,
    "metadata_matching": False,
    "llm_model": "google/gemini-3.1-flash-lite-preview",
    "avatar": False,
    "profile": ""
}


def parse_arguments():
    parser = argparse.ArgumentParser(description="Batch runner đơn giản cho chat API")
    # Chạy từ thư mục batch_chat: input file nằm trong subfolder inputs/
    parser.add_argument("--excel", default=r"inputs/Danh sách câu hỏi Đại học Kiên Giang.xlsx")
    parser.add_argument("--url", default="http://10.8.0.23:9621/query/stream")
    parser.add_argument("--school", default="VNKGU")
    parser.add_argument("--user_id", default="TDHH6")
    # Ghi output vào thư mục hiện tại (Windows-friendly)
    parser.add_argument("--output", default="batch_chat_results_vnkgu_w_lightrag.csv")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=int, default=5)
    
    return parser.parse_args()


def load_questions(excel_path):
    if not os.path.exists(excel_path):
        logger.error(f"Excel not found: {excel_path}")
        sys.exit(1)
    try:
        # File này có sheet thực tế là 'Câu hỏi'
        df = pd.read_excel(excel_path, sheet_name="Câu hỏi", header=0)
        logger.info(f"Loaded {len(df)} questions")
        return df
    except Exception as e:
        logger.error(f"Failed to read Excel: {e}")
        sys.exit(1)


def extract_response(text):
    """Lấy field 'response' từ output stream (mỗi dòng là 1 JSON object), gom tất cả các chunk."""
    if not text:
        return ""
    parts = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "response" in obj:
            parts.append(str(obj["response"]))
    if parts:
        return "".join(parts)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "response" in obj:
            return str(obj["response"])
    except json.JSONDecodeError:
        pass
    return text


def call_api(session, url, payload, max_retries, retry_delay):
    for attempt in range(max_retries + 1):
        try:
            start = time.time()
            resp = session.post(url, json=payload, timeout=180)
            elapsed = time.time() - start
            status = resp.status_code
            reply = extract_response(resp.text)
            return status, reply, "", elapsed
        except Exception as e:
            error = str(e)
            if attempt < max_retries:
                logger.warning(f"Retry {attempt+1}/{max_retries}: {error}")
                time.sleep(retry_delay)
            else:
                return None, "", error, time.time() - start


def main():
    args = parse_arguments()
    questions_df = load_questions(args.excel)
    session = requests.Session()

    # 1. Check file kết quả cũ
    output_exists = os.path.exists(args.output) and os.path.getsize(args.output) > 0

    COLUMNS = ["stt", "câu hỏi", "response"]

    if not output_exists:
        logger.info("No existing results → run all questions")
        results_df = pd.DataFrame(columns=COLUMNS)
        rows_to_process = list(range(len(questions_df)))
    else:
        try:
            results_df = pd.read_csv(args.output, encoding="utf-8-sig")
            logger.info(f"Loaded {len(results_df)} rows from existing CSV")
        except Exception as e:
            logger.warning(f"Cannot read CSV: {e} → run all")
            results_df = pd.DataFrame(columns=COLUMNS)
            rows_to_process = list(range(len(questions_df)))
        else:
            results_df["stt"] = results_df["stt"].astype("Int64")
            # Retry row có response trống
            rows_to_process = []
            for i, _ in questions_df.iterrows():
                excel_row = 1 + i
                existing = results_df[results_df["stt"] == excel_row]
                if existing.empty:
                    rows_to_process.append(i)
                else:
                    resp = existing["response"].iloc[0]
                    if pd.isna(resp) or str(resp).strip() == "":
                        rows_to_process.append(i)
                    else:
                        logger.info(f"Skip row {excel_row} (đã có response)")

            logger.info(f"Will retry/reprocess {len(rows_to_process)} rows")

    # 2. Xử lý các row cần chạy
    for i in rows_to_process:
        excel_row = 1 + i
        question = str(questions_df.iloc[i].get("Câu hỏi", "")).strip()
        if not question:
            continue

        user_id = f"{args.user_id[:-1]}{int(args.user_id[-1]) + i}" if args.user_id[-1].isdigit() else f"{args.user_id}{excel_row}"

        payload = {**DEFAULT_PAYLOAD, "query": question, "school": args.school, "user_id": str(user_id)}

        logger.info(f"Processing row {excel_row} | user={user_id} | Q: {question[:80]}...")

        status, reply, error, elapsed = call_api(
            session, args.url, payload, args.max_retries, args.retry_delay
        )

        if status != 200:
            logger.warning(f"Row {excel_row} failed: status={status} error={error}")

        new_row = {
            "stt": excel_row,
            "câu hỏi": question,
            "response": reply if status == 200 else "",
        }

        mask = results_df["stt"] == excel_row if "stt" in results_df.columns and not results_df.empty else None
        if mask is not None and mask.any():
            results_df.loc[mask, COLUMNS] = [new_row[c] for c in COLUMNS]
            logger.info(f"Replaced row {excel_row}")
        else:
            results_df = pd.concat([results_df, pd.DataFrame([new_row])], ignore_index=True)
            logger.info(f"Added new row {excel_row}")

        # Lưu ngay sau mỗi row (UTF-8 với BOM để Excel mở đúng tiếng Việt)
        results_df[COLUMNS].fillna("").to_csv(
            args.output, index=False, encoding="utf-8-sig"
        )
        logger.info(f"Saved progress after row {excel_row}")

    logger.info("Done. All results saved.")


if __name__ == "__main__":
    main()