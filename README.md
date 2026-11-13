# Day 06 · Data Ingestion Engineering — Bộ luật Hình sự (VBHN 2025)

Bài lab cá nhân: Lục Anh Tuấn · 2A202603634 · L3A (xem [STUDENT.md](STUDENT.md)).

Pipeline biến **Văn bản hợp nhất 135/VBHN-VPQH – Bộ luật Hình sự** (hợp nhất đến Luật 86/2025/QH15) thành kho tri thức truy xuất được. Ba chiến lược A/B/C được so sánh trên cùng corpus, cùng embedding model và cùng 20 câu hỏi có gold evidence.

| | |
|---|---|
| Corpus | 1 PDF, 277 trang vật lý → **275 trang nội dung** (bỏ trang bìa 1 và trang chữ ký lỗi font 277) |
| Embedding | OpenAI `text-embedding-3-small`, 1536 chiều, query và document xử lý như nhau |
| Vector store | PostgreSQL 16 + pgvector 0.8.7 (Docker), cosine `<=>`, tìm kiếm chính xác |
| Chiến lược | **A** fixed 500/50 · **B** theo Điều (≤ 1500 ký tự) · **C** = B + filter `chuong` |
| Benchmark | 20 câu (15 dev / 5 test), 4 câu có filter → [benchmark/](benchmark/README.md) |
| Báo cáo | [report/individual/2A202603634_LucAnhTuan.md](report/individual/2A202603634_LucAnhTuan.md) |

## Cấu trúc

```text
README.md                    # file này: setup, chạy, đường dẫn dữ liệu
STUDENT.md
data/manifest.json           # nguồn, giấy phép, sha256, trang được tính, số ký tự/trang (run.py sinh ra)
benchmark/questions.json     # 20 câu, split, gold page/Điều, evidence, filter
benchmark/README.md          # định nghĩa hit, phân chia dev/test, tiêu chí chọn chốt trước
artifacts/experiment_log.csv # cấu hình và giả thuyết A/B/C + kết quả
starter/
  docker-compose.yml, init.sql, .env.example, requirements.txt
  data/raw/135-vbhn-vpqh.pdf # corpus (văn bản QPPL, không thuộc phạm vi bảo hộ quyền tác giả)
  scripts/check_setup.py     # kiểm tra kết nối DB + pgvector
  scripts/verify_benchmark.py# kiểm chứng evidence trước khi chạy retrieval
  src/ingestion.py           # PyMuPDF, tách chú thích theo cỡ chữ, chuẩn hoá Unicode/dòng
  src/chunking.py            # fixed_size (A), by_article (B/C), metadata cấu trúc
  src/embeddings.py          # OpenAI adapter, đếm token/chi phí, không fallback mock
  src/store.py               # pgvector: schema, upsert không trùng, prune, search + filter SQL
  src/evaluation.py          # Hit@1 / Evidence Hit@3, trace, tuân thủ filter
  src/run.py                 # pipeline đầy đủ
  results/                   # log, thống kê, trace, bảng chấm tay
report/individual/2A202603634_LucAnhTuan.md
```

## Setup

Cần: Docker Desktop (hoặc Docker Engine + Compose), Python 3.11–3.14, một OpenAI API key. Các lệnh dưới đây chạy trong thư mục `starter/`, dùng Windows PowerShell; trên macOS/Linux thay lệnh tương ứng.

```powershell
cd starter
python -m venv .venv
.venv\Scripts\Activate.ps1                 # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
Copy-Item .env.example .env                # macOS/Linux: cp .env.example .env
# Sửa .env: OPENAI_API_KEY=<key của bạn>, EMBEDDING_MODEL=text-embedding-3-small
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py              # kỳ vọng: "... pgvector: 0.8.7" và "Setup OK"
```

Không commit `.env` (đã có trong `.gitignore`).

Nếu thiếu file PDF, tải lại từ nguồn chính thức rồi kiểm tra sha256 so với `data/manifest.json`:

```powershell
curl -L -o data/raw/135-vbhn-vpqh.pdf https://datafiles.chinhphu.vn/cpp/files/vbpq/2025/9/135-vbhn-vpqh.pdf
# sha256: ce7f1dc86e2f40c102f26e5d6980519d51842f864070a979939e182125400155
```

## Chạy

```powershell
python scripts/verify_benchmark.py   # 1. kiểm chứng 20 câu với corpus đã chuẩn hoá (kỳ vọng: 0 error)
python -m src.run --dry-run          # 2. ingest + chunk + thống kê, không gọi API, không ghi DB
python -m src.run                    # 3. embed → pgvector → truy xuất A/B/C → đánh giá
python -m src.run                    # 4. chạy lại: kỳ vọng "embedded 0, reused …", số dòng không đổi
```

Bước 3 chỉ embed những chunk mới hoặc có `content_hash` thay đổi. Chunk không còn trong nguồn sẽ bị xoá (`prune`). Bảng `rag_chunks` có khoá chính `(strategy, chunk_id)` nên nạp lại không tạo bản trùng. Nếu API hoặc DB lỗi, chương trình dừng và báo lỗi, không bao giờ thay bằng vector giả.

## Kết quả (lần chạy 2026-11-13)

| Strategy | Split | Hit@1 | Evidence Hit@3 | Chunk | Top-3 đúng chương (câu filter) |
|---|---|---|---|---|---|
| A | dev | 5/15 | 7/15 | 1.247 | 0/2 |
| A | test | 0/5 | 1/5 | | 2/2 |
| B | dev | 5/15 | 6/15 | 589 | 0/2 |
| B | test | 1/5 | 3/5 | | 2/2 |
| C | dev | 5/15 | 6/15 | 589 (dùng chung B) | 2/2 |
| C | test | 1/5 | 3/5 | | 2/2 |

Embedding lần đầu dùng 564.356 token, chi phí khoảng **$0.0113** (giá $0.02/1M token tại thời điểm chạy). Các lần chạy lại chỉ embed 20 câu hỏi (975 token). Phân tích đầy đủ, ví dụ lỗi và nhãn chấm tay: xem báo cáo.

## File kết quả (`starter/results/`)

| File | Nội dung |
|---|---|
| `ingest_log.json` | Trang bị loại và lý do, số chú thích, các bước chuẩn hoá, thời gian |
| `chunk_stats.json` | Số chunk, phân bố độ dài, số chunk nhiều trang theo từng index |
| `benchmark_verification.json` | Kết quả kiểm chứng evidence của từng câu |
| `traces.jsonl` | 60 trace (20 câu × 3 chiến lược): top-3 chunk id, text, score, trang, metadata, cờ hit |
| `summary.json`, `summary.md`, `runs/*.json` | Chỉ số dev/test, token, chi phí, thời gian, phiên bản thư viện; `runs/` lưu lại mọi lần chạy |
| `manual_coherence.csv` | 10 vị trí nguồn × 3 chiến lược, chấm tay coherence 0–2 |
| `manual_grounding.csv` | 5 câu test × 3 chiến lược, chấm tay grounding 0–2 |
| `manual_metadata.csv` | 5 câu test × top-3 × 3 chiến lược, kiểm tra tay metadata |

## Công cụ AI

Code, benchmark nháp, nhãn thủ công nháp và bản nháp báo cáo được làm với sự hỗ trợ của Claude (Anthropic). Evidence được kiểm chứng tự động bằng `verify_benchmark.py`, kết quả lấy từ lần chạy thật. Nhãn thủ công có quy tắc chấm và lý do cho từng dòng, được tác giả rà soát. Chi tiết xem mục "Cách chấm và người chấm" và mục cuối của báo cáo.
