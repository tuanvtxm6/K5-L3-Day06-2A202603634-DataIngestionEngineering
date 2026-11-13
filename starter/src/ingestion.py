"""Read and normalize source data.

Corpus: Văn bản hợp nhất 135/VBHN-VPQH (Bộ luật Hình sự, hợp nhất đến 2025).
PyMuPDF is used instead of pypdf because pypdf splits Vietnamese syllables
("ch ủ quyền"). Font size separates body text from footnotes in this PDF:

    14pt (>=13.5)         body text of the law (kept)
    13pt, top of page     printed page number (dropped)
    9pt superscript       inline footnote reference, e.g. "61% trở lên⁷⁸" (dropped
                          from text, recorded as metadata with its offset)
    8pt                   footnote number at the start of a footnote
    12pt, lower on page   footnote text (kept separately in metadata)
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pymupdf

from .models import DocumentPage

BODY_MIN_SIZE = 13.5
HEADER_MAX_Y = 50          # printed page numbers sit at y≈29
FOOTNOTE_MIN_Y = 120       # 12pt text above this is a heading (only on page 1)
MIN_VIETNAMESE_RATIO = 0.10

# Private-use sentinels survive normalization and mark inline footnote refs.
_REF_OPEN, _REF_CLOSE = "", ""
_REF_RE = re.compile(f"{_REF_OPEN}(\\d+){_REF_CLOSE}")
# Marks a line whose body spans are all bold (headings); removed after unwrapping.
_BOLD = ""
_ARTICLE = re.compile(r"^Điều \d+[a-z]?\.")

# Lines that start a new structural unit; anything else is a soft line wrap.
# Headings stand alone on their line ("Chương XII (được bãi bỏ)" allowed), so a
# wrapped reference such as "...quy định tại\nChương XIII của Bộ luật này" is not one.
_STRUCT_LINE = re.compile(
    r"^((Phần thứ|PHẦN THỨ) \S+$|(Chương [IVXLC]+|Mục \d+)( \(được bãi bỏ\))?$"
    r"|Điều \d+[a-z]?\.|\d{1,3}\.(\d+\.)?\s|[a-zđ]\)\s|[-–•]\s)"
)
_VIETNAMESE_CHARS = set(
    "ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ"
)

# Look-alike characters seen in this PDF (e.g. "Ðiều 317" uses U+00D0 Eth).
_CHAR_FIXES = str.maketrans({
    "Ð": "Đ",   # Ð (Eth) -> Đ
    "ð": "đ",   # ð (eth) -> đ
    " ": " ",        # no-break space
    "​": None,       # zero-width space
    "﻿": None,       # BOM
    "­": None,       # soft hyphen
})


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace while keeping line structure.

    - NFC composition (273/277 pages are not NFC as extracted)
    - fix look-alike characters (Ð→Đ) and invisible characters
    - collapse runs of spaces/tabs, trim each line, drop blank lines
    - join soft-wrapped lines; keep a break before Phần/Chương/Mục/Điều,
      numbered clauses ("1.") and lettered points ("a)")
    - article titles: a bold line right after a bold "Điều N." line is the
      wrapped tail of the title; a non-bold line there starts the body; a
      non-bold line starting "Điều N." is a wrapped cross-reference, not a title
      (bold is only known for text coming from load_pdf; plain text is treated
      as non-bold except for the "Điều N." line itself)
    """
    text = unicodedata.normalize("NFC", text).translate(_CHAR_FIXES)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line.replace(_BOLD, "").strip()]
    has_bold_info = any(line.startswith(_BOLD) for line in lines)
    out: list[str] = []
    in_title = False                    # out[-1] is an article title line
    for line in lines:
        bold = line.startswith(_BOLD)
        line = line.replace(_BOLD, "")
        visible = _REF_RE.sub("", line)
        article = bool(_ARTICLE.match(visible)) and (bold or not has_bold_info)
        structural = article or (bool(_STRUCT_LINE.match(visible)) and not _ARTICLE.match(visible))
        if not out:
            out.append(line)
        elif in_title:
            if bold and not structural:
                out[-1] = f"{out[-1]} {line}"          # wrapped tail of the title
                continue
            out.append(line)
        elif structural or _is_heading(_REF_RE.sub("", out[-1])):
            out.append(line)
        else:
            out[-1] = f"{out[-1]} {line}"              # soft wrap
        in_title = article
    return "\n".join(out)


def _is_heading(previous: str) -> bool:
    """'Chương II' / 'Phần thứ hai' / 'Mục 1' are followed by their own title line."""
    return bool(re.match(r"^(Chương [IVXLC]+|Phần thứ \S+|PHẦN THỨ \S+|Mục \d+)\S*$", previous))


def strip_refs(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Remove footnote sentinels; return clean text and (offset, number) refs."""
    refs: list[tuple[int, int]] = []
    parts: list[str] = []
    pos = 0
    clean_len = 0
    for match in _REF_RE.finditer(text):
        chunk = text[pos:match.start()]
        parts.append(chunk)
        clean_len += len(chunk)
        refs.append((clean_len, int(match.group(1))))
        pos = match.end()
    parts.append(text[pos:])
    return "".join(parts), refs


def _vietnamese_ratio(text: str) -> float:
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return 0.0
    return sum(c in _VIETNAMESE_CHARS for c in letters) / len(letters)


def _split_spans(page: pymupdf.Page) -> tuple[str, dict[int, str]]:
    """Return body text (with ref sentinels) and footnotes {number: text}."""
    body_lines: list[str] = []
    footnotes: dict[int, str] = {}
    current_note: int | None = None
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            body_parts: list[str] = []
            for span in line["spans"]:
                text, size, y = span["text"], span["size"], span["bbox"][1]
                if not text.strip():
                    body_parts.append(text)
                    continue
                superscript = bool(span["flags"] & 1)
                if size >= BODY_MIN_SIZE:
                    body_parts.append(text)
                elif size >= 12.5:
                    if y >= HEADER_MAX_Y:                      # 13pt is only page numbers
                        body_parts.append(text)
                elif superscript and text.strip().isdigit():
                    body_parts.append(f"{_REF_OPEN}{text.strip()}{_REF_CLOSE}")
                elif 7.5 <= size < 8.5 and text.strip().isdigit():
                    current_note = int(text.strip())           # footnote starts
                    footnotes[current_note] = ""
                elif y < FOOTNOTE_MIN_Y:
                    body_parts.append(text)                    # 12pt heading on page 1
                else:
                    # footnote text; key 0 = continuation of a note from the previous page
                    key = current_note if current_note is not None else 0
                    footnotes[key] = footnotes.get(key, "") + text
            joined = "".join(body_parts)
            if joined.strip():
                # punctuation-only spans ("." after "Điều 177") are often not bold: ignore them
                body_spans = [s for s in line["spans"]
                              if any(ch.isalnum() for ch in s["text"])
                              and s["size"] >= 12.5 and s["bbox"][1] >= HEADER_MAX_Y]
                if body_spans and all(s["flags"] & 16 or "Bold" in s["font"] for s in body_spans):
                    joined = _BOLD + joined
                body_lines.append(joined)
            for key in footnotes:                              # line break inside a note
                if footnotes[key] and not footnotes[key].endswith(" "):
                    footnotes[key] += " "
    notes = {n: re.sub(r"\s+", " ", unicodedata.normalize("NFC", t)).strip()
             for n, t in footnotes.items()}
    return "\n".join(body_lines), notes


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract each physical page; keep page number, footnotes and quality flags.

    Pages with no text or with garbled text (non-Vietnamese glyph soup, e.g. the
    scanned signature page) are returned with metadata["status"] set so the
    caller can log and exclude them. OCR is not attempted here.
    """
    pages: list[DocumentPage] = []
    with pymupdf.open(path) as doc:
        for index, page in enumerate(doc):
            raw_body, footnotes = _split_spans(page)
            text, refs = strip_refs(normalize_text(raw_body))
            if not text.strip():
                status = "empty"
            elif _vietnamese_ratio(text) < MIN_VIETNAMESE_RATIO:
                status = "garbled"
            else:
                status = "ok"
            pages.append(DocumentPage(
                document_id=document_id,
                source=source,
                page=index + 1,
                text=text,
                metadata={
                    "status": status,
                    "char_count": len(text),
                    "footnotes": footnotes,
                    "footnote_refs": refs,
                    "vietnamese_ratio": round(_vietnamese_ratio(text), 3),
                },
            ))
    return pages
