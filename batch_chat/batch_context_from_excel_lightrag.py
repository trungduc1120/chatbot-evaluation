#!/usr/bin/env python3
"""
Batch runner lấy CONTEXT (only_need_context=True) từ chat API LightRAG.
Trích xuất document chunks (chunk_id, title, content) ra CSV tổng hợp.

Output CSV header: STT, Câu hỏi, chunk_id, title, content
- Mỗi câu hỏi = 1 dòng.
- Nếu 1 câu hỏi có nhiều chunk: gộp vào cùng 1 cell, ngăn cách bằng xuống dòng.

Retry các row có chunk_id trống. Dùng stt làm index duy nhất.
"""

import argparse
import json
import logging
import os
import re
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
    "only_need_context": True,   # <-- chỉ lấy context
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
    parser = argparse.ArgumentParser(description="Batch context runner cho chat API (only_need_context)")
    parser.add_argument("--excel", default="/home/vdsmart/eyepro-insight/tools/inputs/Câu hỏi Test SmartLib site VDSMART.xlsx")
    parser.add_argument("--url", default="http://10.8.0.23:9622/query/stream")
    parser.add_argument("--school", default="VDSMART")
    parser.add_argument("--output", default="/home/vdsmart/eyepro-insight/tools/batch_context_results_VDSMART.csv")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=int, default=5)
    return parser.parse_args()


def load_questions(excel_path):
    if not os.path.exists(excel_path):
        logger.error(f"Excel not found: {excel_path}")
        sys.exit(1)
    try:
        df = pd.read_excel(excel_path, sheet_name="Câu hỏi Tiếng Việt", header=0)
        logger.info(f"Loaded {len(df)} questions")
        return df
    except Exception as e:
        logger.error(f"Failed to read Excel: {e}")
        sys.exit(1)


def extract_response(text):
    """Lấy field 'response' từ output stream (mỗi dòng là 1 JSON object)."""
    if not text:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "response" in obj:
            return str(obj["response"])
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "response" in obj:
            return str(obj["response"])
    except json.JSONDecodeError:
        pass
    return text


def extract_chunks(response_text):
    """
    Trích document chunks từ context.
    Phần 'Document Chunks' là 1 block ```json ... ``` với mỗi dòng là 1 JSON object
    chứa: reference_id, chunk_id, title, content (có thể có thêm field khác).
    Trả về list dict [{chunk_id, title, content}, ...].
    """
    chunks = []
    if not response_text:
        return chunks

    idx = response_text.find("Document Chunks")
    if idx == -1:
        return chunks

    sub = response_text[idx:]
    m = re.search(r"```json\s*(.*?)```", sub, re.S)
    if not m:
        return chunks

    block = m.group(1)
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "chunk_id" in obj:
            chunks.append({
                "chunk_id": str(obj.get("chunk_id", "")),
                "title": str(obj.get("title", "")),
                "content": str(obj.get("content", "")),
            })
    return chunks


def call_api(session, url, payload, max_retries, retry_delay):
    start = time.time()
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

    COLUMNS = ["STT", "Câu hỏi", "chunk_id", "title", "content"]

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
            results_df["STT"] = results_df["STT"].astype("Int64")
            # Retry row có chunk_id trống
            rows_to_process = []
            for i, _ in questions_df.iterrows():
                excel_row = 1 + i
                existing = results_df[results_df["STT"] == excel_row]
                if existing.empty:
                    rows_to_process.append(i)
                else:
                    cid = existing["chunk_id"].iloc[0]
                    if pd.isna(cid) or str(cid).strip() == "":
                        rows_to_process.append(i)
                    else:
                        logger.info(f"Skip row {excel_row} (đã có chunk)")

            logger.info(f"Will retry/reprocess {len(rows_to_process)} rows")

    # 2. Xử lý các row cần chạy
    for i in rows_to_process:
        excel_row = 1 + i
        question = str(questions_df.iloc[i].get("Câu hỏi", "")).strip()
        if not question:
            continue

        payload = {**DEFAULT_PAYLOAD, "query": question, "school": args.school}

        logger.info(f"Processing row {excel_row} | Q: {question[:80]}...")

        status, reply, error, elapsed = call_api(
            session, args.url, payload, args.max_retries, args.retry_delay
        )

        if status != 200:
            logger.warning(f"Row {excel_row} failed: status={status} error={error}")
            chunks = []
        else:
            chunks = extract_chunks(reply)
            logger.info(f"Row {excel_row}: {len(chunks)} chunks ({elapsed:.1f}s)")

        # Gộp nhiều chunk vào cùng 1 cell, ngăn cách bằng xuống dòng
        new_row = {
            "STT": excel_row,
            "Câu hỏi": question,
            "chunk_id": "\n".join(c["chunk_id"] for c in chunks),
            "title": "\n".join(c["title"] for c in chunks),
            "content": "\n".join(c["content"] for c in chunks),
        }

        mask = results_df["STT"] == excel_row if "STT" in results_df.columns and not results_df.empty else None
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
