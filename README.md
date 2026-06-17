# chatbot-evaluation

Bộ công cụ **thu thập câu trả lời** và **đánh giá chất lượng chatbot RAG** (hệ thống thư viện số SmartLib / VDSMART và các trường).

Repo gồm 3 thành phần, mỗi thành phần là một thư mục độc lập với `requirements.txt` riêng:

| Thư mục | Vai trò | Cách hoạt động |
|---------|---------|----------------|
| [`automation_notebooklm/`](automation_notebooklm/) | **Thu thập câu trả lời** (data collection) | Dùng Playwright lái trình duyệt hỏi hàng loạt câu hỏi vào NotebookLM / Gemini và lưu CSV. NotebookLM được dùng làm *ground truth*. |
| [`tools/`](tools/) | **Lấy câu trả lời & context từ LightRAG** | Gọi thẳng API LightRAG (không cần trình duyệt) để batch hỏi và trích các chunk được retrieve. |
| [`eval/`](eval/) | **Chấm điểm / đánh giá** | LLM-as-judge (qua OpenRouter) chấm điểm & so sánh câu trả lời; đo retrieval Precision/Recall/F1@K; đánh giá RAG bằng Ragas. |

## Luồng tổng thể

```
File Excel câu hỏi
   ├─► automation_notebooklm  →  NotebookLM/Gemini (browser)  →  output_*.csv   (ground truth)
   ├─► tools                  →  LightRAG API  →  câu trả lời + context đã retrieve (CSV)
   └─► eval                   →  chấm điểm (point/compare) + retrieval metrics + Ragas
```

## Yêu cầu chung

- Python 3.9+ (khuyến nghị 3.10+; thư mục `ragas/` cần 3.9+)
- API key của [OpenRouter](https://openrouter.ai/keys) cho phần đánh giá
- Truy cập tới các endpoint LightRAG nội bộ (ví dụ `http://10.8.0.23:9622`) cho `tools/`
- Tài khoản Google đã đăng nhập NotebookLM/Gemini cho `automation_notebooklm/`

## Cài đặt nhanh

Mỗi thư mục dùng môi trường ảo riêng. Ví dụ với `eval/`:

```bash
cd eval
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Làm tương tự cho `automation_notebooklm/` và `tools/`. Xem README trong từng thư mục để biết bước cấu hình riêng.

> 💡 Có thể dùng **một venv chung** cho cả 3 nếu muốn — chỉ cần `pip install -r` lần lượt cả 3 file `requirements.txt`. Riêng `automation_notebooklm/` cần thêm `playwright install chromium`.

## Cấu hình biến môi trường

Phần đánh giá đọc key từ biến môi trường (hỗ trợ file `.env`):

```bash
cp .env.example .env
# rồi mở .env điền OPENROUTER_API_KEY=...
```

Các biến chính:

| Biến | Bắt buộc | Mô tả |
|------|----------|-------|
| `OPENROUTER_API_KEY` | ✅ | Key OpenRouter dùng cho LLM giám khảo |
| `OPENROUTER_API_KEY_2` | ⛔ | Key dự phòng khi bị rate-limit |
| `OPENAI_BASE_URL` | ⛔ | Mặc định `https://openrouter.ai/api/v1` |
| `JUDGE_MODEL` / `EVAL_MODEL` | ⛔ | Model giám khảo / sinh câu trả lời |

> ⚠️ **Không commit file `.env` thật.** File đã nằm trong `.gitignore`; chỉ commit `.env.example`.

## Lưu ý về dữ liệu

Để repo gọn nhẹ, các file sinh ra khi chạy (output `*.csv`, log, `playwright_data/`, venv, cache) **không** được đóng gói — xem `.gitignore`. Các file Excel câu hỏi đầu vào được giữ lại làm dữ liệu mẫu.
