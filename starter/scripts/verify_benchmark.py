"""Verify the benchmark against the normalized corpus BEFORE any retrieval run.

Checks, per question:
  - required fields, split/filter counts (>=20 total, >=15 dev, >=5 test,
    >=3 filter questions with >=1 in test)
  - every evidence quote occurs on a gold page (whitespace-insensitive; a quote
    may run across two consecutive gold pages)
  - every quote lies inside the gold article (gold_dieu)
  - the filter value equals the gold article's chapter
  - the question text does not name the gold article ("Điều <n>")
Also reports how many places in the corpus each quote occurs (ambiguity).

Run from starter/:  python scripts/verify_benchmark.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

STARTER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STARTER))

from src.chunking import annotate_structure, by_article  # noqa: E402
from src.ingestion import load_pdf  # noqa: E402

ROOT = STARTER.parent
BENCHMARK = ROOT / "benchmark" / "questions.json"
PDF = STARTER / "data" / "raw" / "135-vbhn-vpqh.pdf"
DOC_ID = "blhs-vbhn-135-2025"
OUT = STARTER / "results" / "benchmark_verification.json"
REQUIRED = ["id", "split", "type", "question", "expected_answer", "gold_source_id",
            "gold_page", "evidence_quote", "filter"]


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    questions = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    pages = [p for p in load_pdf(PDF, DOC_ID, "data/raw/135-vbhn-vpqh.pdf")
             if p.metadata["status"] == "ok"]
    annotate_structure(pages)
    by_page = {p.page: flat(p.text) for p in pages}
    articles = {c.metadata["dieu"]: c for c in by_article(pages, 10**9)
                if c.chunk_id.split(":")[2].startswith("dieu-")}
    errors: list[str] = []
    report = []

    n_dev = sum(q.get("split") == "dev" for q in questions)
    n_test = sum(q.get("split") == "test" for q in questions)
    n_filter = sum(bool(q.get("filter")) for q in questions)
    n_filter_test = sum(bool(q.get("filter")) and q.get("split") == "test" for q in questions)
    for cond, msg in [(len(questions) >= 20, "need >= 20 questions"), (n_dev >= 15, "need >= 15 dev"),
                      (n_test >= 5, "need >= 5 test"), (n_filter >= 3, "need >= 3 filter questions"),
                      (n_filter_test >= 1, "need >= 1 filter question in test"),
                      (len({q["id"] for q in questions}) == len(questions), "duplicate ids")]:
        if not cond:
            errors.append(msg)

    for q in questions:
        qid = q.get("id", "?")
        missing = [f for f in REQUIRED if f not in q]
        if missing:
            errors.append(f"{qid}: missing fields {missing}")
            continue
        gold_pages = sorted(q["gold_page"])
        windows = [by_page.get(p, "") for p in gold_pages]
        windows += [f"{by_page.get(a, '')} {by_page.get(b, '')}"
                    for a, b in zip(gold_pages, gold_pages[1:]) if b == a + 1]
        dieu = q.get("gold_dieu")
        art = flat(articles[dieu].text) if dieu in articles else None
        entry = {"id": qid, "split": q["split"], "quotes": []}
        for quote in q["evidence_quote"]:
            fq = flat(quote)
            on_gold = any(fq in w for w in windows)
            found_pages = [p for p, t in by_page.items() if fq in t]
            in_article = art is None or fq in art
            n_articles = sum(fq in flat(c.text) for c in articles.values())
            entry["quotes"].append({"quote": quote[:80], "on_gold_page": on_gold,
                                    "pages_found": found_pages, "in_gold_article": in_article,
                                    "articles_containing": n_articles})
            if not on_gold:
                errors.append(f"{qid}: quote not on gold page {gold_pages}: {quote[:60]!r} (found on {found_pages})")
            if not in_article:
                errors.append(f"{qid}: quote not inside Điều {dieu}: {quote[:60]!r}")
        if dieu and re.search(rf"\bĐiều {re.escape(dieu)}\b", q["question"]):
            errors.append(f"{qid}: question names the gold article Điều {dieu}")
        if q["filter"]:
            if dieu not in articles:
                errors.append(f"{qid}: filter question needs a gold_dieu")
            else:
                actual = articles[dieu].metadata["chuong"]
                entry["gold_chuong"] = actual
                if q["filter"].get("chuong") != actual:
                    errors.append(f"{qid}: filter chuong={q['filter'].get('chuong')} but gold article is in {actual}")
        report.append(entry)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"counts": {"total": len(questions), "dev": n_dev, "test": n_test,
                                          "filter": n_filter, "filter_test": n_filter_test},
                               "errors": errors, "questions": report}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"questions={len(questions)} dev={n_dev} test={n_test} filter={n_filter} (test {n_filter_test})")
    for e in report:
        flags = ["ok" if x["on_gold_page"] and x["in_gold_article"] else "FAIL" for x in e["quotes"]]
        amb = [x["articles_containing"] for x in e["quotes"]]
        print(f"  {e['id']} [{e['split']}] quotes={flags} articles_containing_each_quote={amb}")
    print(f"\n{len(errors)} error(s)")
    for err in errors:
        print("  -", err)
    print(f"report: {OUT.relative_to(ROOT)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
