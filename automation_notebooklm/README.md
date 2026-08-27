# automation_notebooklm

Tự động hóa bằng **Playwright**: hỏi hàng loạt câu hỏi (từ file Excel) vào NotebookLM / Gemini trên web và lưu câu trả lời ra CSV. NotebookLM thường được dùng làm **ground truth** để so với các hệ RAG khác.

## Các script chính

| File | Mục đích |
|------|----------|
| `test_notebook.py` | Lái **NotebookLM** web, hỏi batch, có retry & xử lý lỗi liên tiếp (chờ nghỉ khi fail nhiều) |
| `test_gemini.py` | Tương tự nhưng cho **Gemini** web |
| `test_claude.py`, `test_ekh.py`, `test_notebook_ma.py` | Biến thể cho các nguồn / bộ câu hỏi khác |
| `first_time_login.py` | Mở trình duyệt để đăng nhập Google lần đầu, lưu phiên vào `playwright_data/` |

## Cài đặt

```bash
cd automation_notebooklm
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium       # tải trình duyệt cho Playwright
```

## Cấu hình

1. **Đăng nhập lần đầu** (lưu cookie vào `playwright_data/`):
   ```bash
   python first_time_login.py
   ```
   Đăng nhập tài khoản Google trong cửa sổ hiện ra, rồi đóng lại. Các lần chạy sau sẽ tái sử dụng phiên này.

2. **Cấu hình script** (vd `test_notebook.py`, `test_gemini.py`): các hằng `INPUT_PATH`, `OUTPUT_PATH`, `URL`, `*_WAIT` nằm ngay đầu file — sửa trực tiếp hoặc truyền qua tham số dòng lệnh (`--help` để xem).

## Chạy

```bash
python test_notebook.py
# hoặc
python test_gemini.py
```

Kết quả lưu ra các file `output_*.csv` (đã bị `.gitignore` bỏ qua).

> ⚠️ `playwright_data/` chứa cookie đăng nhập — **không** commit. Đã có trong `.gitignore`.
