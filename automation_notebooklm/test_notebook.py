from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import csv
import pandas as pd
import logging
import os
import argparse
from pathlib import Path

# Configuration constants
# INPUT_PATH = "/home/vdsmart/dung/automation_notebooklm/dhkg.xlsx"
INPUT_PATH = r"D:\clone\chatbot-evaluation-dev\automation_notebooklm\BCA.xlsx"
OUTPUT_PATH = "output_BCA.csv"
USER_DATA_DIR = "./playwright_data"
URL = "https://notebooklm.google.com/notebook/89afd560-bec3-4717-8346-f5a733a58128?authuser=1"
INITIAL_LOAD_WAIT = 60  # seconds
RESPONSE_WAIT = 90  # seconds
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
        logging.FileHandler('script.log', encoding='utf-8'),
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
    """Send a message to the chat interface with retry logic."""
    for attempt in range(retries):
        try:
            input_box = page.get_by_label("Hộp truy vấn")
            input_box.wait_for(state="visible", timeout=10000)
            input_box.click()
            input_box.fill(message)
            input_box.press("Enter")
            logger.info(f"Sent message (attempt {attempt + 1}): {message[:50]}...")
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
    """Wait for NotebookLM to finish responding by tracking thinking-message lifecycle."""
    try:
        # Step 1: Wait for thinking-message to appear (NotebookLM started processing)
        page.wait_for_selector(".thinking-message", timeout=timeout)
        logger.info("NotebookLM started thinking...")

        # Step 2: Wait for thinking-message to disappear (NotebookLM finished)
        page.wait_for_selector(".thinking-message", state="detached", timeout=timeout)
        logger.info("NotebookLM finished responding.")

        # Buffer for DOM to fully render after thinking ends
        time.sleep(8)
        return True
    except PlaywrightTimeoutError:
        logger.warning("Timeout waiting for thinking-message lifecycle")
        # Fallback: check if there's already a response (thinking-message never appeared or already gone)
        try:
            messages = page.locator(".chat-message-pair").all()
            if messages:
                logger.info("Fallback: found chat-message-pair, assuming response is ready")
                return True
        except Exception:
            pass
        return False


def get_next_stt_number(output_path):
    """Get the next STT number based on existing CSV file."""
    if not os.path.exists(output_path):
        return 1
    
    # Try reading CSV with pandas first (preferred method)
    try:
        # Use on_bad_lines='skip' to handle malformed rows gracefully
        df = pd.read_csv(output_path, encoding="utf-8-sig", on_bad_lines='skip', engine='python')
        if len(df) == 0:
            return 1
        # Get the max STT and add 1
        if "STT" in df.columns:
            # Filter out non-numeric STT values and get max
            df_stt = pd.to_numeric(df["STT"], errors='coerce').dropna()
            if len(df_stt) > 0:
                max_stt = int(df_stt.max())
                next_stt = max_stt + 1
            else:
                # No valid STT values, use row count
                next_stt = len(df) + 1
        else:
            # No STT column, use row count
            next_stt = len(df) + 1
        return next_stt
    except Exception as e:
        logger.warning(f"Error reading CSV with pandas: {e}, trying fallback method")
        
        # Fallback: Count lines manually (skip header and count data rows)
        try:
            with open(output_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
                # Skip header if exists
                if lines and lines[0].strip().startswith('STT'):
                    data_lines = [l for l in lines[1:] if l.strip()]  # Skip empty lines
                    # Try to extract STT from each line
                    max_stt = 0
                    for line in data_lines:
                        try:
                            # Split by comma and get first field (STT)
                            parts = line.split(',', 1)  # Split only on first comma
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
            return 1  # Last resort: return 1


def get_messages(page, writer, next_stt=None):
    """Extract the latest message pair and write to CSV."""
    try:
        messages = page.locator(".chat-message-pair")
        all_message_elements = messages.all()
        
        if len(all_message_elements) == 0:
            logger.warning("No messages found")
            return None
        
        latest_message = all_message_elements[-1]
        
        data_pair = latest_message.evaluate(r"""(element) => {
            const cleanAndExtract = (selector) => {
                const part = element.querySelector(selector);
                if (!part) return "N/A";

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
                question: cleanAndExtract('.from-user-container'),
                answer:   cleanAndExtract('.to-user-container')
            };
        }""")

        if isinstance(data_pair, dict):
            question = data_pair.get("question", "")
            answer = data_pair.get("answer", "")
            
            # Use provided STT or calculate from CSV
            if next_stt is None:
                stt = get_next_stt_number(OUTPUT_PATH)
            else:
                stt = next_stt
            
            # Validate STT is not None before writing
            if stt is None:
                stt = get_next_stt_number(OUTPUT_PATH)
                # If still None, use fallback: count existing rows + 1
                if stt is None:
                    try:
                        with open(OUTPUT_PATH, 'r', encoding='utf-8-sig') as f:
                            line_count = sum(1 for line in f if line.strip())
                        stt = max(1, line_count)  # At least 1, or line count if file has data
                    except:
                        stt = 1
            
            writer.writerow([stt, question, answer])
            logger.info(f"Extracted message pair #{stt}")
            data_pair["STT"] = stt
            return data_pair
        else:
            logger.error("Failed to extract message data")
            return None
            
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
                processed = set(df_o["Câu hỏi"].dropna().astype(str))
                logger.info(f"Loaded {len(processed)} already processed questions")
        except Exception as e:
            logger.warning(f"Error reading existing CSV: {e}")
    return processed


def validate_input_file(input_path):
    """Validate that input file exists and has required columns."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    df = pd.read_excel(input_path)
    if "Câu hỏi" not in df.columns:
        raise ValueError(f"Required column 'Câu hỏi' not found in {input_path}")
    
    return df


def check_consecutive_failures(recent_answers: list) -> bool:
    """Check if the last 3 answers are all failures."""
    if len(recent_answers) < CONSECUTIVE_FAILURE_THRESHOLD:
        return False
    last_three = recent_answers[-CONSECUTIVE_FAILURE_THRESHOLD:]
    return all(is_failed_answer(answer) for answer in last_three)


def wait_with_progress(seconds):
    """Wait for specified seconds with progress updates."""
    logger.info(f"Waiting {seconds} seconds ({seconds/60:.1f} minutes)...")
    interval = 300  # Update every 5 minutes
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
        # Find the row with matching question
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
                    # Extract the new answer
                    messages = page.locator(".chat-message-pair")
                    all_message_elements = messages.all()
                    
                    if len(all_message_elements) > 0:
                        latest_message = all_message_elements[-1]
                        data_pair = latest_message.evaluate(r"""(element) => {
                            const cleanAndExtract = (selector) => {
                                const part = element.querySelector(selector);
                                if (!part) return "N/A";
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
                                question: cleanAndExtract('.from-user-container'),
                                answer:   cleanAndExtract('.to-user-container')
                            };
                        }""")
                        
                        if isinstance(data_pair, dict):
                            new_answer = data_pair.get("answer", "")
                            # Use the original STT that was stored when question failed
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
            
            time.sleep(1)  # Small delay between retries
        
        logger.info(f"Retry cycle {retry_cycle} completed. Retried {retried_count}/{len(failed_questions_dict)} questions")
        
    except Exception as e:
        logger.error(f"Error during retry cycle: {e}")


def main():
    parser = argparse.ArgumentParser(description='Process questions from Excel file with optional STT range')
    parser.add_argument('--start', type=int, default=None, 
                        help='Starting STT number (default: process from beginning)')
    parser.add_argument('--end', type=int, default=None,
                        help='Ending STT number (default: process to the end)')
    args = parser.parse_args()
    
    # Validate range
    if args.start is not None and args.end is not None:
        if args.start > args.end:
            logger.error(f"--start ({args.start}) must be <= --end ({args.end})")
            return
    
    try:
        # Validate input file
        df = validate_input_file(INPUT_PATH)
        
        # Filter dataframe based on STT range
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
        
        # Load already processed questions
        processed_questions = load_processed_questions(OUTPUT_PATH)
        
        # Initialize CSV file if needed
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

                # Save page content for debugging
                log_content = page.content()
                with open("log.html", "w", encoding="utf-8") as f:
                    f.write(log_content)
                
                # Track recent answers for failure detection
                recent_answers = []
                failed_questions_dict = {}  # question -> STT mapping
                retry_cycle_count = 0
                
                with open(OUTPUT_PATH, csv_mode, newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                    
                    # Write header if new file
                    if not csv_exists:
                        writer.writerow(["STT", "Câu hỏi", "Trả lời"])
                    
                    for index, row in df.iterrows():
                        question = str(row["Câu hỏi"]).strip()
                        
                        if question in processed_questions:
                            logger.info(f"Skipping already processed question: {question[:50]}...")
                            continue
                        
                        logger.info(f"Processing question {index + 1}/{len(df)}")
                        
                        if send_message(page, question):
                            if wait_for_response(page):
                                next_stt = get_next_stt_number(OUTPUT_PATH)
                                data_pair = get_messages(page, writer, next_stt=next_stt)
                                
                                if data_pair and isinstance(data_pair, dict):
                                    answer = data_pair.get("answer", "")
                                    recent_answers.append(answer)
                                    # Keep only last 3 answers
                                    if len(recent_answers) > CONSECUTIVE_FAILURE_THRESHOLD:
                                        recent_answers.pop(0)
                                    
                                    processed_questions.add(question)
                                    f.flush()  # Ensure data is written
                                    
                                    # Check for consecutive failures
                                    if is_failed_answer(answer):
                                        stt = data_pair.get("STT", len(recent_answers))
                                        failed_questions_dict[question] = stt
                                        logger.warning(f"Question failed (STT={stt}): {question[:50]}...")
                                    
                                    # Check if 3 consecutive failures detected
                                    if check_consecutive_failures(recent_answers) and retry_cycle_count < MAX_RETRY_CYCLES:
                                        logger.warning(f"Detected {CONSECUTIVE_FAILURE_THRESHOLD} consecutive failures!")
                                        logger.info("Waiting 2 hours before retrying failed questions...")
                                        
                                        # Ensure CSV is flushed before retry
                                        f.flush()
                                        
                                        try:
                                            wait_with_progress(FAILURE_WAIT_TIME)
                                        except KeyboardInterrupt:
                                            logger.info("Wait interrupted by user")
                                            break
                                        
                                        retry_cycle_count += 1
                                        logger.info(f"Starting retry cycle {retry_cycle_count}/{MAX_RETRY_CYCLES}")
                                        
                                        # Retry failed questions (this will update CSV directly)
                                        retry_failed_questions(page, failed_questions_dict.copy(), OUTPUT_PATH, retry_cycle_count)
                                        
                                        # Reload processed questions after retry
                                        processed_questions = load_processed_questions(OUTPUT_PATH)
                                        
                                        # Clear recent answers and failed questions after retry
                                        recent_answers = []
                                        failed_questions_dict = {}
                                        
                                else:
                                    logger.error(f"Failed to extract message data for: {question[:50]}...")
                            else:
                                logger.error(f"No response received for: {question[:50]}...")
                        else:
                            logger.error(f"Failed to send: {question[:50]}...")
                        
                        time.sleep(1)  # Small delay between questions
                        
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
