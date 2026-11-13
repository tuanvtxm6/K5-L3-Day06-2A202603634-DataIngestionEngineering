# Benchmark — Bộ luật Hình sự (VBHN 135/VBHN-VPQH, 2025)

Bộ câu hỏi: [questions.json](questions.json), gồm 20 câu: **15 dev / 5 test**. Bộ câu hỏi được chốt ngày 2026-11-13, **trước mọi lần chạy retrieval**.

## Trường dữ liệu

| Trường | Ý nghĩa |
|---|---|
| `id`, `split`, `type` | `type` ∈ `truc_tiep`, `dien_dat_lai`, `dieu_kien`, `ngoai_le`, `metadata_filter` |
| `question`, `expected_answer` | Câu hỏi không nêu số Điều gold, để tránh đưa gold source vào query |
| `gold_source_id` | `blhs-vbhn-135-2025` |
| `gold_page` | **Danh sách** trang PDF vật lý hợp lệ (một Điều có thể trải trên nhiều trang) |
| `gold_dieu` | Điều chứa evidence (dùng cho phân tích lỗi, không dùng trong truy xuất) |
| `evidence_quote` | **Danh sách** trích dẫn nguyên văn sau chuẩn hoá. Chunk phải chứa **tất cả** trích dẫn thì mới tính là đủ evidence |
| `filter` | `{"chuong": "<số La Mã>"}` hoặc `null`. Kèm `filter_context`, tức phạm vi người dùng chọn trước khi hỏi, và `confusable`, tức Điều ở chương khác dễ gây nhầm |

**Định nghĩa hit** (dùng cho Hit@1 / Evidence Hit@3): một chunk được tính là hit khi `document_id` đúng, `metadata.pages` có giao với `gold_page`, và text của chunk chứa đủ mọi `evidence_quote` (so sánh sau khi gộp khoảng trắng).

## Phân bố

| Loại | Dev | Test |
|---|---|---|
| truc_tiep | q01, q03, q07, q10, q12 | q16 |
| dien_dat_lai | q04, q08, q11 | q17 |
| dieu_kien / ngoai_le | q02, q05, q06, q09, q13 | q18 |
| metadata_filter | q14 (Chương XI), q15 (Chương IX) | q19 (Chương XI), q20 (Chương XXI) |

- Có 3 câu liên quan sửa đổi năm 2025 (Luật 86/2025/QH15): q06 (dev), q16 và q18 (test).
- Các câu filter được chọn sao cho có một Điều ở chương khác dùng câu chữ gần giống. Ví dụ: xóa án tích của pháp nhân (Điều 89) với của cá nhân (Điều 70); thời hiệu thi hành bản án (Điều 60) với thời hiệu truy cứu (Điều 27); mốc 61% trong Điều 260 với Điều 134.
- Với câu không có filter, cấu hình C chạy **không filter**, giống B.

## Cách chia dev/test và nguy cơ rò rỉ

Test được chọn để đại diện cho mọi loại câu (có 2 câu filter, 2 câu sửa đổi 2025). Corpus chỉ có một văn bản nên không chia theo tài liệu được. Các cặp có chủ đề gần nhau giữa dev và test:

- q14 (dev) và q19 (test) cùng thuộc Chương XI, pháp nhân thương mại.
- q15 (dev, Điều 60) và q17 (test, Điều 27) cùng nói về thời hiệu.
- q05 (dev, Điều 28) dẫn chiếu tới Điều 353, là gold của q16 (test).

Chỉ có 5 câu test nên kết quả test chỉ mang tính minh hoạ, không đủ để kết luận chiến lược nào tốt nhất nói chung.

## Tiêu chí chọn chiến lược (chốt trước khi xem test)

Chiến lược được chọn **chỉ dựa trên dev**, theo thứ tự ưu tiên:
1. Evidence Hit@3 trên dev cao hơn;
2. nếu chênh lệch ≤ 1 câu: Hit@1 trên dev cao hơn;
3. nếu vẫn hoà: ít chunk hơn (chi phí embedding và lưu trữ thấp hơn).

Sau khi đã chọn, cấu hình được cố định rồi mới chạy test một lần. Nếu sau đó có thay đổi gì vì đã xem kết quả test, sẽ ghi rõ trong báo cáo.

## Kiểm chứng evidence

```powershell
cd starter
python scripts/verify_benchmark.py
```

Script kiểm tra: mỗi trích dẫn có trên trang gold và nằm trong Điều gold; giá trị filter khớp chương của Điều gold; câu hỏi không chứa số Điều gold; số lượng câu đạt yêu cầu. Kết quả ghi ra `starter/results/benchmark_verification.json`. Lần chạy ngày 2026-11-13: **0 lỗi**.

## Nguồn gốc câu hỏi

Bản nháp câu hỏi và đáp án do trợ lý AI (Claude) soạn, dựa trên text đã chuẩn hoá của từng Điều. Evidence được kiểm chứng tự động bằng script trên. **Học viên cần tự đọc lại từng câu hỏi và đáp án đối chiếu với PDF gốc** trước khi chạy retrieval, rồi ghi kết quả rà soát vào báo cáo.
