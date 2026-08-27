#!/usr/bin/env python3
"""
Script phân tích kết quả chạy test_notebook.py và test_gemini.py
Tạo báo cáo so sánh giữa NotebookLM và Gemini
"""

import pandas as pd
import os
import sys
from datetime import datetime

def analyze_csv(csv_path):
    """Phân tích một file CSV kết quả"""
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception as e:
        print(f"❌ Lỗi đọc file {csv_path}: {e}")
        return None
    
    stats = {
        "file": csv_path,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_questions": len(df),
        "success_count": len(df[df["Trả lời"].notna() & (df["Trả lời"].str.strip() != "")]),
        "failed_count": len(df[df["Trả lời"].isna() | (df["Trả lời"].str.strip() == "")]),
        "success_rate": 0,
        "avg_response_length": 0,
    }
    
    if stats["total_questions"] > 0:
        stats["success_rate"] = round((stats["success_count"] / stats["total_questions"]) * 100, 2)
    
    # Tính độ dài trung bình câu trả lời
    if stats["success_count"] > 0:
        valid_responses = df[df["Trả lời"].notna() & (df["Trả lời"].str.strip() != "")]["Trả lời"]
        stats["avg_response_length"] = round(valid_responses.str.len().mean(), 0)
    
    return stats


def compare_results(nlm_csv, gemini_csv):
    """So sánh kết quả giữa NotebookLM và Gemini"""
    nlm_stats = analyze_csv(nlm_csv)
    gemini_stats = analyze_csv(gemini_csv)
    
    if nlm_stats is None or gemini_stats is None:
        return None
    
    comparison = {
        "nlm": nlm_stats,
        "gemini": gemini_stats,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    return comparison


def generate_report_md(comparison, output_path):
    """Tạo báo cáo Markdown"""
    if comparison is None:
        print("❌ Không thể tạo báo cáo (dữ liệu không hợp lệ)")
        return
    
    nlm = comparison["nlm"]
    gemini = comparison["gemini"]
    
    report = f"""# 📊 BÁO CÁO SO SÁNH NOTEBOOKLM VS GEMINI

**Ngày tạo báo cáo**: {comparison['timestamp']}

---

## 📈 TÓMLẠI KẾT QUẢ

### **NotebookLM**
- 📁 File: `{os.path.basename(nlm['file'])}`
- 📝 Tổng câu hỏi: **{nlm['total_questions']}**
- ✅ Thành công: **{nlm['success_count']}** ({nlm['success_rate']}%)
- ❌ Thất bại: **{nlm['failed_count']}**
- 📏 Độ dài trung bình: **{int(nlm['avg_response_length'])}** ký tự

### **Gemini**
- 📁 File: `{os.path.basename(gemini['file'])}`
- 📝 Tổng câu hỏi: **{gemini['total_questions']}**
- ✅ Thành công: **{gemini['success_count']}** ({gemini['success_rate']}%)
- ❌ Thất bại: **{gemini['failed_count']}**
- 📏 Độ dài trung bình: **{int(gemini['avg_response_length'])}** ký tự

---

## 🔍 SO SÁNH CHI TIẾT

| Metric | NotebookLM | Gemini | Khác biệt |
|--------|-----------|--------|----------|
| **Tổng câu hỏi** | {nlm['total_questions']} | {gemini['total_questions']} | {nlm['total_questions'] - gemini['total_questions']:+d} |
| **Success Rate** | {nlm['success_rate']}% | {gemini['success_rate']}% | {nlm['success_rate'] - gemini['success_rate']:+.2f}% |
| **Câu trả lời thành công** | {nlm['success_count']} | {gemini['success_count']} | {nlm['success_count'] - gemini['success_count']:+d} |
| **Câu trả lời thất bại** | {nlm['failed_count']} | {gemini['failed_count']} | {nlm['failed_count'] - gemini['failed_count']:+d} |
| **Độ dài trung bình** | {int(nlm['avg_response_length'])} | {int(gemini['avg_response_length'])} | {int(nlm['avg_response_length'] - gemini['avg_response_length']):+d} |

---

## 💡 NHẬN XÉT & PHÂN TÍCH

### **Tính ổn định (Reliability)**
"""
    
    # Thêm nhận xét dựa trên success rate
    if nlm["success_rate"] > gemini["success_rate"]:
        report += f"✅ **NotebookLM ổn định hơn** ({nlm['success_rate']}% vs {gemini['success_rate']}%)\n"
    elif gemini["success_rate"] > nlm["success_rate"]:
        report += f"✅ **Gemini ổn định hơn** ({gemini['success_rate']}% vs {nlm['success_rate']}%)\n"
    else:
        report += f"⚖️ **Cả hai có tỷ lệ thành công như nhau** ({nlm['success_rate']}%)\n"
    
    report += f"""
- NotebookLM: {nlm['success_count']}/{nlm['total_questions']} câu trả lời thành công
- Gemini: {gemini['success_count']}/{gemini['total_questions']} câu trả lời thành công

### **Độ dài câu trả lời (Response Length)**
"""
    
    if nlm["avg_response_length"] > gemini["avg_response_length"]:
        diff = nlm["avg_response_length"] - gemini["avg_response_length"]
        report += f"📝 **NotebookLM trả lời dài hơn** ({int(nlm['avg_response_length'])} vs {int(gemini['avg_response_length'])} ký tự, +{int(diff)})\n"
    elif gemini["avg_response_length"] > nlm["avg_response_length"]:
        diff = gemini["avg_response_length"] - nlm["avg_response_length"]
        report += f"📝 **Gemini trả lời dài hơn** ({int(gemini['avg_response_length'])} vs {int(nlm['avg_response_length'])} ký tự, +{int(diff)})\n"
    else:
        report += f"⚖️ **Độ dài câu trả lời tương đương** ({int(nlm['avg_response_length'])} ký tự)\n"
    
    report += f"""
- Câu trả lời dài hơn có thể chứa chi tiết hơn (hoặc dài dòng hơn)
- Cần xem xét chất lượng nội dung, không chỉ độ dài

### **Tỷ lệ lỗi (Failure Rate)**
- NotebookLM: {nlm['failed_count']} lỗi ({100 - nlm['success_rate']}%)
- Gemini: {gemini['failed_count']} lỗi ({100 - gemini['success_rate']}%)

"""
    
    if nlm["failed_count"] < gemini["failed_count"]:
        report += f"✅ NotebookLM có ít lỗi hơn\n"
    elif gemini["failed_count"] < nlm["failed_count"]:
        report += f"✅ Gemini có ít lỗi hơn\n"
    
    report += f"""
---

## 🎯 KHUYẾN NGHỊ CẢI THIỆN

### **Nếu Success Rate thấp (<80%)**
1. 📌 Kiểm tra kết nối mạng (timeout/retry settings)
2. 📌 Xem log để xác định lỗi cụ thể
3. 📌 Thêm INITIAL_LOAD_WAIT hoặc RESPONSE_WAIT nếu cần
4. 📌 Retry với `--max-retries` cao hơn

### **Nếu muốn so sánh chất lượng**
1. 🔍 So sánh sample 10-20 câu trả lời từ cả hai
2. 🔍 Dùng LLM-as-judge (eval/) để chấm điểm
3. 🔍 Kiểm tra Relevance, Completeness, Accuracy
4. 🔍 Tính retrieval metrics (Precision/Recall) nếu có context

### **Tiếp theo**
- 📊 Dùng `batch_chat_from_excel_lightrag.py` để lấy kết quả từ LightRAG
- 📊 Chạy eval/ để scoring tự động
- 📊 Tạo báo cáo so sánh 3 chiều: NotebookLM vs Gemini vs LightRAG

---

## 📝 GHI CHÚ KỸ THUẬT

- **NotebookLM**: Ground truth, đáng tin cậy
- **Gemini**: So sánh, thường nhanh hơn
- **Cấu hình đã dùng**:
  - INITIAL_LOAD_WAIT: 60s
  - RESPONSE_WAIT: 90s (Gemini 45s)
  - MAX_RETRIES: 3
  - FAILURE_WAIT_TIME: 2 giờ (nếu 3 lỗi liên tiếp)

---

**Báo cáo được tạo tự động bởi `analyze_results.py`**
**Thời gian**: {comparison['timestamp']}
"""
    
    # Lưu báo cáo
    try:
        with open(output_path, 'w', encoding='utf-8-sig') as f:
            f.write(report)
        print(f"✅ Báo cáo đã lưu: {output_path}")
        return output_path
    except Exception as e:
        print(f"❌ Lỗi lưu báo cáo: {e}")
        return None


def main():
    print("=" * 60)
    print("📊 PHÂN TÍCH KẾT QUẢ NOTEBOOKLM VS GEMINI")
    print("=" * 60)
    
    # Tìm file CSV
    nlm_csv = "output_DHKG.csv"
    gemini_csv = "output_slib_vdsmart_new.csv"
    
    # Hỏi người dùng nếu cần
    if len(sys.argv) > 1:
        nlm_csv = sys.argv[1]
    if len(sys.argv) > 2:
        gemini_csv = sys.argv[2]
    
    print(f"\n🔍 Tìm file:")
    print(f"  - NotebookLM: {nlm_csv}")
    print(f"  - Gemini: {gemini_csv}")
    
    if not os.path.exists(nlm_csv):
        print(f"\n❌ Không tìm thấy {nlm_csv}")
        print("   Chạy test_notebook.py trước!")
        return
    
    if not os.path.exists(gemini_csv):
        print(f"\n❌ Không tìm thấy {gemini_csv}")
        print("   Chạy test_gemini.py trước!")
        return
    
    print(f"\n✅ Cả 2 file đều tìm thấy")
    
    # Phân tích
    print(f"\n⏳ Đang phân tích...")
    comparison = compare_results(nlm_csv, gemini_csv)
    
    if comparison is None:
        print("❌ Lỗi trong quá trình phân tích")
        return
    
    # In kết quả nhanh
    print("\n" + "=" * 60)
    print("📈 KẾT QUẢ SƠ BỘ")
    print("=" * 60)
    print(f"\nNotebookLM: {comparison['nlm']['success_count']}/{comparison['nlm']['total_questions']} thành công ({comparison['nlm']['success_rate']}%)")
    print(f"Gemini:     {comparison['gemini']['success_count']}/{comparison['gemini']['total_questions']} thành công ({comparison['gemini']['success_rate']}%)")
    
    # Tạo báo cáo Markdown
    print(f"\n⏳ Đang tạo báo cáo Markdown...")
    report_path = generate_report_md(comparison, "BÁOCÁO_NOTEBOOKLM_VS_GEMINI.md")
    
    if report_path:
        print(f"\n✅ Báo cáo hoàn thành!")
        print(f"   📄 Mở file: {report_path}")
    else:
        print(f"\n❌ Không thể tạo báo cáo")


if __name__ == "__main__":
    main()
