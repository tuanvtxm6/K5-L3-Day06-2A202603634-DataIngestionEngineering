"""Evaluate retrieved evidence and keep a full per-query trace.

Hit definition (see ../../benchmark/README.md): a retrieved chunk is a hit when
  - its document_id equals gold_source_id,
  - its pages intersect gold_page, and
  - its text contains EVERY evidence_quote (whitespace-insensitive),
or the same holds for one of the documented `alternatives` of the question.

Only automatic retrieval metrics are computed here. Grounding, coherence and
metadata-correctness labels are left empty for manual review: exact string
match must not be presented as human judgement.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _gold_sets(question: dict[str, Any]) -> list[dict[str, Any]]:
    """Main gold plus any documented alternative evidence."""
    main = {"gold_source_id": question["gold_source_id"], "gold_page": question["gold_page"],
            "evidence_quote": question["evidence_quote"]}
    alts = [{"gold_source_id": a.get("gold_source_id", question["gold_source_id"]),
             "gold_page": a["gold_page"], "evidence_quote": a["evidence_quote"]}
            for a in question.get("alternatives", [])]
    return [main, *alts]


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _check_hit(hit: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    pages = set(hit.get("pages") or [hit["page"]])
    text = _flat(hit["text"])
    quotes = gold["evidence_quote"]
    found = [q for q in quotes if _flat(q) in text]
    return {
        "source_ok": hit["document_id"] == gold["gold_source_id"],
        "page_ok": bool(pages & set(_as_list(gold["gold_page"]))),
        "quotes_found": len(found),
        "quotes_total": len(quotes),
        "missing_quotes": [q[:80] for q in quotes if q not in found],
    }


def _complies(hit: dict[str, Any], filters: dict[str, Any] | None) -> bool | None:
    if not filters:
        return None
    meta = hit.get("metadata") or {}
    return all(str(meta.get(k)) in map(str, _as_list(v)) for k, v in filters.items())


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]],
                   applied_filter: dict[str, Any] | None = None) -> dict[str, Any]:
    """Score one question's top-k hits; return a trace with hit@1 / hit@3."""
    golds = _gold_sets(question)
    # Compliance is measured against the question's filter for every strategy,
    # so A/B (no filter applied) show how often they leave the requested scope.
    scope = question.get("filter")
    hit_rows = []
    for hit in hits:
        checks = [_check_hit(hit, g) for g in golds]
        is_hit = any(c["source_ok"] and c["page_ok"] and c["quotes_found"] == c["quotes_total"]
                     for c in checks)
        best = max(checks, key=lambda c: (c["source_ok"] and c["page_ok"], c["quotes_found"]))
        meta = hit.get("metadata") or {}
        hit_rows.append({
            "rank": hit["rank"], "chunk_id": hit["chunk_id"], "score": round(hit["score"], 6),
            "document_id": hit["document_id"], "source": hit["source"], "page": hit["page"],
            "pages": hit.get("pages"),
            "metadata": {k: meta.get(k) for k in ("phan", "chuong", "chuong_title", "muc", "dieu",
                                                   "dieu_title", "part", "parts", "amended_by")},
            "text": hit["text"],
            "is_hit": is_hit, **best,
            "filter_ok": _complies(hit, scope),
        })
    top3 = hit_rows[:3]
    # Evidence split across chunks: no single chunk has it all, but the top-3 chunks
    # that are on the gold source/pages do together (identical wording elsewhere,
    # e.g. Điều 272 vs Điều 260, must not count).
    def _covered(gold: dict[str, Any]) -> bool:
        on_gold = [h for h in hits[:3] if (lambda c: c["source_ok"] and c["page_ok"])(_check_hit(h, gold))]
        union = _flat(" ".join(h["text"] for h in on_gold))
        return bool(on_gold) and all(_flat(q) in union for q in gold["evidence_quote"])
    split_evidence = not any(h["is_hit"] for h in top3) and any(_covered(g) for g in golds)
    filter_flags = [h["filter_ok"] for h in top3]
    return {
        "id": question["id"], "split": question["split"], "type": question.get("type"),
        "question": question["question"], "expected_answer": question["expected_answer"],
        "gold_source_id": question["gold_source_id"], "gold_page": question["gold_page"],
        "gold_dieu": question.get("gold_dieu"), "evidence_quote": question["evidence_quote"],
        "question_filter": question.get("filter"), "applied_filter": applied_filter,
        "hit_at_1": bool(top3) and top3[0]["is_hit"],
        "hit_at_3": any(h["is_hit"] for h in top3),
        "first_hit_rank": next((h["rank"] for h in hit_rows if h["is_hit"]), None),
        "split_evidence": split_evidence,
        "filter_compliant": None if not scope else all(f is True for f in filter_flags),
        "hits": hit_rows,
        # Manual labels (filled by a human reviewer, never computed here)
        "manual": {"grounding_0_1_2": None, "grounding_reason": "",
                   "metadata_correct_per_hit": [None] * len(top3), "metadata_notes": ""},
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1 / Evidence Hit@3 by strategy and split, with n/N."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
        groups[(t["strategy"], "all")].append(t)
    out: dict[str, Any] = {}
    for (strategy, split), items in sorted(groups.items()):
        n = len(items)
        h1 = sum(t["hit_at_1"] for t in items)
        h3 = sum(t["hit_at_3"] for t in items)
        applied = [t for t in items if t["applied_filter"] is not None]
        with_filter_q = [t for t in items if t["question_filter"]]
        out.setdefault(strategy, {})[split] = {
            "N": n,
            "hit_at_1": f"{h1}/{n}", "hit_at_1_rate": round(h1 / n, 3) if n else None,
            "evidence_hit_at_3": f"{h3}/{n}", "evidence_hit_at_3_rate": round(h3 / n, 3) if n else None,
            "split_evidence": sum(t["split_evidence"] for t in items),
            "filter_questions": len(with_filter_q),
            "filter_applied": len(applied),
            # top-3 entirely inside the question's scope / questions with a filter
            "filter_compliant": (f"{sum(t['filter_compliant'] for t in with_filter_q)}/{len(with_filter_q)}"
                                 if with_filter_q else "N/A"),
            "filter_questions_hit_at_3": (f"{sum(t['hit_at_3'] for t in with_filter_q)}/{len(with_filter_q)}"
                                          if with_filter_q else "N/A"),
            "misses": [t["id"] for t in items if not t["hit_at_3"]],
        }
    return out
