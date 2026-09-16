"""
Core Phase 1 preprocessing: turn one raw HUM19UK .txt file into a structured
ParsedNovel record (metadata + cleaned body + division offsets + page
offsets + sentences), ready for insertion into SQLite.

Design notes
------------
- Single forward pass over the raw text collects tag matches (division tags,
  page tags, plain-text division fallbacks) in document order, then rebuilds
  a "cleaned_text" string with all markup stripped, recording each tag's
  *character offset in the cleaned text* as it goes. This is what makes
  later page-anchored / division-anchored visualization possible without
  re-scanning the raw file.
- Sentence segmentation runs on the cleaned text using NLTK's punkt
  tokenizer (fast, no model download needed beyond the one-time punkt
  data). Word-by-word granularity (Phase 2's stretch goal) is deliberately
  NOT done here -- Phase 1's job is clean structured text + sentence
  boundaries; tense/tag-level tokenization belongs in the Phase 2 engine.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import nltk

from . import config

try:
    nltk.data.find("tokenizers/punkt")
except (LookupError, OSError):
    nltk.download("punkt", quiet=True)


@dataclass
class Division:
    division_type: str
    number: str
    title: str
    start_char: int  # offset into cleaned_text
    order_index: int


@dataclass
class Page:
    page_number: str
    char_offset: int  # offset into cleaned_text
    order_index: int


@dataclass
class Sentence:
    text: str
    start_char: int
    end_char: int
    sentence_index: int


@dataclass
class ParsedNovel:
    filename: str
    title: str | None
    author: str | None
    author_gender: str | None
    year: int | None
    source: str | None
    cleaned_text: str
    word_count: int
    divisions: list[Division] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    sentences: list[Sentence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _normalize_encoding(raw_bytes: bytes) -> str:
    """Decode to UTF-8, normalizing to NFC and collapsing smart-quote/dash
    variants that otherwise fragment tokenization downstream."""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw_bytes.decode("utf-8", errors="replace")
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # some files carry a UTF-8 BOM that decodes to a literal U+FEFF even via
    # the plain "utf-8" codec path (only utf-8-sig strips it), which would
    # otherwise sit before the header block and break the header regex.
    text = text.lstrip("﻿")
    return text


def _strip_gutenberg_boilerplate(text: str) -> str:
    m = config.GUTENBERG_START.search(text)
    if m:
        text = text[m.end():]
    m = config.GUTENBERG_END.search(text)
    if m:
        text = text[: m.start()]
    return text


def _extract_header(text: str) -> tuple[dict, str]:
    """Pull the compiler-added metadata block off the top of the file and
    isolate the novel body. <text>...</text> reliably bounds the real
    content in every sampled file, so it's used as the primary split point
    (this also discards any trailing errata/corrections lists some
    Gutenberg-sourced files append after </text>). Falls back to a fixed
    line-count heuristic if a file lacks the <text> marker entirely.
    Returns (fields_dict, body_text)."""
    start_m = config.TEXT_START_PATTERN.search(text)
    if start_m:
        head_chunk = text[: start_m.start()]
        body = text[start_m.end():]
        end_m = config.TEXT_END_PATTERN.search(body)
        if end_m:
            body = body[: end_m.start()]
        matches = config.HEADER_FIELD_PATTERN.findall(head_chunk)
        fields = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in matches}
        return fields, body.lstrip("\n")

    # fallback for files with no <text> marker at all: locate the header
    # block by finding where the line of the last recognized header field
    # ends, and treat everything after that as body.
    head_chunk = "\n".join(text.split("\n")[: config.HEADER_MAX_LINES])
    matches = config.HEADER_FIELD_PATTERN.findall(head_chunk)
    fields = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in matches}
    if matches:
        last_field_line = matches[-1][1]
        idx = text.find(last_field_line)
        line_end = text.find("\n", idx)
        remaining = text[line_end + 1:] if line_end != -1 else text
    else:
        remaining = text
    return fields, remaining.lstrip("\n")


def _roman_or_int(s: str) -> str:
    return s.strip()


def _division_number(title: str) -> str:
    """Best-effort extraction of a roman/arabic numeral from a division
    title like 'VOL. I.' or 'XIX. MONTGOMERY'S "BANK HOLIDAY.'. Returns ''
    if none is found (e.g. spelled-out numbers like 'PART TWO')."""
    m = config.DIVISION_NUMBER_PATTERN.search(title)
    return m.group(1) if m else ""


def _walk_tags(text: str):
    """Yield (kind, match) tuples for every division/page tag in document
    order, trying tag-based patterns first and falling back to plain-text
    markers only where no tags exist at all in the file."""
    tag_spans = []
    for m in config.DIVISION_TAG_PATTERN.finditer(text):
        tag_spans.append(("division_tag", m))
    for m in config.PAGE_TAG_PATTERN.finditer(text):
        tag_spans.append(("page_tag", m))

    if not any(kind == "division_tag" for kind, _ in tag_spans):
        for m in config.DIVISION_PLAIN_PATTERN.finditer(text):
            tag_spans.append(("division_plain", m))

    tag_spans.sort(key=lambda km: km[1].start())
    return tag_spans


def _strip_tags_and_index(text: str) -> tuple[str, list[Division], list[Page]]:
    """Single pass: build cleaned_text with tags removed, recording each
    tag's offset *in the cleaned text* as we go."""
    tag_spans = _walk_tags(text)
    cleaned_parts = []
    cleaned_len = 0
    cursor = 0
    divisions: list[Division] = []
    pages: list[Page] = []
    div_order = 0
    page_order = 0

    for kind, m in tag_spans:
        start, end = m.span()
        if start < cursor:
            continue  # overlapping match, skip
        # text before this tag is body content -> keep
        chunk = text[cursor:start]
        cleaned_parts.append(chunk)
        cleaned_len += len(chunk)

        if kind == "division_tag":
            div_title = m.groupdict().get("div_title")
            if div_title is not None:
                dtype, title = "volume", div_title.strip()
            else:
                dtype, title = "chapter", (m.groupdict().get("chap_title") or "").strip()
            num = _division_number(title)
            divisions.append(Division(dtype, _roman_or_int(num), title, cleaned_len, div_order))
            div_order += 1
        elif kind == "division_plain":
            groups = m.groups()
            if groups[0]:  # VOLUME/BOOK/PART line
                dtype, num, title = groups[0].lower(), groups[1], ""
            else:  # CHAPTER line
                dtype, num, title = "chapter", groups[2], (groups[3] or "").strip()
            divisions.append(Division(dtype, _roman_or_int(num), title, cleaned_len, div_order))
            div_order += 1
            # plain markers are real text the reader sees -- keep them,
            # rather than deleting, so cleaned_text stays human-readable
            cleaned_parts.append(m.group(0))
            cleaned_len += len(m.group(0))
        elif kind == "page_tag":
            pages.append(Page(m.group(1) or "", cleaned_len, page_order))
            page_order += 1

        cursor = end

    cleaned_parts.append(text[cursor:])
    cleaned_len += len(text[cursor:])
    cleaned_text = "".join(cleaned_parts)

    # collapse the excess blank lines left behind by tag removal
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    cleaned_text = re.sub(r"[ \t]{2,}", " ", cleaned_text)
    return cleaned_text.strip(), divisions, pages


def _load_sentence_tokenizer():
    # nltk's own sent_tokenize() loads the pickled "punkt" model on the
    # currently pinned nltk version; fall back to the newer punkt_tab
    # directory format for forward compatibility with nltk>=3.9.
    try:
        return nltk.data.load("tokenizers/punkt/english.pickle")
    except (LookupError, OSError, ValueError):
        return nltk.data.load("tokenizers/punkt_tab/english/")


_SENTENCE_TOKENIZER = _load_sentence_tokenizer()


def _segment_sentences(text: str) -> list[Sentence]:
    # an untrained PunktSentenceTokenizer() has no abbreviation list and
    # mis-splits on "Mr.", "Dr.", "St." etc., which 19th-century prose is
    # full of -- the pretrained english model is required for correctness.
    spans = list(_SENTENCE_TOKENIZER.span_tokenize(text))
    sentences = []
    for i, (start, end) in enumerate(spans):
        sentences.append(Sentence(text[start:end].strip(), start, end, i))
    return sentences


def parse_novel(path: Path) -> ParsedNovel:
    raw_bytes = path.read_bytes()
    text = _normalize_encoding(raw_bytes)
    text = _strip_gutenberg_boilerplate(text)
    header_fields, body = _extract_header(text)
    cleaned_text, divisions, pages = _strip_tags_and_index(body)
    sentences = _segment_sentences(cleaned_text)

    word_count = len(cleaned_text.split())
    warnings = []
    if word_count < config.MIN_NOVEL_WORDS:
        warnings.append(f"suspiciously short ({word_count} words) -- check for truncation/corruption")
    if not header_fields.get("title"):
        warnings.append("no title found in header block")
    if not divisions:
        warnings.append("no chapter/volume divisions detected")
    if not pages:
        warnings.append("no original page-number markers detected")

    year = None
    year_str = (
        header_fields.get("publication_date")
        or header_fields.get("publication_data")  # observed typo in some files
        or header_fields.get("date_of_publication")
        or header_fields.get("year")
    )
    if year_str:
        m = re.search(r"\d{4}", year_str)
        if m:
            year = int(m.group())

    return ParsedNovel(
        filename=path.name,
        title=header_fields.get("title"),
        author=header_fields.get("author"),
        author_gender=header_fields.get("gender") or header_fields.get("author_gender"),
        year=year,
        source=header_fields.get("source"),
        cleaned_text=cleaned_text,
        word_count=word_count,
        divisions=divisions,
        pages=pages,
        sentences=sentences,
        warnings=warnings,
    )
