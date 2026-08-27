#!/usr/bin/env python3
"""
Batch runner đơn giản: retry chỉ các row có status_code != 200 hoặc trống.
Dùng excel_row làm index duy nhất.
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
    "only_need_context": False,
    "only_need_prompt": False,
    "response_type": "Multiple Paragraphs",
    "top_k": 40,
    "chunk_top_k": 20,
    "max_entity_tokens": 6000,
    "max_relation_tokens": 8000,
    "max_total_tokens": 50000,
    "hl_keywords": [],
    "ll_keywords": [],
    "conversation_history": [],
    "user_prompt": "",
    "enable_rerank": True,
    "metadata_matching": False,
    "include_references": True,
    "include_chunk_content": False,
    "stream": False,
    "llm_model": "mistralai/devstral-2512",
    "avatar": True,
    "profile":  "Đây là hồ sơ của chị Nguyễn Văn Thị Mai Anh, sinh ngày 10/10/1990. Sở thích: Đánh cầu lông. Tình trạng sức khỏe: Thường xuyên bị đau bụng và dễ bị ốm và đau đầu. Bài hát yêu thích: Nàng thơ (https://www.youtube.com/watch?v=Zzn9-ATB9aU&list=RDZzn9-ATB9aU)."
}


def parse_arguments():
    parser = argparse.ArgumentParser(description="Batch runner đơn giản cho chat API")
    parser.add_argument("--excel", default="/home/vdsmart/eyepro-insight/tools/Câu hỏi BTC.xlsx")
    parser.add_argument("--url", default="http://10.8.0.23:9621/query/stream")
    parser.add_argument("--school", default="Bộ Tài Chính")
    parser.add_argument("--user_id", default="TDHH6")
    parser.add_argument("--output", default="/home/vdsmart/eyepro-insight/tools/batch_chat_results_btc_rta_lightrag.csv")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=int, default=5)
    
    return parser.parse_args()


def load_questions(excel_path):
    if not os.path.exists(excel_path):
        logger.error(f"Excel not found: {excel_path}")
        sys.exit(1)
    try:
        df = pd.read_excel(excel_path, sheet_name="Tiếng Việt(Gemini Ground Truth)", header=0)
        logger.info(f"Loaded {len(df)} questions")
        return df
    except Exception as e:
        logger.error(f"Failed to read Excel: {e}")
        sys.exit(1)


def call_api(session, url, payload, max_retries, retry_delay):
    for attempt in range(max_retries + 1):
        try:
            start = time.time()
            resp = session.post(url, json=payload, timeout=180)
            elapsed = time.time() - start
            status = resp.status_code
            reply = ""
            try:
                # Parse JSONL format: first line has "type", second line has "response"
                lines = resp.text.strip().split('\n')
                
                if len(lines) >= 1:
                    # Parse first line to get type
                    first_obj = json.loads(lines[0])
                    response_type = str(first_obj.get("type", ""))
                    
                    if response_type == "in_scope" and len(lines) >= 2:
                        # Parse second line to get response
                        second_obj = json.loads(lines[1])
                        reply = str(second_obj.get("response", ""))
                        logger.info("Received in_scope response")
                    elif response_type in ["out_of_scope", "not_a_question"]:
                        # For these types, response might be in the same object or separate
                        if len(lines) >= 2:
                            second_obj = json.loads(lines[1])
                            reply = str(second_obj.get("response", ""))
                        else:
                            reply = str(first_obj.get("response", ""))
                        logger.info(f"Received {response_type} response")
                    else:
                        logger.warning(f"Unknown response type: {response_type}")
                    
                    return status, reply, "", elapsed
                else:
                    logger.warning("Empty response")
                    return status, "", "Empty response", elapsed
                    
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON response: {e}")
                return status, resp.text, str(e), elapsed
                
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

    if not output_exists:
        logger.info("No existing results → run all questions")
        results_df = pd.DataFrame()
        rows_to_process = list(range(len(questions_df)))
    else:
        try:
            results_df = pd.read_csv(args.output)
            logger.info(f"Loaded {len(results_df)} rows from existing CSV")
        except Exception as e:
            logger.warning(f"Cannot read CSV: {e} → run all")
            results_df = pd.DataFrame()
            rows_to_process = list(range(len(questions_df)))
        else:
            # Chỉ retry các row có status_code != 200 hoặc trống
            results_df["excel_row"] = results_df["excel_row"].astype("Int64")  # cho phép NaN
            valid_mask = (
                results_df["status_code"].notna() &
                (results_df["status_code"] == 200)
            )
            rows_to_process = []
            for i, row in questions_df.iterrows():
                excel_row = 1 + i
                # Tìm xem row này đã có trong CSV chưa
                existing = results_df[results_df["excel_row"] == excel_row]
                if existing.empty:
                    rows_to_process.append(i)
                else:
                    status = existing["status_code"].iloc[0]
                    print(status)
                    if pd.isna(status) or status != 200:
                        rows_to_process.append(i)
                    else:
                        logger.info(f"Skip row {excel_row} (status=200)")

            logger.info(f"Will retry/reprocess {len(rows_to_process)} rows")

    # 2. Xử lý các row cần chạy
    for i in rows_to_process:
        excel_row = 1 + i
        question = str(questions_df.iloc[i].get("Câu hỏi", "")).strip()
        if not question:
            continue

        user_id = f"{args.user_id[:-1]}{int(args.user_id[-1]) + i}" if args.user_id[-1].isdigit() else f"{args.user_id}{excel_row}"

        payload = {**DEFAULT_PAYLOAD, "query": question, "school": args.school}

        logger.info(f"Processing row {excel_row} | user={user_id} | Q: {question[:80]}...")

        status, reply, error, elapsed = call_api(
            session, args.url, payload, args.max_retries, args.retry_delay
        )
        try:
            reply = reply["respond"]
        except (KeyError, TypeError):
            logger.warning("JSON response does not contain 'response' field, using raw text")
        new_row = {
            "excel_row": excel_row,
            "question": question,
            "school": args.school,
            "user_id": user_id,
            "reply": reply,
            "status_code": status,
            "elapsed_seconds": round(elapsed, 2) if elapsed else None,
            "error": error,
        }

        # Thay thế hoặc thêm mới vào results_df
        # Thay thế hoặc thêm mới vào results_df
        if output_exists and not results_df.empty:
            mask = results_df["excel_row"] == excel_row
            if mask.any():
                # Cách 1: Gán bằng list giá trị (an toàn nhất, không lỗi shape)
                results_df.loc[mask] = list(new_row.values())
                logger.info(f"Replaced row {excel_row}")
            else:
                # Thêm mới
                new_df = pd.DataFrame([new_row])
                results_df = pd.concat([results_df, new_df], ignore_index=True)
                logger.info(f"Added new row {excel_row}")
        else:
            new_df = pd.DataFrame([new_row])
            results_df = pd.concat([results_df, new_df], ignore_index=True)
            logger.info(f"Added new row {excel_row}")

        # Lưu ngay sau mỗi row
        results_df.fillna("").to_csv(args.output, index=False)
        logger.info(f"Saved progress after row {excel_row}")

    logger.info("Done. All results saved.")


if __name__ == "__main__":
    main()