# tools

Gọi thẳng **API LightRAG** (không cần trình duyệt) để batch hỏi câu hỏi từ Excel và trích context đã retrieve. Đầu ra dùng cho phần `eval/`.

## Các script chính

| File | Mục đích |
|------|----------|
| `batch_chat_from_excel_lightrag.py` | Batch hỏi → lưu `(stt, câu hỏi, response)`, tự retry các dòng trống |
| `batch_chat_from_excel_lighrag_2.py` | Biến thể của script trên |
| `batch_chat_from_excel_lightrag_with_profile.py` | Batch hỏi kèm `profile` người dùng |
| `batch_chat_from_excel.py` | Batch hỏi qua API chat thường (không LightRAG) |
| `batch_context_from_excel_lightrag.py` | `only_need_context=True` — trích các chunk được retrieve (`chunk_id, title, content`), phục vụ đo retrieval |
| `convert_openrouter_logs_to_csv.py` | Chuyển log OpenRouter → CSV |
| `merge_logs_to_excel.py` | Gộp nhiều log → một Excel |

## Cài đặt

```bash
cd tools
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Cấu hình

Các script nhận tham số dòng lệnh (xem `--help`). Mặc định nằm trong `parse_arguments()` ở đầu mỗi file:

| Tham số | Ý nghĩa | Mặc định ví dụ |
|---------|---------|----------------|
| `--excel` | File câu hỏi đầu vào (sheet `Câu hỏi Tiếng Việt`) | trong `inputs/` |
| `--url` | Endpoint LightRAG | `http://10.8.0.23:9622/query/stream` |
| `--school` | Mã trường / không gian dữ liệu | `VDSMART`, `VNKGU`… |
| `--user_id` | ID người dùng gọi API | `TDHH6` |
| `--output` | File CSV kết quả | `batch_*_results_*.csv` |
| `--max-retries`, `--retry-delay` | Số lần & độ trễ retry | `3`, `5` |

`DEFAULT_PAYLOAD` (mode `mix`, `top_k`, `chunk_top_k`, `llm_model`…) cũng ở đầu file — sửa nếu cần đổi tham số truy vấn LightRAG.

File câu hỏi mẫu nằm trong [`inputs/`](inputs/).

## Chạy

```bash
# Lấy câu trả lời
python batch_chat_from_excel_lightrag.py \
  --excel "inputs/Câu hỏi Test SmartLib site VDSMART.xlsx" \
  --school VDSMART \
  --output batch_chat_results_vdsmart.csv

# Lấy context (chunk đã retrieve) để đo retrieval
python batch_context_from_excel_lightrag.py \
  --excel "inputs/Câu hỏi Test SmartLib site VDSMART.xlsx" \
  --school VDSMART \
  --output batch_context_results_VDSMART.csv
```

Các file `batch_*_results_*.csv` sinh ra đã bị `.gitignore` bỏ qua.
