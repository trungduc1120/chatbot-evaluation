from re import S

from playwright.sync_api import sync_playwright
from time import sleep
import csv
import pandas as pd
import os

# Configuration
INPUT_FILE = "/home/vdsmart/dung/automation_notebooklm/Câu hỏi BTC.xlsx"  # CSV or XLSX with columns: STT, Câu hỏi
OUTPUT_CSV = "answers_BTC.csv"
URL = "https://claude.ai/chat/6b32af92-30a1-46d8-9c03-6035cceb5244"
USER_DATA_PATH = "./playwright_data"
WAIT_TIME = 60  # seconds to wait for response

def load_questions(input_path):
    """Load questions from CSV or XLSX file."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    # Detect file type by extension
    if input_path.lower().endswith('.xlsx') or input_path.lower().endswith('.xls'):
        df = pd.read_excel(input_path, sheet_name="Tiếng Việt")
    else:
        df = pd.read_csv(input_path, encoding="utf-8-sig")
    
    if "Câu hỏi" not in df.columns:
        raise ValueError("Required column 'Câu hỏi' not found in input file")
    return df

def run_automation():
    print("Starting Claude automation...")
    
    # Load questions
    df = load_questions(INPUT_FILE)
    print(f"Loaded {len(df)} questions from {INPUT_FILE}")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_PATH,
            headless=False, 
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )
        
        page = context.pages[0]
        
        print("Navigating to Claude page...")
        page.goto(URL)
        sleep(5)  # Wait for page load
        
        # Prepare output CSV
        csv_exists = os.path.exists(OUTPUT_CSV)
        with open(OUTPUT_CSV, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            if not csv_exists:
                writer.writerow(["STT", "Câu hỏi", "Trả lời"])
        
        for index, row in df.iterrows():
            stt = row.get("STT", index + 1)
            question = str(row["Câu hỏi"]).strip()
            
            print(f"Processing question {stt}: {question[:50]}...")
            
            # Find input box using data-testid
            input_div = page.query_selector('[data-testid="chat-input"]')
            if not input_div:
                print("Input box not found!")
                continue
            
            # Click and fill the contenteditable div
            input_div.click()
            input_div.fill(question)
            input_div.press("Enter")
            
            print("Sent question, waiting for response...")
            sleep(WAIT_TIME)
            
            # Extract all QA pairs
            elements = page.query_selector_all('div[data-test-render-count]')
            qa_pairs = []
            for elem in elements:
                has_marker = elem.query_selector('.text-text-500.text-xs.flex.items-center.mr-2') is not None
                if has_marker:
                    # Question
                    text = elem.evaluate("""(el) => {
                        const toRemove = el.querySelectorAll('.text-text-500.text-xs.flex.items-center.mr-2');
                        toRemove.forEach(child => child.remove());
                        return el.innerText;
                    }""").strip()
                    qa_pairs.append(('question', text))
                else:
                    # Answer
                    text = elem.inner_text().strip()
                    qa_pairs.append(('answer', text))
            
            # Get the latest pair
            if len(qa_pairs) >= 2 and qa_pairs[-2][0] == 'question' and qa_pairs[-1][0] == 'answer':
                extracted_question = qa_pairs[-2][1]
                extracted_answer = qa_pairs[-1][1]
                
                # Validate question
                if extracted_question == question:
                    print("Question validated, saving answer...")
                    with open(OUTPUT_CSV, 'a', newline='', encoding='utf-8-sig') as f:
                        writer = csv.writer(f)
                        writer.writerow([stt, question, extracted_answer])
                else:
                    print(f"Question mismatch! Expected: {question}, Got: {extracted_question}")
            else:
                print("Latest pair not found or invalid!")
        
        print("Automation completed.")
        input("Press Enter to close...")
        context.close()

if __name__ == "__main__":
    run_automation()