"""Fixed-size (strategy A) and article-aware (strategy B/C) chunking.

Both strategies attach the same structural metadata, derived from headings in
the text itself (never guessed):

    phan, chuong, chuong_title, muc, dieu, dieu_title,
    footnote_ids, amended_by (law numbers cited by those footnotes)

so that an A–B comparison changes only the chunk boundaries.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from .models import Chunk, DocumentPage

_PHAN = re.compile(r"(?m)^(Phần thứ \S+)$")
_CHUONG = re.compile(r"(?m)^Chương ([IVXLC]+)( \(được bãi bỏ\))?$")
_MUC = re.compile(r"(?m)^Mục (\d+)$")
_DIEU = re.compile(r"(?m)^Điều (\d+[a-z]?)\. ?(.*)$")
_KHOAN = re.compile(r"(?m)^\d{1,3}\.(?:\d+\.)?\s")
_DIEM = re.compile(r"(?m)^[a-zđ]\)\s")
_LAW_NO = re.compile(r"\b\d+/\d{4}/QH\d+\b")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- structure
@dataclass
class _Event:
    page: int
    offset: int
    key: str
    value: Any


def annotate_structure(pages: list[DocumentPage]) -> None:
    """Record heading positions on each page; context carries across pages.

    Writes page.metadata["structure_start"] (context in force at offset 0) and
    page.metadata["structure_events"] [(offset, key, value), ...].
    """
    ctx: dict[str, Any] = {"phan": None, "chuong": None, "chuong_title": None,
                           "muc": None, "dieu": None, "dieu_title": None}
    for page in pages:
        page.metadata["structure_start"] = dict(ctx)
        events: list[tuple[int, str, Any]] = []
        found: list[tuple[int, str, Any]] = []
        for m in _PHAN.finditer(page.text):
            found.append((m.start(), "phan", m.group(1)))
        for m in _CHUONG.finditer(page.text):
            title = "(được bãi bỏ)" if m.group(2) else _next_line(page.text, m.end())
            found.append((m.start(), "chuong", (m.group(1), title)))
        for m in _MUC.finditer(page.text):
            found.append((m.start(), "muc", m.group(1)))
        for m in _DIEU.finditer(page.text):
            found.append((m.start(), "dieu", (m.group(1), m.group(2).strip())))
        for offset, key, value in sorted(found, key=lambda e: e[0]):
            if key == "phan":
                ctx.update(phan=value, chuong=None, chuong_title=None, muc=None, dieu=None, dieu_title=None)
            elif key == "chuong":
                ctx.update(chuong=value[0], chuong_title=value[1], muc=None, dieu=None, dieu_title=None)
            elif key == "muc":
                ctx.update(muc=value, dieu=None, dieu_title=None)
            else:
                ctx.update(dieu=value[0], dieu_title=value[1])
            events.append((offset, key, value))
        page.metadata["structure_events"] = events


def _next_line(text: str, pos: int) -> str | None:
    rest = text[pos:].lstrip("\n")
    line = rest.split("\n", 1)[0].strip()
    return line or None


def _context_at(page: DocumentPage, offset: int) -> dict[str, Any]:
    """Structural context in force at a character offset of a page."""
    ctx = dict(page.metadata["structure_start"])
    for event_offset, key, value in page.metadata["structure_events"]:
        if event_offset > offset:
            break
        if key == "phan":
            ctx.update(phan=value, chuong=None, chuong_title=None, muc=None, dieu=None, dieu_title=None)
        elif key == "chuong":
            ctx.update(chuong=value[0], chuong_title=value[1], muc=None, dieu=None, dieu_title=None)
        elif key == "muc":
            ctx.update(muc=value, dieu=None, dieu_title=None)
        else:
            ctx.update(dieu=value[0], dieu_title=value[1])
    return ctx


def _footnote_meta(spans: list[tuple[DocumentPage, int, int]]) -> dict[str, Any]:
    """Footnotes referenced inside (page, start, end) spans and the laws they cite."""
    ids: list[int] = []
    laws: set[str] = set()
    for page, start, end in spans:
        for offset, number in page.metadata.get("footnote_refs", []):
            if start <= offset <= end and number not in ids:
                ids.append(number)
                laws.update(_LAW_NO.findall(page.metadata["footnotes"].get(number, "")))
    return {"footnote_ids": ids, "amended_by": sorted(laws)}


def _base_meta(ctx: dict[str, Any], text: str) -> dict[str, Any]:
    return {**ctx, "char_count": len(text), "content_hash": _hash(text)}


# --------------------------------------------------------------- strategy A
def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Overlapping character windows within one page.

    The window end is moved back to the last whitespace (if one exists in the
    last 20% of the window) so that a Vietnamese syllable is never cut in half;
    otherwise the split is purely positional, by design.
    """
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("require size > 0 and 0 <= overlap < size")
    if "structure_start" not in page.metadata:
        raise ValueError("call annotate_structure(pages) on the whole document first")
    text = page.text
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + int(size * 0.8), end)
            cut = max(cut, text.rfind("\n", start + int(size * 0.8), end))
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            meta = _base_meta(_context_at(page, start), piece)
            meta.update(_footnote_meta([(page, start, end)]))
            meta.update(strategy_chunker=f"fixed-{size}-{overlap}", pages=[page.page],
                        start_offset=start, end_offset=end)
            chunks.append(Chunk(
                chunk_id=f"fixed{size}o{overlap}:{page.document_id}:p{page.page}:{start}",
                document_id=page.document_id, source=page.source, page=page.page,
                text=piece, metadata=meta))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


# --------------------------------------------------------------- strategy B
@dataclass
class _Unit:
    """A contiguous run of text that may span several pages."""
    key: str                                   # "dieu-173" / "preamble" / "chuong-XII"
    ctx: dict[str, Any]
    segments: list[tuple[DocumentPage, int, int]] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join(p.text[s:e].strip("\n") for p, s, e in self.segments if p.text[s:e].strip())


def _units(pages: list[DocumentPage]) -> list[_Unit]:
    """Cut the page stream at every Điều heading; text before the first Điều of a
    chapter (headings) is attached to the next Điều, the document preamble and
    repealed chapters become their own unit."""
    # (page index, cut offset, key, offset used for context)
    boundaries: list[tuple[int, int, str, int]] = []
    for i, page in enumerate(pages):
        heading_start: int | None = None               # Phần/Chương/Mục lines before a Điều
        for offset, key, value in page.metadata["structure_events"]:
            if key == "dieu":
                cut = heading_start if heading_start is not None else offset
                boundaries.append((i, cut, f"dieu-{value[0]}", offset))
                heading_start = None
            elif key == "chuong" and value[1] == "(được bãi bỏ)":
                boundaries.append((i, offset, f"chuong-{value[0]}", offset))
                heading_start = None
            elif heading_start is None:
                heading_start = offset
    if not boundaries or boundaries[0][:2] != (0, 0):
        boundaries.insert(0, (0, 0, "preamble", 0))
    units: list[_Unit] = []
    for n, (pi, off, key, ctx_off) in enumerate(boundaries):
        end_pi, end_off = (boundaries[n + 1][0], boundaries[n + 1][1]) if n + 1 < len(boundaries) \
            else (len(pages) - 1, len(pages[-1].text))
        unit = _Unit(key=key, ctx=_context_at(pages[pi], ctx_off))
        for p in range(pi, end_pi + 1):
            s = off if p == pi else 0
            e = end_off if p == end_pi else len(pages[p].text)
            if e > s:
                unit.segments.append((pages[p], s, e))
        units.append(unit)
    return units


def _split_long(text: str, max_size: int, header: str) -> list[str]:
    """Split an over-long article at clause (khoản) boundaries, then points
    (điểm), then whitespace. Every part after the first is prefixed with the
    article heading so it still says which article it belongs to."""
    if len(text) <= max_size:
        return [text]
    budget = max_size - len(header) - 1

    def pieces(block: str, level: int) -> list[str]:
        if len(block) <= budget:
            return [block]
        pattern = (_KHOAN, _DIEM)[level] if level < 2 else None
        if pattern is None:                                   # hard split on whitespace
            out, rest = [], block
            while len(rest) > budget:
                cut = rest.rfind(" ", 0, budget)
                cut = cut if cut > budget // 2 else budget
                out.append(rest[:cut].strip())
                rest = rest[cut:].strip()
            return out + ([rest] if rest else [])
        starts = [m.start() for m in pattern.finditer(block)]
        if not starts or starts == [0]:
            return pieces(block, level + 1)
        starts = ([0] if starts[0] != 0 else []) + starts
        parts = [block[a:b].strip("\n") for a, b in zip(starts, starts[1:] + [len(block)])]
        out: list[str] = []
        for part in parts:
            out.extend(pieces(part, level + 1) if len(part) > budget else [part])
        return out

    grouped: list[str] = []
    for part in pieces(text, 0):
        if grouped and len(grouped[-1]) + 1 + len(part) <= budget:
            grouped[-1] = f"{grouped[-1]}\n{part}"
        else:
            grouped.append(part)
    return [g if i == 0 or g.startswith(header) else f"{header}\n{g}" for i, g in enumerate(grouped)]


def by_article(pages: list[DocumentPage], max_size: int) -> list[Chunk]:
    """One chunk per Điều (may span pages); oversized articles are split by
    khoản/điểm with the article heading repeated. `page` is the first page the
    chunk text appears on; metadata["pages"] lists every page it covers."""
    if "structure_events" not in pages[0].metadata:
        annotate_structure(pages)
    chunks: list[Chunk] = []
    for unit in _units(pages):
        text = unit.text()
        if not text.strip():
            continue
        dieu, title = unit.ctx.get("dieu"), unit.ctx.get("dieu_title")
        header = f"Điều {dieu}. {title}" if unit.key.startswith("dieu-") else ""
        parts = _split_long(text, max_size, header) if header else [text]
        fn = _footnote_meta(unit.segments)              # article-level: same for every part
        for k, part in enumerate(parts):
            body = part[len(header) + 1:] if k and part.startswith(header + "\n") else part
            first_page = _page_of(unit, body.strip()[:40])
            last_page = _page_of(unit, body.strip()[-40:])
            page_list = [p.page for p, _, _ in unit.segments if first_page <= p.page <= last_page]
            meta = _base_meta(unit.ctx, part)
            meta.update(fn)
            meta.update(strategy_chunker=f"article-{max_size}", pages=page_list,
                        part=k + 1, parts=len(parts))
            chunks.append(Chunk(
                chunk_id=f"article{max_size}:{pages[0].document_id}:{unit.key}:{k + 1}",
                document_id=pages[0].document_id, source=pages[0].source,
                page=first_page, text=part, metadata=meta))
    return chunks


def _page_of(unit: _Unit, probe: str) -> int:
    """First page of the unit whose segment contains `probe` (a 40-char snippet)."""
    for page, s, e in unit.segments:
        if probe and probe in page.text[s:e]:
            return page.page
    return unit.segments[0][0].page


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Starter signature kept for reference; this corpus uses by_article()."""
    raise NotImplementedError("Use by_article(pages, max_size): articles span pages in this corpus")
