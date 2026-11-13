# Báo cáo cá nhân — Day 6

Lục Anh Tuấn · 2A202603634 · L3A · Lần chạy chính: 2026-11-13 (UTC)

> Số liệu tự động lấy từ `starter/results/` của lần chạy thật. Nhãn thủ công (coherence, metadata, grounding) lấy từ `starter/results/manual_*.csv`. Cách chấm và người chấm: xem mục "Đường dẫn trace, nhãn thủ công và cách chọn mẫu".

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang.**
  - **Văn bản:** Văn bản hợp nhất số 135/VBHN-VPQH – Bộ luật Hình sự, do Văn phòng Quốc hội ban hành ngày 05/9/2025. Văn bản hợp nhất BLHS 100/2015/QH13 với Luật 12/2017/QH14, Luật Tư pháp người chưa thành niên 59/2024/QH15 và Luật 86/2025/QH15.
  - **Nguồn và quyền:** PDF tải từ datafiles.chinhphu.vn lúc 2026-11-13 10:04 UTC (sha256 `ce7f1dc8…0155`). Đây là văn bản quy phạm pháp luật nên không thuộc phạm vi bảo hộ quyền tác giả (khoản 2 Điều 15 Luật SHTT).
  - **Quy tắc tính trang:** tính các trang vật lý trích được text tiếng Việt, trừ trang 1 (trang bìa/danh sách văn bản sửa đổi). Trang 277 (trang xác thực chữ ký, lỗi font, tỷ lệ ký tự tiếng Việt bằng 0) bị loại. Kết quả: **275/277 trang nội dung**, khoảng 514k ký tự sau chuẩn hoá. Chi tiết trong `data/manifest.json`.

- **Chuẩn hóa, lỗi và giới hạn.**
  - **Chọn thư viện đọc PDF:** dùng PyMuPDF thay pypdf. pypdf tách sai âm tiết có dấu (`ch ủ quyền`, `c ủa`, `mi ễn`); PyMuPDF không gặp lỗi này trên cùng file.
  - **Tách chú thích theo cỡ chữ:**
    - 14pt là nội dung luật;
    - 9pt superscript là số chú thích chèn trong câu. Nếu không bỏ thì chúng làm sai số liệu, vd `61% trở lên78`, `năm 20181`;
    - 8pt + 12pt là chú thích ở cuối trang;
    - 13pt ở đầu trang là số trang.
    - Kết quả: 588 số chú thích bị loại khỏi text; nội dung 401 chú thích được giữ trong metadata (`footnote_ids`, `amended_by`).
  - **Chuẩn hoá ký tự:** đưa về NFC (273/277 trang chưa ở dạng NFC); đổi `Ð` (U+00D0, chữ Eth, khiến "Ðiều 317" không được nhận diện) thành `Đ`; bỏ các ký tự vô hình.
  - **Nối dòng:** nối các dòng bị xuống dòng do khổ giấy, nhưng giữ ngắt dòng trước Phần/Chương/Mục/Điều/khoản/điểm. Tiêu đề Điều bị xuống dòng (117 trường hợp) được nhận diện bằng chữ đậm. Dòng bắt đầu bằng "Điều N." mà không in đậm thì được coi là câu tham chiếu chứ không phải tiêu đề.
  - **Kiểm tra cấu trúc:** đọc đủ 26/26 chương, 410/410 Điều (gồm 217a, 256a; Chương XII "được bãi bỏ" nên không có Điều 90–107).
  - **Giới hạn:**
    - Không OCR trang 277.
    - Các dòng đầu trang 1 (quốc hiệu, tên văn bản) bị nối thành một đoạn.
    - Căn cứ sửa đổi/bãi bỏ chỉ có trong metadata, không có trong text chunk.
    - Văn bản hợp nhất không phải bản có giá trị pháp lý thay thế văn bản gốc.

- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí.**
  - **Embedding:** OpenAI `text-embedding-3-small` (SDK `openai` 2.54.0), 1536 chiều. Query và document được embed như nhau, không thêm tiền tố.
  - **Vector store:** PostgreSQL 16.16 + pgvector 0.8.7, chạy bằng Docker image `pgvector/pgvector:0.8.7-pg16`. Một bảng `rag_chunks`, khoá chính `(strategy, chunk_id)`. Metric cosine (`<=>`), score = 1 − distance, tìm kiếm **chính xác**, không dùng index xấp xỉ.
  - **Môi trường:** Python 3.12.10, PyMuPDF 1.28.2, psycopg 3.3.8.
  - **Lệnh chạy:** `python scripts/verify_benchmark.py`, `python -m src.run`. Xem README.
  - **Chi phí:** lần chạy đầu dùng 564.356 token, khoảng **$0.0113** (giá niêm yết $0.02/1M token, cần đối chiếu lại). Trong đó 975 token là cho 20 câu hỏi. Lần chạy lại tốn $0.00002 vì chỉ embed câu hỏi.

- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn.**
  - **Bắt buộc:** `document_id`, `source`, `page` (trang bắt đầu) và `pages` (mọi trang chunk phủ, vì một Điều có thể vắt trang).
  - **Bổ sung:** `phan`, `chuong` (số La Mã), `chuong_title`, `muc`, `dieu`, `dieu_title`, `footnote_ids`, `amended_by`, `content_hash`. Mọi giá trị đều lấy từ dòng tiêu đề và chú thích **trong chính văn bản**, không suy đoán.
  - **Trường lọc là `chuong`:** mỗi chương là một nhóm tội hoặc nhóm quy định chung. Cùng một cụm từ ("xóa án tích", "thời hiệu", "tình tiết giảm nhẹ", "61%") xuất hiện ở nhiều chương với nghĩa khác nhau, nên filter theo chương giúp thu hẹp đúng phạm vi.
  - **Hạn chế:** với A, `dieu`/`chuong` là ngữ cảnh tại **vị trí đầu chunk**. Chunk vắt qua ranh giới Điều sẽ mang nhãn Điều trước (vd q01: top-1 của A ghi Điều 11 nhưng chứa nội dung Điều 12).

## Cấu hình và benchmark

- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C).**
  - **A:** `fixed_size`, 500 ký tự, overlap 50, cắt trong phạm vi từng trang (lùi điểm cắt về khoảng trắng gần nhất trong 20% cuối cửa sổ). Cho 1.247 chunk, median 496 ký tự.
  - **B:** `by_article`, mỗi chunk là một Điều và được phép vắt qua trang; tiêu đề Chương/Mục đứng trước Điều được gắn vào Điều đó. Điều dài hơn 1500 ký tự thì tách theo khoản rồi điểm, mỗi phần lặp lại tiêu đề Điều. Cho 589 chunk, median 902 ký tự; 120 Điều bị tách; 207 chunk phủ nhiều trang.
  - **C:** dùng chung **chunk và vector** của B, chỉ thêm `WHERE chuong = …` khi câu hỏi có filter. **Khác biệt duy nhất giữa B và C là filter.**
  - Tham số chunk được chốt trước khi viết câu hỏi và trước khi chạy retrieval.
- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence.**
  - **20 câu, 15 dev / 5 test,** nằm trong `benchmark/questions.json`. Các loại câu: trực tiếp, diễn đạt lại, điều kiện/ngoại lệ, metadata filter. Có 3 câu về sửa đổi năm 2025.
  - **4 câu filter:** q14 (Chương XI), q15 (IX) thuộc dev; q19 (XI), q20 (XXI) thuộc test. Mỗi câu đều có một Điều ở chương khác dùng câu chữ gần giống.
  - **Evidence:** là danh sách trích dẫn nguyên văn. Chunk phải chứa **đủ tất cả** trích dẫn, đúng nguồn, và có trang giao với `gold_page`.
  - **Kiểm chứng:** `scripts/verify_benchmark.py` chạy trước khi retrieval, kết quả 0 lỗi. Script kiểm tra trích dẫn có trên trang gold, nằm trong Điều gold, filter khớp chương, và câu hỏi không chứa số Điều gold. Lần chạy đầu script bắt được một gold page sai ở q18 (Điều 250 trải 3 trang), đã sửa.
  - **Nguy cơ rò rỉ:** ghi trong `benchmark/README.md` (các cặp q14/q19, q15/q17, q05/q16).
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:** (1) Evidence Hit@3 trên dev; (2) nếu chênh lệch ≤ 1 câu thì xét Hit@1 trên dev; (3) nếu vẫn hoà thì chọn chiến lược ít chunk hơn.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 5/15 | 7/15 | 1.247 | chunk 0,011s; search 20 câu 0,77s | chung A+B: $0.0113 |
| A | test | 0/5 | 1/5 | 1.247 | (như trên) | |
| B | dev | 5/15 | 6/15 | 589 | chunk 0,011s; search 20 câu 0,57s | chung A+B: $0.0113 |
| B | test | 1/5 | 3/5 | 589 | (như trên) | |
| C | dev | 5/15 | 6/15 | 589 (dùng chung B) | search 20 câu 0,51s | $0 thêm (dùng lại vector B) |
| C | test | 1/5 | 3/5 | 589 | (như trên) | |

Ghi chú về thời gian và chi phí:
- Thời gian lấy từ `starter/results/runs/2026-11-13T111033Z.json`. Lần chạy này dùng lại vector đã lưu nên `summary.md` ghi embed tài liệu 0s và 0 token. Chỉ số Hit giống hệt cả ba lần chạy.
- Ingest PDF mất 0,69s, dùng chung cho cả ba chiến lược. Embed 20 câu hỏi mất 7,56s (20 request API), cũng dùng chung.
- Thời gian embed tài liệu theo từng index ở lần chạy đầu **không được lưu**, vì `summary.json` bị lần chạy thứ hai ghi đè. Từ sau đó `results/runs/` lưu lại mọi lần chạy.
- Chi phí không tách được theo index: log lần đầu chỉ ghi tổng 564.356 token. Theo tổng số ký tự, A có 562k ký tự, B có 524k.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1,1 (n=10; 0:2, 1:5, 2:3) | 6/15 | test 2/2 (dev 0/2) | 0: 4 · 1: 0 · 2: 1 → 0,4 |
| B | 2,0 (n=10; 2:10) | 15/15 | test 2/2 (dev 0/2) | 0: 2 · 1: 0 · 2: 3 → 1,2 |
| C | 2,0 (n=10; dùng chung chunk B) | 15/15 | test 2/2 (dev 2/2) | 0: 2 · 1: 0 · 2: 3 → 1,2 |

Cột "Filter tuân thủ" là số **câu có filter** mà cả top-3 đều nằm trong chương được yêu cầu. Chỉ số này tính tự động cho cả A/B (dù A/B không áp filter), để so sánh với C.

**Grounding theo từng câu test** (lý do chi tiết trong `manual_grounding.csv`):

| Câu | A | B | C | Ghi chú |
|---|---|---|---|---|
| q16 tham ô | 0 | 2 | 2 | A chỉ lấy tội xâm phạm sở hữu (Điều 171, 170, 173). B/C có Điều 353 khoản 4 ở top-2 |
| q17 thời hiệu | 0 | 0 | 0 | Mọi chiến lược kéo về Chương XXIV (Điều 368–371, 379–380), không có Điều 27 |
| q18 ma túy | 0 | 2 | 2 | A có tiêu đề Điều 250 nhưng chỉ có khoản 1. B/C có `dieu-250:4` (khoản 4 điểm b) |
| q19 pháp nhân | 2 | 2 | 2 | A cần gộp top-2 (tiêu đề Điều 84) với top-3 (điểm đ) |
| q20 giao thông | 0 | 0 | 0 | Top-1 B/C là Điều 272 (đường thủy) trùng nguyên văn mức phạt nhưng sai nguồn, nên tính 0 |

Grounding thủ công khớp với Evidence Hit@3 tự động ở cả 15 dòng: grounding đạt 2 đúng ở những câu Hit@3 = 1 (A: q19; B/C: q16, q18, q19). Đây chỉ là sự trùng khớp trên tập test nhỏ, không phải vì nhãn tay được suy ra từ Hit@3.

**Coherence.** A đạt 1,1/2. Chunk 500 ký tự thường mở đầu bằng đuôi của Điều trước (không có chủ thể) và cắt giữa khoản. Hai vị trí bị 0 điểm vì chỉ còn tiêu đề và vài chữ: pos03 (Điều 6) và pos09 (Điều 28, mất cả danh sách tội không áp dụng thời hiệu). B đạt 2,0/2 ở cả 10 vị trí. **Lưu ý mẫu:** 10 vị trí là tiêu đề Điều ở các trang 2–11, toàn là Điều ngắn ở phần chung (≤ 1.315 ký tự, không bị tách). Mẫu này nghiêng về B; chưa có vị trí nào rơi vào Điều dài bị B tách theo khoản (120 Điều), nên 2,0 là cận trên của B.

**Metadata.** Tiêu chí "đủ và đúng" yêu cầu: `source` đúng; trang ghi trong `page`/`pages` chứa text chunk; `chuong`/`dieu` khớp **toàn bộ** nội dung chunk. B và C đạt 15/15. A đạt 6/15. Cả 9 lỗi của A cùng một kiểu: chunk chứa thêm tiêu đề và nội dung của Điều kế tiếp nhưng `dieu` chỉ ghi Điều ở đầu chunk:

| Câu, hạng | Ghi `dieu` | Thực tế chứa thêm |
|---|---|---|
| q16 #2, #3 | 169, 172 | Điều 170, 173 |
| q17 #1, #2, #3 | 379, 369, 370 | Điều 380, 370, 371 |
| q18 #1, #2 | 270, 249 | Điều 271, 250 |
| q19 #1, #2 | 79, 83 | Điều 80, 84 |

Không có lỗi `source`, trang hay `chuong`. Về độ hữu ích:
- **`pages` và `dieu` giúp truy vết:** người đọc mở đúng trang PDF và tìm được Điều chỉ từ metadata.
- **`chuong` giúp lọc:** C giữ top-3 trong đúng chương ở 2/2 câu filter dev, trong khi B lẫn Điều 70 (Chương X) ở q14.
- **Hạn chế:** `chuong` không phân biệt được hai Điều cùng chương có câu chữ giống nhau (q20: Điều 260 với Điều 272, cùng Chương XXI và Mục 1). Ngoài ra `dieu` của A không đủ để truy vết khi chunk vắt qua hai Điều.

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu.**
- **Trace:** `starter/results/traces.jsonl`, gồm 60 trace (20 câu × 3 chiến lược), mỗi trace có top-3 với chunk id, text, score, trang, metadata, cờ hit và trích dẫn còn thiếu. Bảng tổng hợp ở `summary.md` / `summary.json`.
- **Coherence:** `manual_coherence.csv`, gồm 10 vị trí cố định trước khi chấm: tiêu đề Điều đầu tiên trên mỗi trang 2–11 (Điều 1, 4, 6, 8, 11, 15, 19, 23, 28, 30). Cùng 10 vị trí đó được dùng cho cả 3 chiến lược.
- **Grounding:** `manual_grounding.csv`, gồm 5 câu test × 3 chiến lược.
- **Metadata:** `manual_metadata.csv`, gồm 5 câu test × top-3 × 3 chiến lược.
- **Cách chấm và người chấm:**
  - Nhãn coherence và grounding được chấm nháp với sự hỗ trợ của Claude, theo quy tắc ghi sẵn:
    - coherence: 2 = Điều tại vị trí nằm trọn và có tiêu đề; 1 = có tiêu đề nhưng nội dung bị cắt dở; 0 = gần như chỉ còn tiêu đề;
    - grounding: chấm trên top-3 gộp lại; chunk sai Điều dù câu chữ trùng thì tính 0.
  - Metadata được đối chiếu bằng script với text nguồn đã chuẩn hoá (trang chứa text, tiêu đề Điều/Chương lọt vào chunk).
  - Tác giả rà soát từng nhãn và lý do, đã sửa một nhãn: grounding A q16 từ 1 thành 0.
  - Không có người chấm độc lập thứ hai, nên có nguy cơ thiên lệch. Mỗi nhãn đều kèm lý do trong CSV để người chấm bài kiểm tra lại.

## Phân tích và kết luận

- **So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn.**
  - **A–B (chỉ thay cách chunk):**
    - Trên dev, A hơn B 1 câu ở Hit@3 (7 so với 6), Hit@1 bằng nhau (5/15). Trên test, B hơn rõ (Hit@3 3/5 so với 1/5).
    - A thắng ở câu hỏi một mệnh đề nằm gọn trong 500 ký tự. Ví dụ q15: A tìm được Điều 60 ở hạng 3, còn chunk Điều 60 của B (1.275 ký tự, có cả tiêu đề Chương IX) không vào top-3. Ví dụ q10: chunk A bắt đầu từ cuối Điều 172 nhưng chứa khoản 1 Điều 173.
    - B thắng khi câu trả lời cần **tên tội cùng khung hình phạt**. q18 (test): khoản 4 của Điều 248/249/250/251 có câu chữ gần như trùng nhau; chỉ chunk B (`dieu-250:4`, có lặp lại tiêu đề "Điều 250. Tội vận chuyển trái phép chất ma túy") chứa đủ evidence. q16 (test): B tìm được Điều 353 phần 2, còn A chỉ lấy các tội ở Chương XVI (Điều 171, 170, 173).
    - **Chấm tay cũng nghiêng về B:** coherence 2,0 so với 1,1; metadata đủ/đúng 15/15 so với 6/15; grounding test 1,2 so với 0,4.
    - **Tài nguyên:** B dùng ít hơn khoảng 53% số chunk (589 so với 1.247) và ít ký tự cần embed hơn (524k so với 562k).
    - **Sai số do mẫu nhỏ:** trên dev A hơn 1 câu, trên test B hơn 2 câu. Mỗi câu test tương đương 20 điểm phần trăm, nên không kết luận được chiến lược nào thắng về Hit@3.
  - **B–C (chỉ thêm filter):**
    - Hit@1/Hit@3 **giống hệt nhau** ở cả dev và test.
    - Filter có tác dụng ở mức phạm vi: trên dev, tỷ lệ tuân thủ tăng từ 0/2 lên 2/2. Ví dụ q14: top-3 của B có Điều 70 (Chương X, xóa án tích cho cá nhân) ở hạng 2–3, còn C chỉ trả về Chương XI.
    - Filter **không sửa được xếp hạng bên trong phạm vi**. q15: dù chỉ còn 13 chunk Chương IX, Điều 60 vẫn nằm ngoài top-3.
    - Trên test, filter không làm thay đổi top-3 (q19, q20 vốn đã nằm đúng chương), nên coherence, metadata và grounding của C trùng với B. Filter không tốn thêm chi phí embedding; thời gian search tương đương (0,51s so với 0,57s cho 20 câu).
  - **Ví dụ sai 1 – q13 (dev, Điều 134, trang 43–44), evidence bị cắt rời:** đáp án cần cả điểm b khoản 1 ("dùng a-xít nguy hiểm") lẫn khung khoản 2 điểm đ. B tách Điều 134 theo khoản, A cắt theo cửa sổ, nên không chunk nào chứa đủ. Cả ba chiến lược đều trượt. Top-3 của B là Điều 135/136/138, các tội gây thương tích có câu chữ tương tự.
  - **Ví dụ sai 2 – q20 (test, Điều 260, trang 168), trùng nguyên văn trong cùng chương:** top-1 của B/C là **Điều 272** cùng Chương XXI. Điều này có đúng câu "phạt tiền từ 30.000.000 đồng đến 100.000.000 đồng … phạt tù từ 01 năm đến 05 năm" và "01 người … 61% trở lên". Nếu đọc lướt thì chunk này trông đúng, nhưng nó **sai nguồn**: Điều 272 là "Tội vi phạm quy định về điều khiển phương tiện giao thông đường thủy", không phải giao thông đường bộ. Cả hai Điều cùng Chương XXI và cùng Mục 1, nên filter `chuong` hay `muc` đều không phân biệt được. Cần dựa vào tên tội (`dieu_title`), dùng khớp từ khoá như BM25 với cụm "đường bộ", hoặc thêm reranker.
  - **Lỗi khác:**
    - q17 (test, diễn đạt lại về thời hiệu): mọi chiến lược đều kéo về Chương XXIV (Điều 368/369, cũng chứa cụm "truy cứu trách nhiệm hình sự").
    - q12 (dev): chunk "Chương XII (được bãi bỏ)" chỉ dài 24 ký tự, căn cứ bãi bỏ lại nằm trong chú thích, nên embedding không khớp.
    - q03 và q07 (dev): câu hỏi phần chung bị kéo sang các chunk tội cụ thể dày đặc cụm "phạt tù từ … năm".
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng.**
  - **Theo tiêu chí chốt trước, A–B:** chênh Hit@3 trên dev ≤ 1 câu, Hit@1 hoà, nên xét số chunk và **chọn B** (589 so với 1.247).
  - **B–C hoà ở cả ba tiêu chí.** Tôi chọn **C**, nhưng ghi rõ lý do dựa trên **tiêu chí bổ sung sau khi xem kết quả dev**, không có trong tiêu chí chốt trước: C giữ top-3 đúng phạm vi (dev 2/2 so với 0/2) mà không tốn thêm chi phí.
  - Các chỉ số chấm tay (coherence, metadata, grounding) được đo sau khi đã chọn, **chỉ để tham khảo**, không dùng để chọn. Kết quả của chúng cùng chiều với lựa chọn B/C hơn A.
  - **Điều kiện áp dụng:** C chỉ có lợi khi người dùng hoặc ngữ cảnh **cung cấp chương trước khi truy xuất**; câu không có filter thì C chạy giống B. Các con số test (3/5) được đo sau khi cấu hình đã cố định, và không có thay đổi nào dựa trên test.
  - **Đánh đổi:** chunk theo Điều giữ trọn ý và tên tội, nhưng chunk dài bị loãng, và evidence nằm ở hai khoản khác nhau vẫn có thể bị tách rời (q13).
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí.**
  - **Dữ liệu và metric:**
    - Corpus chỉ có một văn bản nên không chia dev/test theo tài liệu được.
    - Test chỉ có 5 câu: một câu chênh lệch tương đương 20 điểm phần trăm, nên kết quả chỉ mang tính minh hoạ, không suy rộng ra ngoài corpus này.
    - Evidence được so khớp chuỗi rất chặt. Trường hợp trả lời đúng nhưng trích nguồn tương đương khác chưa được khai báo trong `alternatives`.
  - **Quy trình chấm:**
    - Bộ câu hỏi do AI soạn nháp; evidence được kiểm chứng tự động bằng script.
    - Nhãn thủ công được chấm nháp với AI hỗ trợ, rồi một người (tác giả) rà soát; không có người chấm độc lập thứ hai.
    - Mẫu coherence nghiêng về B (toàn Điều ngắn ở phần chung).
    - Kết quả test được in ra cùng lần chạy với dev (cấu hình cố định trước, không chỉnh sau).
  - **Đo đạc:**
    - Thời gian embed theo index ở lần đầu bị mất.
    - Chi phí ước tính theo giá niêm yết.
    - Chỉ thử exact search, chưa thử ANN (HNSW).
  - **Sửa lỗi sau khi chạy:** sau lần chạy chính, đã sửa định nghĩa chỉ số phụ `split_evidence`. Trước đó chỉ số này gộp cả chunk sai nguồn, ví dụ Điều 272 ở q20. Sau khi sửa, chỉ số bằng 0 ở mọi chiến lược. Hit@1/Hit@3 không đổi; đã kiểm tra lại trên trace đã lưu.
- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  1. **Hybrid dense + BM25** (đề bài cho phép làm thêm) để bắt từ khoá pháp lý và con số ("15 năm", "100 gam"). Tham số chọn trên dev; vì test hiện tại đã bị xem, cần một **bộ test mới**.
  2. **Parent retrieval:** truy xuất theo phần của Điều nhưng trả về cả Điều, nhằm sửa q13 và giảm số Điều bị tách.
  3. Đưa nội dung chú thích vào text, hoặc dùng filter `amended_by`, cho các câu hỏi về sửa đổi/bãi bỏ (q12).
  4. Cho trường hợp trùng câu chữ trong cùng chương và cùng mục (q20): khớp theo tên tội (`dieu_title`) hoặc thêm reranker. Filter theo `muc` không đủ, vì Điều 260 và 272 cùng thuộc Mục 1.
  5. Gán metadata của A theo Điều chiếm nhiều text nhất trong chunk, thay vì theo vị trí đầu chunk.

## Công cụ AI và cách kiểm tra

- **Công cụ:** Claude (Anthropic) hỗ trợ viết code pipeline, benchmark nháp, chấm nháp nhãn thủ công và bản nháp báo cáo này.
- **Cách kiểm tra:**
  - Mọi số liệu lấy từ `starter/results/` của lần chạy thật, không có số tự tạo.
  - Evidence được kiểm chứng bằng script.
  - Logic chấm điểm được test offline bằng chunk thật.
  - Nhãn thủ công: quy tắc chấm ghi ở mục "Cách chấm và người chấm". Mỗi nhãn có lý do trong CSV; tác giả rà soát và đã sửa nhãn A q16.
- **Tự rà soát:** ⏳ *(học viên tự viết trước khi nộp: đã đọc lại câu hỏi/đáp án nào so với PDF gốc, đã sửa gì)*
