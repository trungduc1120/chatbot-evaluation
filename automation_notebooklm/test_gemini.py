from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import csv
import pandas as pd
import logging
import os
import argparse
from pathlib import Path

# Configuration constants
# INPUT_PATH = "/home/vdsmart/dung/automation_notebooklm/Câu hỏi Test SmartLib site VDSMART.xlsx"
INPUT_PATH = "./inputs/Câu hỏi Test SmartLib site VDSMART.xlsx"
OUTPUT_PATH = "output_slib_vdsmart_new.csv"
USER_DATA_DIR = "./playwright_data"
URL = "https://gemini.google.com/u/1/app/4f09c15589b36f20"
INITIAL_LOAD_WAIT = 20  # seconds
RESPONSE_WAIT = 45  # seconds
MAX_RETRIES = 3  # max retry attempts for sending messages
MAX_RETRY_CYCLES = 3  # max retry cycles for failed questions
FAILURE_WAIT_TIME = 7200  # 2 hours in seconds
CONSECUTIVE_FAILURE_THRESHOLD = 3  # number of consecutive failures to trigger wait
FAILED_ANSWER_TEXT = "Hệ thống không thể trả lời."

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('gemini_script.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def is_failed_answer(answer: str) -> bool:
    """Check if answer indicates failure (blank or specific failure message)."""
    if not answer or not isinstance(answer, str):
        return True
    answer_clean = answer.strip()
    return answer_clean == "" or answer_clean == FAILED_ANSWER_TEXT


def send_message(page, message, retries=MAX_RETRIES):
    """Send a message to the Gemini chat interface with retry logic."""
    for attempt in range(retries):
        try:
            # Find the input editor and ensure it is ready
            page.wait_for_selector(
                'div[data-test-id="textarea-wrapper"] .ql-editor, '
                'div.text-input-field_textarea-inner .ql-editor, '
                'rich-textarea .ql-editor, '
                '[contenteditable="true"]',
                timeout=8000
            )

            input_field = page.query_selector(
                'div[data-test-id="textarea-wrapper"] .ql-editor, '
                'div.text-input-field_textarea-inner .ql-editor, '
                'rich-textarea .ql-editor, '
                '[contenteditable="true"]'
            )
            if not input_field:
                input_field = page.query_selector('rich-textarea')
            if not input_field:
                input_field = page.query_selector('textarea')
            if not input_field:
                raise Exception("Input field not found")

            input_field.click()
            time.sleep(0.5)

            full_message = message + "\n" + "Không đề cập thông tin của các câu trả lời phía trên"
            # Use ElementHandle.evaluate to set the editor content (passes the element implicitly)
            input_field.evaluate(
                "(el, msg) => { el.innerText = msg; el.textContent = msg; el.dispatchEvent(new Event('input', { bubbles: true })); }",
                full_message,
            )

            send_button = page.query_selector(
                'div[data-test-id="send-button-container"] button[aria-label="Gửi tin nhắn"], '
                'button[aria-label="Gửi tin nhắn"], '
                'button[aria-label="Send message"], '
                'button[aria-label="Send"], '
                'button[aria-label="Gửi"]'
            )
            if send_button:
                send_button.click()
            else:
                input_field.press("Enter")

            logger.info(f"Sent message (attempt {attempt + 1}): {full_message[:50]}...")
            return True
        except PlaywrightTimeoutError as e:
            logger.warning(f"Failed to send message (attempt {attempt + 1}/{retries}): {e}")
            if attempt == retries - 1:
                logger.error(f"Failed to send message after {retries} attempts")
                return False
            time.sleep(2)
        except Exception as e:
            logger.error(f"Unexpected error sending message (attempt {attempt + 1}/{retries}): {e}")
            if attempt == retries - 1:
                return False
            time.sleep(2)
    return False


def wait_for_response(page, timeout=RESPONSE_WAIT * 1000):
    """Wait for a new response to appear in Gemini chat."""
    try:
        # Wait for new conversation container to appear
        page.wait_for_selector("div.conversation-container.message-actions-hover-boundary.ng-star-inserted", timeout=timeout)
        # Additional wait for content to load
        time.sleep(5)
        return True
    except PlaywrightTimeoutError:
        logger.warning("Timeout waiting for response")
        return False


def get_next_stt_number(output_path):
    """Get the next STT number based on existing CSV file."""
    if not os.path.exists(output_path):
        return 1
    
    try:
        df = pd.read_csv(output_path, encoding="utf-8-sig", on_bad_lines='skip', engine='python')
        if len(df) == 0:
            return 1
        if "STT" in df.columns:
            df_stt = pd.to_numeric(df["STT"], errors='coerce').dropna()
            if len(df_stt) > 0:
                max_stt = int(df_stt.max())
                next_stt = max_stt + 1
            else:
                next_stt = len(df) + 1
        else:
            next_stt = len(df) + 1
        return next_stt
    except Exception as e:
        logger.warning(f"Error reading CSV with pandas: {e}, trying fallback method")
        
        try:
            with open(output_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
                if lines and lines[0].strip().startswith('STT'):
                    data_lines = [l for l in lines[1:] if l.strip()]
                    max_stt = 0
                    for line in data_lines:
                        try:
                            parts = line.split(',', 1)
                            if parts[0].strip().isdigit():
                                stt_val = int(parts[0].strip())
                                max_stt = max(max_stt, stt_val)
                        except:
                            continue
                    next_stt = max_stt + 1 if max_stt > 0 else len(data_lines) + 1
                else:
                    next_stt = len([l for l in lines if l.strip()]) + 1
            return next_stt
        except Exception as e2:
            logger.error(f"Fallback method also failed: {e2}, returning 1")
            return 1


def get_messages(page, writer, question, next_stt=None):
    """Extract the latest response from Gemini and write to CSV using the provided question."""
    try:
        # Get all conversation containers
        containers = page.query_selector_all("div.conversation-container.message-actions-hover-boundary.ng-star-inserted")
        
        if len(containers) == 0:
            logger.warning("No messages found")
            return None
        
        latest_container = containers[-1]
        model_response_elem = latest_container.query_selector("div.container")
        answer = model_response_elem.inner_text().strip() if model_response_elem else "N/A"
        
        if next_stt is None:
            stt = get_next_stt_number(OUTPUT_PATH)
        else:
            stt = next_stt
        
        if stt is None:
            stt = get_next_stt_number(OUTPUT_PATH)
            if stt is None:
                try:
                    with open(OUTPUT_PATH, 'r', encoding='utf-8-sig') as f:
                        line_count = sum(1 for line in f if line.strip())
                    stt = max(1, line_count)
                except:
                    stt = 1
        
        writer.writerow([stt, question, answer])
        logger.info(f"Extracted message pair #{stt}")
        
        return {
            "question": question,
            "answer": answer,
            "STT": stt
        }
            
    except Exception as e:
        logger.error(f"Error extracting messages: {e}")
        return None


def load_processed_questions(output_path):
    """Load already processed questions from CSV file."""
    processed = set()
    if os.path.exists(output_path):
        try:
            df_o = pd.read_csv(output_path, encoding="utf-8-sig")
            if "Câu hỏi" in df_o.columns:
                questions_list = df_o["Câu hỏi"].dropna().str.strip().astype(str).tolist()
                # Remove suffix if present for backward compatibility
                suffix = "Không đề cập thông tin của các câu trả lời phía trên"
                cleaned_questions = [q.replace(suffix, "").strip() for q in questions_list]
                processed = set(cleaned_questions)
                logger.info(f"Loaded {len(processed)} already processed questions")
        except Exception as e:
            logger.warning(f"Error reading existing CSV: {e}")
    return processed


def validate_input_file(input_path):
    """Validate that input file exists and has required columns."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    if input_path.lower().endswith('.xlsx') or input_path.lower().endswith('.xls'):
        df = pd.read_excel(input_path)
    else:
        df = pd.read_csv(input_path, encoding="utf-8-sig")
    
    if "Câu hỏi" not in df.columns:
        raise ValueError(f"Required column 'Câu hỏi' not found in {input_path}")
    
    return df


def build_prompt(row):
    """Build the prompt using the question and chunk context fields."""
    question = str(row.get("Câu hỏi", "")).strip()
    chunk_fields = [
        "chunk_content_1",
        "chunk_content_2",
        "chunk_content_3",
        "chunk_content_4",
        "chunk_content_5",
    ]
    chunks = []
    for field in chunk_fields:
        value = row.get(field, "")
        if pd.isna(value):
            value = ""
        text = str(value).strip()
        if text:
            chunks.append(text)

    chunk_text = ",\n    ".join(chunks)
    prompt = (
        "Tôi có câu hỏi và context, hãy trả lời câu hỏi chỉ dựa vào nội dung context. "
        "Trả lời trực tiếp, không mở đầu bằng \"Dựa vào nội dung đoạn context được cung cấp\". "
        "Trình bày bằng văn xuôi mạch lạc, không gạch đầu dòng. Đảm bảo bao gồm đầy đủ tất cả "
        "các chi tiết, ví dụ minh họa và số liệu liên quan có trong context. Sắp xếp các ý theo "
        "trình tự logic, gộp các thông tin liên quan lại với nhau.\n"
        f"Câu hỏi: {question}\n"
        "Context:\n{\n"
        f"    {chunk_text}\n"
        "}"
    )
    return prompt


def check_consecutive_failures(recent_answers: list) -> bool:
    """Check if the last 3 answers are all failures."""
    if len(recent_answers) < CONSECUTIVE_FAILURE_THRESHOLD:
        return False
    last_three = recent_answers[-CONSECUTIVE_FAILURE_THRESHOLD:]
    return all(is_failed_answer(answer) for answer in last_three)


def wait_with_progress(seconds):
    """Wait for specified seconds with progress updates."""
    logger.info(f"Waiting {seconds} seconds ({seconds/60:.1f} minutes)...")
    interval = 300
    elapsed = 0
    
    while elapsed < seconds:
        remaining = seconds - elapsed
        if remaining > interval:
            time.sleep(interval)
            elapsed += interval
            logger.info(f"Progress: {elapsed}/{seconds} seconds ({elapsed/60:.1f}/{seconds/60:.1f} minutes)")
        else:
            time.sleep(remaining)
            elapsed += remaining
    logger.info("Wait completed")


def update_csv_entry(csv_path: str, question: str, new_answer: str, new_stt: int):
    """Update a specific CSV entry by overwriting the file."""
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        mask = df["Câu hỏi"].astype(str) == str(question)
        if mask.any():
            df.loc[mask, "Trả lời"] = new_answer
            df.loc[mask, "STT"] = new_stt
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            logger.info(f"Updated CSV entry for question: {question[:50]}...")
            return True
        else:
            logger.warning(f"Question not found in CSV for update: {question[:50]}...")
            return False
    except Exception as e:
        logger.error(f"Error updating CSV entry: {e}")
        return False


def retry_failed_questions(page, failed_questions_dict, csv_path, retry_cycle):
    """Retry all failed questions and update CSV entries."""
    logger.info(f"Starting retry cycle {retry_cycle} for {len(failed_questions_dict)} failed questions")
    
    try:
        retried_count = 0
        
        for question, original_stt in failed_questions_dict.items():
            logger.info(f"Retrying question: {question[:50]}...")
            
            if send_message(page, question):
                if wait_for_response(page):
                    containers = page.query_selector_all("div.conversation-container.message-actions-hover-boundary.ng-star-inserted")
                    
                    if len(containers) > 0:
                        latest_container = containers[-1]
                        user_query_elem = latest_container.query_selector(".user-query")
                        model_response_elem = latest_container.query_selector(".model-response")
                        
                        new_question = user_query_elem.inner_text().strip() if user_query_elem else ""
                        new_answer = model_response_elem.inner_text().strip() if model_response_elem else ""
                        
                        if new_question:
                            update_csv_entry(csv_path, question, new_answer, original_stt)
                            retried_count += 1
                            logger.info(f"Successfully retried question: {question[:50]}...")
                        else:
                            logger.warning(f"Failed to extract answer for retry: {question[:50]}...")
                    else:
                        logger.warning(f"No messages found for retry: {question[:50]}...")
                else:
                    logger.warning(f"No response received for retry: {question[:50]}...")
            else:
                logger.error(f"Failed to send message for retry: {question[:50]}...")
            
            time.sleep(1)
        
        logger.info(f"Retry cycle {retry_cycle} completed. Retried {retried_count}/{len(failed_questions_dict)} questions")
        
    except Exception as e:
        logger.error(f"Error during retry cycle: {e}")


def main():
    parser = argparse.ArgumentParser(description='Process questions from Excel file with Gemini using optional STT range')
    parser.add_argument('--start', type=int, default=None, 
                        help='Starting STT number (default: process from beginning)')
    parser.add_argument('--end', type=int, default=None,
                        help='Ending STT number (default: process to the end)')
    args = parser.parse_args()
    
    if args.start is not None and args.end is not None:
        if args.start > args.end:
            logger.error(f"--start ({args.start}) must be <= --end ({args.end})")
            return
    
    try:
        df = validate_input_file(INPUT_PATH)
        
        if 'STT' in df.columns:
            if args.start is not None:
                df = df[df['STT'] >= args.start]
            if args.end is not None:
                df = df[df['STT'] <= args.end]
        else:
            if args.start is not None or args.end is not None:
                df['STT'] = df.index + 1
                if args.start is not None:
                    df = df[df['STT'] >= args.start]
                if args.end is not None:
                    df = df[df['STT'] <= args.end]
        
        logger.info(f"Total questions to process: {len(df)}")
        
        processed_questions = load_processed_questions(OUTPUT_PATH)
        
        csv_exists = os.path.exists(OUTPUT_PATH)
        csv_mode = "a" if csv_exists else "w"
        
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                USER_DATA_DIR, 
                headless=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                args=["--disable-blink-features=AutomationControlled"]
            )

            try:
                page = browser.pages[0]
                logger.info(f"Navigating to {URL}")
                page.goto(URL)
                logger.info(f"Waiting {INITIAL_LOAD_WAIT} seconds for initial load...")
                time.sleep(INITIAL_LOAD_WAIT)
                
                recent_answers = []
                failed_questions_dict = {}
                retry_cycle_count = 0
                
                with open(OUTPUT_PATH, csv_mode, newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                    
                    if not csv_exists:
                        writer.writerow(["STT", "Câu hỏi", "Trả lời"])
                    
                    for index, row in df.iterrows():
                        question = str(row["Câu hỏi"]).strip()
                        prompt = build_prompt(row)
                        
                        if question in processed_questions:
                            logger.info(f"Skipping already processed question: {question[:50]}...")
                            continue
                        
                        logger.info(f"Processing question {index + 1}/{len(df)}")
                        
                        if send_message(page, prompt):
                            time.sleep(RESPONSE_WAIT)
                            if wait_for_response(page):
                                next_stt = get_next_stt_number(OUTPUT_PATH)
                                data_pair = get_messages(page, writer, question, next_stt=next_stt)
                                
                                if data_pair and isinstance(data_pair, dict):
                                    answer = data_pair.get("answer", "")
                                    recent_answers.append(answer)
                                    if len(recent_answers) > CONSECUTIVE_FAILURE_THRESHOLD:
                                        recent_answers.pop(0)
                                    
                                    processed_questions.add(question)
                                    f.flush()
                                    
                                    if is_failed_answer(answer):
                                        stt = data_pair.get("STT", len(recent_answers))
                                        failed_questions_dict[question] = stt
                                        logger.warning(f"Question failed (STT={stt}): {question[:50]}...")
                                    
                                    if check_consecutive_failures(recent_answers) and retry_cycle_count < MAX_RETRY_CYCLES:
                                        logger.warning(f"Detected {CONSECUTIVE_FAILURE_THRESHOLD} consecutive failures!")
                                        logger.info("Waiting 2 hours before retrying failed questions...")
                                        
                                        f.flush()
                                        
                                        try:
                                            wait_with_progress(FAILURE_WAIT_TIME)
                                        except KeyboardInterrupt:
                                            logger.info("Wait interrupted by user")
                                            break
                                        
                                        retry_cycle_count += 1
                                        logger.info(f"Starting retry cycle {retry_cycle_count}/{MAX_RETRY_CYCLES}")
                                        
                                        retry_failed_questions(page, failed_questions_dict.copy(), OUTPUT_PATH, retry_cycle_count)
                                        
                                        processed_questions = load_processed_questions(OUTPUT_PATH)
                                        
                                        recent_answers = []
                                        failed_questions_dict = {}
                                        
                                else:
                                    logger.error(f"Failed to extract message data for: {question[:50]}...")
                            else:
                                logger.error(f"No response received for: {question[:50]}...")
                        else:
                            logger.error(f"Failed to send: {question[:50]}...")
                        
                        time.sleep(1)
                        
            except KeyboardInterrupt:
                logger.info("Interrupted by user")
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
            finally:
                browser.close()
                logger.info("Browser closed")
                
    except FileNotFoundError as e:
        logger.error(f"File error: {e}")
    except ValueError as e:
        logger.error(f"Validation error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)


if __name__ == "__main__":
    main()