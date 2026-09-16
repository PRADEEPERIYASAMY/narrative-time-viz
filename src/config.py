"""
Central configuration for the Phase 1 corpus pipeline.

The regex patterns below were validated against real downloaded files
(decades 1800-1809, 1850-1859, 1890-1899 sampled) -- NOT the TEI-lite
div/pb convention assumed in the original best-guess version. Real HUM19UK
.txt files use their own bracket-tag dialect:
    <Title: ...>            (header block, one field per line, wrapped in <>)
    <Author: ...>
    <Publication date: ...> (also seen: "Date of publication", "Publication data" [typo])
    <Page numbers: yes|no>
    <Source: ...>
    <text> ... </text>      (hard content boundary -- see below)
    <div title="VOL. I.">   (volume/part division; sometimes `<div="...">`, no "title" keyword)
    <chapter title="...">   (chapter division, closed by </chapter>)
    <3>  or  <Page 3 >      (page-break marker; bare-number vs "Page N" form
                              correlates with Source -- Chawton House Collection
                              uses bare numbers, public-library-UK uses "Page N")

<text>/</text> reliably bound the actual novel body in every sampled file
(1 occurrence each) and matter in practice: at least one Project Gutenberg-
sourced file (Dracula, 1897) has an OCR errata list appended *after*
</text> that must NOT be treated as narrative content.

No per-novel "Gender" field was found in any sampled header -- HUM19UK
records author gender in the separate "Description of Contents Corpus.zip"
PDF, not inline. author_gender will legitimately be None from this parser;
that's not a bug.
"""
import re
from pathlib import Path

# --- paths -------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
DB_PATH = ROOT / "data" / "processed" / "corpus.db"

# --- corpus source (verified against the live Uppsala page, 2026-09) ---
# The URL in the original scope-of-work doc (linguisticsathuddersfield.com)
# no longer serves the files. The corpus is now mirrored decade-by-decade
# at Uppsala University's English Dept. site:
DECADE_ZIPS = {
    "1800-1809": "https://www.uu.se/download/18.547e7b518eeffced3d76c6/1713518082927/1800-1809.zip",
    "1810-1819": "https://www.uu.se/download/18.547e7b518eeffced3d76c7/1713518092145/1810-1819.zip",
    "1820-1829": "https://www.uu.se/download/18.547e7b518eeffced3d76c8/1713518092339/1820-1829.zip",
    "1830-1839": "https://www.uu.se/download/18.547e7b518eeffced3d76c9/1713518092474/1830-1839.zip",
    "1840-1849": "https://www.uu.se/download/18.547e7b518eeffced3d76ca/1713518092650/1840-1849.zip",
    "1850-1859": "https://www.uu.se/download/18.547e7b518eeffced3d76cb/1713518092845/1850-1859.zip",
    "1860-1869": "https://www.uu.se/download/18.547e7b518eeffced3d76cc/1713518093016/1860-1869.zip",
    "1870-1879": "https://www.uu.se/download/18.547e7b518eeffced3d76cd/1713518093274/1870-1879.zip",
    "1880-1889": "https://www.uu.se/download/18.547e7b518eeffced3d76ce/1713518093520/1880-1889.zip",
    "1890-1899": "https://www.uu.se/download/18.547e7b518eeffced3d76cf/1713518093675/1890-1899.zip",
}
DESCRIPTION_ZIP = "https://www.uu.se/download/18.547e7b518eeffced3d76c5/1713518064184/Description%20of%20Contents%20Corpus.zip"

# --- content boundary (compiler-added <text>...</text> wrapper) --------
# Everything before <text> is the header block; everything after </text>
# (e.g. Gutenberg-derived errata/corrections lists) is discarded.
TEXT_START_PATTERN = re.compile(r"<text>", re.IGNORECASE)
TEXT_END_PATTERN = re.compile(r"</text>", re.IGNORECASE)

# --- header parsing (compiler-added small metadata block) --------------
# Documented fields: novel title; author's name; year of first publication;
# source of the machine-readable text. (No per-novel gender field exists in
# the header -- see module docstring.) Field-name spelling is inconsistent
# across files ("Publication date" / "Date of publication" / "Publication
# data" [typo], case varies), hence the alternation below.
HEADER_FIELD_PATTERN = re.compile(
    r'^\s*<?\s*(Title|Author[ _]Gender|Author|Gender'
    r'|Date[ _]of[ _]publication|Publication[ _](?:date|data)'
    r'|Page[ _]Numbers|Source)\s*:\s*(.+?)\s*>?\s*$',
    re.IGNORECASE | re.MULTILINE,
)
HEADER_MAX_LINES = 15  # fallback scan depth if no <text> marker is found

# --- division tags (volume / chapter / part) ----------------------------
# Real convention: <div title="VOL. I."> ... </div> for volumes/parts
# (occasionally missing the "title" keyword: <div="PART TWO">), and
# <chapter title="..."> ... </chapter> for chapters. No type/n attributes.
# Division number is pulled from the title text itself (roman numeral or
# digits), best-effort.
DIVISION_TAG_PATTERN = re.compile(
    r'<div(?:\s+title)?\s*="(?P<div_title>[^"]*)"[^>]*>'
    r'|<chapter\s+title="(?P<chap_title>[^"]*)"[^>]*>',
    re.IGNORECASE,
)
DIVISION_NUMBER_PATTERN = re.compile(r"\b([IVXLCDM]+|\d+)\b", re.IGNORECASE)
# Fallback hypothesis: plain-text markers on their own line, no tags at all.
DIVISION_PLAIN_PATTERN = re.compile(
    r'^\s*(VOLUME|BOOK|PART)\s+([IVXLCDM]+|\d+)\s*\.?\s*$'
    r'|^\s*CHAPTER\s+([IVXLCDM]+|\d+)\s*\.?\s*(.*)$',
    re.IGNORECASE | re.MULTILINE,
)

# --- page tags -----------------------------------------------------------
# Real convention: a bare number in brackets (<3>) when Source is "Chawton
# House Collection online", or "<Page N >" (note trailing space) when
# Source is "public-library-UK". Malformed page-numberless tags ("<Page >")
# exist in the wild and are intentionally left unmatched -- there's no
# number to record.
PAGE_TAG_PATTERN = re.compile(r'<(?:Page\s+)?(\d+)\s*>', re.IGNORECASE)

# --- residual boilerplate (defensive; corpus is pre-cleaned but some
# source texts were pulled from Project Gutenberg) -----------------------
GUTENBERG_START = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.IGNORECASE | re.DOTALL)
GUTENBERG_END = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG.*", re.IGNORECASE | re.DOTALL)

MIN_NOVEL_WORDS = 500  # sanity floor; flags obviously-truncated/corrupt files
