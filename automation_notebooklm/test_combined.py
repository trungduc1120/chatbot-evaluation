from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import csv
import pandas as pd
import logging
import os
import argparse
from pathlib import Path

# Configuration constants
DEFAULT_INPUT_PATH = "./inputs/Câu hỏi Test SmartLib site VDSMART.xlsx"
DEFAULT_OUTPUT_PATH = "output_combined.csv"
USER_DATA_DIR = "./playwright_data"
DEFAULT_GEMINI_URL = "https://gemini.google.com/u/1/app/4f09c15589b36f20"
DEFAULT_NOTEBOOK_URL = "https://notebooklm.google.com/notebook/89afd560-bec3-4717-8346-f5a733a58128?authuser=1"

INITIAL_LOAD_WAIT = 60  # seconds (NotebookLM requires around 60s)
RESPONSE_WAIT_GEMINI = 45  # seconds
RESPONSE_WAIT_NOTEBOOK = 90  # seconds
MAX_RETRIES = 3  # max retry attempts for sending messages
FAILURE_WAIT_TIME = 7200  # 2 hours in seconds
CONSECUTIVE_FAILURE_THRESHOLD = 3  # number of consecutive failures to trigger wait
FAILED_ANSWER_TEXT = "Hệ thống không thể trả lời."

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('combined_script.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def is_failed_answer(answer: str) -> bool:
    """Check if answer indicates failure (blank or specific failure message)."""
    if not answer or not isinstance(answer, str):
        return True
    answer_clean = answer.strip()
    return answer_clean == "" or answer_clean == FAILED_ANSWER_TEXT or "Hệ thống không thể trả lời" in answer_clean


def send_message_gemini(page, message, retries=MAX_RETRIES):
    """Send a message to the Gemini chat interface with retry logic."""
    for attempt in range(retries):
        try:
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

            logger.info(f"Sent message to Gemini (attempt {attempt + 1}): {full_message[:50]}...")
            return True
        except PlaywrightTimeoutError as e:
            logger.warning(f"Failed to send message to Gemini (attempt {attempt + 1}/{retries}): {e}")
            if attempt == retries - 1:
                return False
            time.sleep(2)
        except Exception as e:
            logger.error(f"Unexpected error sending message to Gemini (attempt {attempt + 1}/{retries}): {e}")
            if attempt == retries - 1:
                return False
            time.sleep(2)
    return False


def wait_for_response_gemini(page, timeout=RESPONSE_WAIT_GEMINI * 1000):
    """Wait for a new response to appear in Gemini chat."""
    try:
        page.wait_for_selector("div.conversation-container.message-actions-hover-boundary.ng-star-inserted", timeout=timeout)
        time.sleep(5)
        return True
    except PlaywrightTimeoutError:
        logger.warning("Timeout waiting for Gemini response")
        return False


def get_messages_gemini(page):
    """Extract the latest response from Gemini as a string."""
    try:
        containers = page.query_selector_all("div.conversation-container.message-actions-hover-boundary.ng-star-inserted")
        if len(containers) == 0:
            logger.warning("No Gemini messages found")
            return ""
        
        latest_container = containers[-1]
        model_response_elem = latest_container.query_selector("div.container")
        answer = model_response_elem.inner_text().strip() if model_response_elem else ""
        return answer
    except Exception as e:
        logger.error(f"Error extracting Gemini messages: {e}")
        return ""


def send_message_notebook(page, message, retries=MAX_RETRIES):
    """Send a message to the NotebookLM chat interface with retry logic."""
    for attempt in range(retries):
        try:
            input_box = page.get_by_label("Hộp truy vấn")
            input_box.wait_for(state="visible", timeout=10000)
            input_box.click()
            input_box.fill(message)
            input_box.press("Enter")
            logger.info(f"Sent message to NotebookLM (attempt {attempt + 1}): {message[:50]}...")
            return True
        except PlaywrightTimeoutError as e:
            logger.warning(f"Failed to send message to NotebookLM (attempt {attempt + 1}/{retries}): {e}")
            if attempt == retries - 1:
                return False
            time.sleep(2)
        except Exception as e:
            logger.error(f"Unexpected error sending message to NotebookLM (attempt {attempt + 1}/{retries}): {e}")
            if attempt == retries - 1:
                return False
            time.sleep(2)
    return False


def wait_for_response_notebook(page, timeout=RESPONSE_WAIT_NOTEBOOK * 1000):
    """Wait for NotebookLM to finish responding by tracking thinking-message lifecycle."""
    try:
        page.wait_for_selector(".thinking-message", timeout=timeout)
        logger.info("NotebookLM started thinking...")
        page.wait_for_selector(".thinking-message", state="detached", timeout=timeout)
        logger.info("NotebookLM finished responding.")
        time.sleep(8)
        return True
    except PlaywrightTimeoutError:
        logger.warning("Timeout waiting for thinking-message lifecycle")
        try:
            messages = page.locator(".chat-message-pair").all()
            if messages:
                logger.info("Fallback: found chat-message-pair, assuming response is ready")
                return True
        except Exception:
            pass
        return False


def get_messages_notebook(page):
    """Extract the latest response from NotebookLM as a string."""
    try:
        messages = page.locator(".chat-message-pair")
        all_message_elements = messages.all()
        
        if len(all_message_elements) == 0:
            logger.warning("No NotebookLM messages found")
            return ""
        
        latest_message = all_message_elements[-1]
        
        data_pair = latest_message.evaluate(r"""(element) => {
            const cleanAndExtract = (selector) => {
                const part = element.querySelector(selector);
                if (!part) return "";
                const clone = part.cloneNode(true);
                clone.querySelectorAll('.xap-inline-dialog.citation-marker')
                        .forEach(el => el.remove());
                clone.querySelectorAll('.mat-mdc-card-actions')
                        .forEach(el => el.remove());
                const blocks = clone.querySelectorAll('labs-tailwind-structural-element-view-v2');
                if (blocks.length > 0) {
                    return Array.from(blocks)
                        .map(block => block.innerText.trim())
                        .filter(text => text.length > 0)
                        .join('\n');
                } else {
                    return clone.innerText.trim();
                }
            };
            return {
                answer: cleanAndExtract('.to-user-container')
            };
        }""")
        
        if isinstance(data_pair, dict):
            return data_pair.get("answer", "")
        return ""
    except Exception as e:
        logger.error(f"Error extracting NotebookLM messages: {e}")
        return ""


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
        if field in row:
            value = row.get(field, "")
            if pd.isna(value):
                value = ""
            text = str(value).strip()
            if text:
                chunks.append(text)

    if not chunks:
        # Fallback if no context chunks are found in the row
        return question

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


def main():
    parser = argparse.ArgumentParser(description='Process questions with both Gemini and NotebookLM side-by-side')
    parser.add_argument('--excel', type=str, default=DEFAULT_INPUT_PATH, help='Input Excel/CSV file path')
    parser.add_argument('--output', type=str, default=DEFAULT_OUTPUT_PATH, help='Output combined CSV path')
    parser.add_argument('--gemini-url', type=str, default=DEFAULT_GEMINI_URL, help='Gemini chat URL')
    parser.add_argument('--notebook-url', type=str, default=DEFAULT_NOTEBOOK_URL, help='NotebookLM chat URL')
    parser.add_argument('--start', type=int, default=None, help='Starting STT number (1-based)')
    parser.add_argument('--end', type=int, default=None, help='Ending STT number (1-based)')
    args = parser.parse_args()
    
    if args.start is not None and args.end is not None:
        if args.start > args.end:
            logger.error(f"--start ({args.start}) must be <= --end ({args.end})")
            return
            
    try:
        # Load input DataFrame
        df_full = validate_input_file(args.excel)
        
        # Add STT column if not exists
        if 'STT' not in df_full.columns:
            df_full['STT'] = df_full.index + 1
            
        # Filter DataFrame based on STT range
        df_filtered = df_full.copy()
        if args.start is not None:
            df_filtered = df_filtered[df_filtered['STT'] >= args.start]
        if args.end is not None:
            df_filtered = df_filtered[df_filtered['STT'] <= args.end]
            
        logger.info(f"Total questions to process: {len(df_filtered)}")
        
        # Load already processed data to support resume logic
        existing_data = {}
        if os.path.exists(args.output):
            try:
                df_existing = pd.read_csv(args.output, encoding="utf-8-sig")
                for _, row in df_existing.iterrows():
                    q = str(row["Câu hỏi"]).strip()
                    existing_data[q] = {
                        "STT": row.get("STT", None),
                        "Trả lời Gemini": str(row.get("Trả lời Gemini", "")).strip(),
                        "Trả lời NotebookLM": str(row.get("Trả lời NotebookLM", "")).strip()
                    }
                logger.info(f"Loaded {len(existing_data)} questions from existing combined output")
            except Exception as e:
                logger.warning(f"Error reading existing output file: {e}")
        
        # Initialize Playwright browser context
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                USER_DATA_DIR, 
                headless=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                args=["--disable-blink-features=AutomationControlled"]
            )
            
            try:
                # Open Gemini in the first tab
                page_gemini = browser.pages[0]
                logger.info(f"Navigating Gemini page to {args.gemini_url}")
                page_gemini.goto(args.gemini_url, timeout=90000)
                
                # Open NotebookLM in the second tab
                logger.info("Opening a new tab for NotebookLM...")
                page_notebook = browser.new_page()
                logger.info(f"Navigating NotebookLM page to {args.notebook_url}")
                page_notebook.goto(args.notebook_url, timeout=90000)
                
                # Wait for initial load
                logger.info(f"Waiting {INITIAL_LOAD_WAIT} seconds for initial load on both tabs...")
                time.sleep(INITIAL_LOAD_WAIT)
                
                # Save NotebookLM page debug log
                with open("notebook_log.html", "w", encoding="utf-8") as f:
                    f.write(page_notebook.content())
                
                recent_gemini_answers = []
                recent_notebook_answers = []
                
                # Loop through each question
                for index, row in df_filtered.iterrows():
                    stt = int(row["STT"])
                    question = str(row["Câu hỏi"]).strip()
                    prompt_gemini = build_prompt(row)
                    
                    q_info = existing_data.get(question, {})
                    ans_gemini = q_info.get("Trả lời Gemini", "")
                    ans_notebook = q_info.get("Trả lời NotebookLM", "")
                    
                    # Normalize empty or nan values
                    if not ans_gemini or ans_gemini == "nan" or ans_gemini == "N/A":
                        ans_gemini = ""
                    if not ans_notebook or ans_notebook == "nan" or ans_notebook == "N/A":
                        ans_notebook = ""
                        
                    # Skip if already fully processed
                    if ans_gemini and ans_notebook:
                        logger.info(f"Skipping already processed question #{stt}: {question[:50]}...")
                        continue
                        
                    logger.info(f"\nProcessing question {index + 1}/{len(df_filtered)} (STT: {stt}): {question[:50]}...")
                    
                    # 1. Process Gemini if missing
                    if not ans_gemini:
                        logger.info(f"-> Querying Gemini...")
                        if send_message_gemini(page_gemini, prompt_gemini):
                            time.sleep(RESPONSE_WAIT_GEMINI)
                            if wait_for_response_gemini(page_gemini):
                                ans_gemini = get_messages_gemini(page_gemini)
                                if not ans_gemini:
                                    ans_gemini = FAILED_ANSWER_TEXT
                            else:
                                ans_gemini = f"{FAILED_ANSWER_TEXT} (Timeout wait response)"
                        else:
                            ans_gemini = f"{FAILED_ANSWER_TEXT} (Failed to send)"
                        logger.info(f"-> Gemini answer extracted.")
                    else:
                        logger.info(f"-> Gemini answer already exists.")
                        
                    # 2. Process NotebookLM if missing
                    if not ans_notebook:
                        logger.info(f"-> Querying NotebookLM...")
                        if send_message_notebook(page_notebook, question):
                            if wait_for_response_notebook(page_notebook):
                                ans_notebook = get_messages_notebook(page_notebook)
                                if not ans_notebook:
                                    ans_notebook = FAILED_ANSWER_TEXT
                            else:
                                ans_notebook = f"{FAILED_ANSWER_TEXT} (Timeout wait response)"
                        else:
                            ans_notebook = f"{FAILED_ANSWER_TEXT} (Failed to send)"
                        logger.info(f"-> NotebookLM answer extracted.")
                    else:
                        logger.info(f"-> NotebookLM answer already exists.")
                        
                    # Update local database
                    existing_data[question] = {
                        "STT": stt,
                        "Trả lời Gemini": ans_gemini,
                        "Trả lời NotebookLM": ans_notebook
                    }
                    
                    # Track consecutive failures for pause logic
                    recent_gemini_answers.append(ans_gemini)
                    recent_notebook_answers.append(ans_notebook)
                    if len(recent_gemini_answers) > CONSECUTIVE_FAILURE_THRESHOLD:
                        recent_gemini_answers.pop(0)
                    if len(recent_notebook_answers) > CONSECUTIVE_FAILURE_THRESHOLD:
                        recent_notebook_answers.pop(0)
                    
                    # Write immediately to output CSV preserving original Excel order
                    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
                        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                        writer.writerow(["STT", "Câu hỏi", "Trả lời Gemini", "Trả lời NotebookLM"])
                        for _, r in df_full.iterrows():
                            q_text = str(r["Câu hỏi"]).strip()
                            stt_val = r.get("STT", "")
                            if q_text in existing_data:
                                writer.writerow([
                                    existing_data[q_text]["STT"] or stt_val,
                                    q_text,
                                    existing_data[q_text]["Trả lời Gemini"],
                                    existing_data[q_text]["Trả lời NotebookLM"]
                                ])
                    logger.info(f"Successfully saved question #{stt} to output file: {args.output}")
                    
                    # Failure check & Pause
                    gemini_failed = len(recent_gemini_answers) >= CONSECUTIVE_FAILURE_THRESHOLD and all(is_failed_answer(a) for a in recent_gemini_answers)
                    notebook_failed = len(recent_notebook_answers) >= CONSECUTIVE_FAILURE_THRESHOLD and all(is_failed_answer(a) for a in recent_notebook_answers)
                    
                    if gemini_failed or notebook_failed:
                        failed_system = "Gemini" if gemini_failed else "NotebookLM"
                        logger.warning(f"Detected {CONSECUTIVE_FAILURE_THRESHOLD} consecutive failures on {failed_system}!")
                        try:
                            wait_with_progress(FAILURE_WAIT_TIME)
                        except KeyboardInterrupt:
                            logger.info("Wait interrupted by user")
                            break
                        recent_gemini_answers = []
                        recent_notebook_answers = []
                        
                    time.sleep(2)
                    
            except KeyboardInterrupt:
                logger.info("Interrupted by user")
            except Exception as e:
                logger.error(f"Unexpected runtime error: {e}", exc_info=True)
            finally:
                browser.close()
                logger.info("Browser context closed")
                
    except Exception as e:
        logger.error(f"Initialization error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
