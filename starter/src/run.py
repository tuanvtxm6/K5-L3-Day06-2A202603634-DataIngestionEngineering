"""Day 06 pipeline: ingest → chunk (A/B) → embed → pgvector → retrieve A/B/C → evaluate.

Run from starter/:
    python -m src.run --dry-run      # ingest + chunk + stats + coherence sample, no API/DB
    python -m src.run                # full run (OpenAI embeddings + pgvector)

Strategies (same corpus, model, store, metric and questions):
    A  fixed-size 500 chars, overlap 50, per page          index fixed500o50, no filter
    B  one chunk per Điều (split by khoản if > 1500 chars)  index article1500, no filter
    C  = B chunks/vectors + SQL filter on `chuong` when the question supplies one
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import annotate_structure, by_article, fixed_size
from .evaluation import evaluate_query, summarize
from .ingestion import load_pdf
from .models import Chunk, DocumentPage

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
RESULTS = STARTER / "results"
BENCHMARK = ROOT / "benchmark" / "questions.json"
MANIFEST = ROOT / "data" / "manifest.json"

CORPUS = {
    "source_id": "blhs-vbhn-135-2025",
    "title": "Văn bản hợp nhất số 135/VBHN-VPQH – Bộ luật Hình sự (hợp nhất BLHS 100/2015/QH13, "
             "Luật 12/2017/QH14, Luật 59/2024/QH15, Luật 86/2025/QH15)",
    "issuer": "Văn phòng Quốc hội",
    "source_path": "starter/data/raw/135-vbhn-vpqh.pdf",
    "source_url": "https://datafiles.chinhphu.vn/cpp/files/vbpq/2025/9/135-vbhn-vpqh.pdf",
    "license_or_permission": "Văn bản quy phạm pháp luật – không thuộc phạm vi bảo hộ quyền tác giả "
                             "(khoản 2 Điều 15 Luật Sở hữu trí tuệ).",
    "accessed_at": "2026-11-13T10:04:49Z",
    "snapshot": "PDF ModDate 2025-09-08; sha256 below",
    "page_counting_rule": "Trang vật lý có status 'ok' (trích được text tiếng Việt), trừ trang 1 "
                          "(trang bìa/danh sách văn bản sửa đổi). Trang 277 (trang xác thực chữ ký, lỗi font) "
                          "bị loại vì 'garbled'.",
}
DOC_ID = CORPUS["source_id"]
PDF = STARTER / "data" / "raw" / "135-vbhn-vpqh.pdf"
STRATEGIES: dict[str, dict[str, Any]] = {
    "A": {"index": "fixed500o50", "chunker": "fixed_size", "size": 500, "overlap": 50, "use_filter": False},
    "B": {"index": "article1500", "chunker": "by_article", "max_size": 1500, "use_filter": False},
    "C": {"index": "article1500", "chunker": "by_article", "max_size": 1500, "use_filter": True},
}
TOP_K = 3
MIN_CONTENT_PAGES = 30
COHERENCE_PAGES = list(range(2, 12))   # first 10 content page IDs, fixed before scoring


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:   # utf-8-sig: opens cleanly in Excel
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


# ------------------------------------------------------------------- ingest
def ingest() -> tuple[list[DocumentPage], dict[str, Any]]:
    if not PDF.exists():
        raise FileNotFoundError(f"{PDF} missing: download it from {CORPUS['source_url']}")
    t0 = time.perf_counter()
    pages = load_pdf(PDF, DOC_ID, CORPUS["source_path"])
    seconds = time.perf_counter() - t0
    ok = [p for p in pages if p.metadata["status"] == "ok"]
    content = [p for p in ok if p.page != 1]
    if len(content) < MIN_CONTENT_PAGES:
        raise RuntimeError(f"only {len(content)} content pages (< {MIN_CONTENT_PAGES})")
    log = {
        "physical_pages": len(pages), "ok_pages": len(ok), "content_pages_counted": len(content),
        "excluded_pages": [{"page": p.page, "status": p.metadata["status"],
                            "vietnamese_ratio": p.metadata["vietnamese_ratio"],
                            "preview": p.text[:120]} for p in pages if p.metadata["status"] != "ok"],
        "cover_page_not_counted": 1,
        "footnotes_extracted": sum(len([k for k in p.metadata["footnotes"] if k]) for p in pages),
        "footnote_refs_removed_from_text": sum(len(p.metadata["footnote_refs"]) for p in pages),
        "repealed": ["Chương XII (Điều 90–107) – 'được bãi bỏ' theo Luật 59/2024/QH15 (chú thích 34)"],
        "normalization": ["NFC", "Ð(U+00D0)→Đ(U+0110), ð→đ", "drop zero-width/soft hyphen/BOM, NBSP→space",
                          "drop page numbers (13pt, top) and inline footnote refs (9pt superscript)",
                          "footnote text (8pt number + 12pt text) kept in metadata only",
                          "join soft line wraps; keep breaks before Phần/Chương/Mục/Điều/khoản/điểm; "
                          "bold detects wrapped article titles"],
        "seconds": round(seconds, 3),
    }
    manifest = {**CORPUS, "sha256": sha256(PDF), "physical_pages": len(pages),
                "content_pages": [p.page for p in content],
                "excluded_pages": [p.page for p in pages if p not in content],
                "chars_per_page": {p.page: p.metadata["char_count"] for p in pages},
                "total_content_chars": sum(p.metadata["char_count"] for p in content)}
    write_json(MANIFEST, manifest)
    return ok, log


# -------------------------------------------------------------------- chunk
def build_indexes(pages: list[DocumentPage]) -> tuple[dict[str, list[Chunk]], dict[str, Any]]:
    annotate_structure(pages)
    indexes: dict[str, list[Chunk]] = {}
    stats: dict[str, Any] = {}
    for cfg in STRATEGIES.values():
        name = cfg["index"]
        if name in indexes:
            continue
        t0 = time.perf_counter()
        if cfg["chunker"] == "fixed_size":
            chunks = [c for p in pages for c in fixed_size(p, cfg["size"], cfg["overlap"])]
        else:
            chunks = by_article(pages, cfg["max_size"])
        lengths = sorted(len(c.text) for c in chunks)
        stats[name] = {
            "chunks": len(chunks), "seconds": round(time.perf_counter() - t0, 3),
            "chars_total": sum(lengths), "len_min": lengths[0], "len_median": statistics.median(lengths),
            "len_mean": round(statistics.mean(lengths), 1), "len_p90": lengths[int(0.9 * (len(lengths) - 1))],
            "len_max": lengths[-1],
            "multi_page_chunks": sum(len(c.metadata["pages"]) > 1 for c in chunks),
            "chunks_without_chuong": sum(c.metadata["chuong"] is None for c in chunks),
        }
        if len({c.chunk_id for c in chunks}) != len(chunks):
            raise RuntimeError(f"{name}: duplicate chunk ids")
        indexes[name] = chunks
    return indexes, stats


def coherence_sample(pages: list[DocumentPage], indexes: dict[str, list[Chunk]]) -> list[dict[str, Any]]:
    """Same 10 source positions for every strategy: the first 'Điều N.' heading
    on each of pages 2–11 (page start if a page has no heading)."""
    by_page = {p.page: p for p in pages}
    rows = []
    for n, pno in enumerate(COHERENCE_PAGES, 1):
        page = by_page[pno]
        dieu_events = [(off, val) for off, key, val in page.metadata["structure_events"] if key == "dieu"]
        offset, label = (dieu_events[0][0], f"Điều {dieu_events[0][1][0]}") if dieu_events else (0, "đầu trang")
        for strategy, cfg in STRATEGIES.items():
            chunks = indexes[cfg["index"]]
            if cfg["chunker"] == "fixed_size":
                found = next(c for c in chunks if c.page == pno
                             and c.metadata["start_offset"] <= offset < c.metadata["end_offset"])
            else:
                dieu = dieu_events[0][1][0] if dieu_events else None
                found = next((c for c in chunks if dieu and c.metadata["dieu"] == dieu
                              and c.metadata.get("part") == 1),
                             next(c for c in chunks if pno in c.metadata["pages"]))
            rows.append({"position_id": f"pos{n:02d}", "page": pno, "position": label,
                         "strategy": strategy, "chunk_id": found.chunk_id,
                         "note": "C dùng chung chunk với B" if strategy == "C" else "",
                         "chunk_text": found.text, "coherence_0_1_2": "", "reason": ""})
    return rows


# ---------------------------------------------------------------- embed/store
def sync_index(store, embedder, name: str, chunks: list[Chunk]) -> dict[str, Any]:
    existing = store.existing_hashes(name)
    todo = [c for c in chunks
            if existing.get(c.chunk_id) != (c.metadata["content_hash"], embedder.model_name)]
    tokens_before = embedder.prompt_tokens
    t0 = time.perf_counter()
    vectors = embedder.embed_documents([c.text for c in todo]) if todo else []
    embed_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    written = store.upsert(name, todo, vectors, embedder.model_name) if todo else 0
    pruned = store.prune(name, DOC_ID, [c.chunk_id for c in chunks])
    counts = store.count(name)
    if counts["rows"] != len(chunks) or counts["distinct_chunk_ids"] != len(chunks):
        raise RuntimeError(f"{name}: store has {counts}, expected {len(chunks)} unique rows")
    # Re-ingest check: the same chunks again must need no new embedding and add no rows.
    again = store.existing_hashes(name)
    would_embed = sum(again.get(c.chunk_id) != (c.metadata["content_hash"], embedder.model_name)
                      for c in chunks)
    return {"chunks": len(chunks), "embedded_this_run": len(todo), "reused_from_store": len(chunks) - len(todo),
            "written": written, "pruned_obsolete": pruned, "rows_after": counts["rows"],
            "reingest_would_embed": would_embed, "embed_seconds": round(embed_s, 2),
            "store_seconds": round(time.perf_counter() - t1, 2),
            "prompt_tokens": embedder.prompt_tokens - tokens_before}


# ------------------------------------------------------------------ report
def summary_markdown(summary: dict[str, Any], index_stats: dict[str, Any], sync: dict[str, Any],
                     usage: dict[str, Any], query_seconds: dict[str, float]) -> str:
    lines = ["# Kết quả tự động (Hit@1 / Evidence Hit@3)", "",
             f"Model: `{usage['model']}` ({usage['dimensions']} chiều) · tokens: {usage['prompt_tokens']} · "
             f"chi phí ước tính: ${usage['cost_usd']:.6f} (giá {usage['price_per_mtok_usd']} USD/1M tokens, cần kiểm tra)",
             "", "| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |",
             "|---|---|---|---|---|---|---|"]
    for strategy, cfg in STRATEGIES.items():
        s = sync[cfg["index"]]
        for split in ("dev", "test"):
            m = summary[strategy][split]
            extra = " (dùng lại vector của B)" if strategy == "C" else ""
            lines.append(f"| {strategy} | {split} | {m['hit_at_1']} | {m['evidence_hit_at_3']} | "
                         f"{index_stats[cfg['index']]['chunks']} | embed {s['embed_seconds']}s, "
                         f"query {query_seconds[strategy]:.2f}s{extra} | tokens {s['prompt_tokens']} |")
    lines += ["", "| Strategy | Split | Filter tuân thủ top-3 (n/N câu có filter) | Hit@3 câu filter | "
                  "Evidence bị tách nhiều chunk | Câu trượt top-3 |", "|---|---|---|---|---|---|"]
    for strategy in STRATEGIES:
        for split in ("dev", "test"):
            m = summary[strategy][split]
            lines.append(f"| {strategy} | {split} | {m['filter_compliant']} | {m['filter_questions_hit_at_3']} | "
                         f"{m['split_evidence']} | {', '.join(m['misses']) or '—'} |")
    lines += ["", "Coherence, grounding, metadata đúng/đủ: chấm tay trong các file `manual_*.csv`.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="ingest + chunk only; no API, no database")
    args = parser.parse_args()
    load_dotenv(STARTER / ".env")
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    pages, ingest_log = ingest()
    indexes, index_stats = build_indexes(pages)
    write_json(RESULTS / "ingest_log.json", ingest_log)
    write_json(RESULTS / "chunk_stats.json", index_stats)
    write_csv(RESULTS / "manual_coherence.csv", coherence_sample(pages, indexes))
    print(f"ingest: {ingest_log['content_pages_counted']} content pages, excluded "
          f"{[e['page'] for e in ingest_log['excluded_pages']]} | manifest → {MANIFEST.relative_to(ROOT)}")
    for name, s in index_stats.items():
        print(f"index {name}: {s['chunks']} chunks, median {s['len_median']} chars, max {s['len_max']}")
    if args.dry_run:
        print("dry run: stopped before embedding (no API call, no database write)")
        return

    from .embeddings import OpenAIEmbedder          # imported here so --dry-run needs no key
    from .store import PgVectorStore

    embedder = OpenAIEmbedder(os.getenv("EMBEDDING_MODEL", ""))
    store = PgVectorStore(os.getenv("DATABASE_URL", ""), embedder.dimensions)
    store.create_schema()
    sync = {name: sync_index(store, embedder, name, chunks) for name, chunks in indexes.items()}
    for name, s in sync.items():
        print(f"store {name}: embedded {s['embedded_this_run']}, reused {s['reused_from_store']}, "
              f"pruned {s['pruned_obsolete']}, rows {s['rows_after']}, re-ingest would embed {s['reingest_would_embed']}")

    questions = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    tokens_before = embedder.prompt_tokens
    qvecs = {q["id"]: embedder.embed_query(q["question"]) for q in questions}  # same vector for A/B/C
    query_tokens = embedder.prompt_tokens - tokens_before

    traces: list[dict[str, Any]] = []
    query_seconds: dict[str, float] = {}
    for strategy, cfg in STRATEGIES.items():
        t0 = time.perf_counter()
        for q in questions:
            applied = q["filter"] if cfg["use_filter"] and q.get("filter") else None
            hits = store.search(cfg["index"], qvecs[q["id"]], top_k=TOP_K, filters=applied)
            trace = evaluate_query(q, hits, applied_filter=applied)
            traces.append({"strategy": strategy, "index": cfg["index"], **trace})
        query_seconds[strategy] = time.perf_counter() - t0

    summary = summarize(traces)
    usage = embedder.usage()
    with (RESULTS / "traces.jsonl").open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    run_record = {
        "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {"strategies": STRATEGIES, "top_k": TOP_K, "metric": "cosine (pgvector <=>), exact search",
                   "embedding": usage, "query_tokens": query_tokens},
        "versions": {"python": platform.python_version(),
                     **{pkg: version(pkg) for pkg in ("pymupdf", "psycopg", "openai", "python-dotenv")}},
        "index_stats": index_stats, "store_sync": sync, "query_seconds": query_seconds,
        "metrics": summary}
    write_json(RESULTS / "summary.json", run_record)
    # keep every run: summary.json is overwritten, the history is not
    write_json(RESULTS / "runs" / f"{started.replace(':', '').replace('+0000', 'Z')}.json", run_record)
    (RESULTS / "summary.md").write_text(summary_markdown(summary, index_stats, sync, usage, query_seconds),
                                        encoding="utf-8")

    test = [t for t in traces if t["split"] == "test"]
    write_csv(RESULTS / "manual_grounding.csv", [
        {"strategy": t["strategy"], "id": t["id"], "question": t["question"],
         "expected_answer": t["expected_answer"], "filter": json.dumps(t["applied_filter"], ensure_ascii=False),
         "auto_hit_at_3": t["hit_at_3"],
         **{f"top{h['rank']}": f"[{h['chunk_id']} | p{h['pages']}] {h['text']}" for h in t["hits"]},
         "grounding_0_1_2": "", "reason": ""} for t in test])
    write_csv(RESULTS / "manual_metadata.csv", [
        {"strategy": t["strategy"], "id": t["id"], "rank": h["rank"], "chunk_id": h["chunk_id"],
         "source": h["source"], "page": h["page"], "pages": h["pages"], "chuong": h["metadata"]["chuong"],
         "dieu": h["metadata"]["dieu"], "question_filter": json.dumps(t["question_filter"], ensure_ascii=False),
         "auto_filter_ok": h["filter_ok"], "text_preview": h["text"][:200],
         "metadata_correct_1_0": "", "error_note": ""} for t in test for h in t["hits"]])

    print(f"\nembedding tokens: {usage['prompt_tokens']} (queries {query_tokens}) | "
          f"cost ≈ ${usage['cost_usd']:.6f}")
    for strategy in STRATEGIES:
        for split in ("dev", "test"):
            m = summary[strategy][split]
            print(f"{strategy} {split:4}: Hit@1 {m['hit_at_1']:>5}  Hit@3 {m['evidence_hit_at_3']:>5}  "
                  f"filter-compliant {m['filter_compliant']}")
    print(f"results → {RESULTS.relative_to(ROOT)}/ (traces.jsonl, summary.json, summary.md, manual_*.csv)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:                       # surface backend errors, never fall back to mocks
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
