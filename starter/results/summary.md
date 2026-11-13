# Kết quả tự động (Hit@1 / Evidence Hit@3)

Model: `text-embedding-3-small` (1536 chiều) · tokens: 975 · chi phí ước tính: $0.000019 (giá 0.02 USD/1M tokens, cần kiểm tra)

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 5/15 | 7/15 | 1247 | embed 0.0s, query 0.77s | tokens 0 |
| A | test | 0/5 | 1/5 | 1247 | embed 0.0s, query 0.77s | tokens 0 |
| B | dev | 5/15 | 6/15 | 589 | embed 0.0s, query 0.57s | tokens 0 |
| B | test | 1/5 | 3/5 | 589 | embed 0.0s, query 0.57s | tokens 0 |
| C | dev | 5/15 | 6/15 | 589 | embed 0.0s, query 0.51s (dùng lại vector của B) | tokens 0 |
| C | test | 1/5 | 3/5 | 589 | embed 0.0s, query 0.51s (dùng lại vector của B) | tokens 0 |

| Strategy | Split | Filter tuân thủ top-3 (n/N câu có filter) | Hit@3 câu filter | Evidence bị tách nhiều chunk | Câu trượt top-3 |
|---|---|---|---|---|---|
| A | dev | 0/2 | 2/2 | 0 | q02, q03, q04, q05, q07, q09, q12, q13 |
| A | test | 2/2 | 1/2 | 0 | q16, q17, q18, q20 |
| B | dev | 0/2 | 1/2 | 0 | q03, q04, q05, q07, q09, q10, q12, q13, q15 |
| B | test | 2/2 | 1/2 | 0 | q17, q20 |
| C | dev | 2/2 | 1/2 | 0 | q03, q04, q05, q07, q09, q10, q12, q13, q15 |
| C | test | 2/2 | 1/2 | 0 | q17, q20 |

Coherence, grounding, metadata đúng/đủ: chấm tay trong các file `manual_*.csv`.
