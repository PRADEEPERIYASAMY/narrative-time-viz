"""
Unit tests using synthetic sample text that mimics HUM19UK's REAL, verified
file format: a bracketed header block, a <text>...</text> content boundary,
<div title="..."> / <chapter title="..."> divisions, and page markers
(bare <N>, the "Chawton House Collection online" convention this fixture
uses). Confirmed against real downloaded files from the 1800-1809,
1850-1859 and 1890-1899 decade zips -- see config.py's module docstring
for the format notes and corpus-quirk caveats (no per-novel Gender field,
"Publication date"/"Date of publication"/"Publication data" [typo]
variance, "<Page N >" as an alternate page-tag form, etc).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.preprocess import parse_novel  # noqa: E402

SAMPLE_REAL_FORMAT = """<Title: The Sample Governess>
<Author: Jane Doe>
<Publication date: 1847>
<Page numbers: yes>
<Source: Chawton House Collection online>
<text>
<div title="VOL. I.">
<chapter title="Chapter I">
<1>It was a dark and stormy night. The governess arrived at the manor.
She had never seen such a house before. It loomed over the drive like a threat.

<2>The butler greeted her at the door. "You are expected," he said.
She nodded and stepped inside, her heart pounding.
</chapter>
<chapter title="Chapter II">
<3>Three years later, she remembered that first night vividly.
It had changed everything about her life.
</chapter>
</div>
</text>
"""

SAMPLE_PLAIN_STYLE = """Title: A Plainer Tale
Author: John Roe
Gender: male
Year: 1862

VOLUME I

CHAPTER I

It was the best of mornings. The sun rose over the quiet village.
Everyone in town knew everyone else's business.

CHAPTER II

Later that year, the harvest failed. The village struggled through winter.
"""


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_header_parsed(tmp_path):
    path = _write(tmp_path, "sample_real.txt", SAMPLE_REAL_FORMAT)
    novel = parse_novel(path)
    assert novel.title == "The Sample Governess"
    assert novel.author == "Jane Doe"
    # real HUM19UK headers carry no per-novel Gender field (see module docstring)
    assert novel.author_gender is None
    assert novel.year == 1847


def test_divisions_and_pages_detected(tmp_path):
    path = _write(tmp_path, "sample_real.txt", SAMPLE_REAL_FORMAT)
    novel = parse_novel(path)
    assert len(novel.divisions) == 3  # 1 volume + 2 chapters
    assert any(d.division_type == "volume" for d in novel.divisions)
    assert len(novel.pages) == 3
    # the fixture is intentionally tiny (well under MIN_NOVEL_WORDS), so the
    # only expected warning is the short-novel one -- structure is otherwise clean
    assert len(novel.warnings) == 1
    assert "suspiciously short" in novel.warnings[0]


def test_tags_removed_from_cleaned_text(tmp_path):
    path = _write(tmp_path, "sample_real.txt", SAMPLE_REAL_FORMAT)
    novel = parse_novel(path)
    assert "<div" not in novel.cleaned_text
    assert "<chapter" not in novel.cleaned_text
    assert "<text>" not in novel.cleaned_text
    assert "It was a dark and stormy night" in novel.cleaned_text


def test_plain_text_fallback_divisions(tmp_path):
    path = _write(tmp_path, "sample_plain.txt", SAMPLE_PLAIN_STYLE)
    novel = parse_novel(path)
    assert len(novel.divisions) == 3  # VOLUME I + CHAPTER I + CHAPTER II
    assert "no original page-number markers detected" in novel.warnings


def test_sentence_segmentation(tmp_path):
    path = _write(tmp_path, "sample_real.txt", SAMPLE_REAL_FORMAT)
    novel = parse_novel(path)
    assert len(novel.sentences) >= 6
    assert novel.sentences[0].text.startswith("It was a dark and stormy night")


def test_sentences_linked_to_nearest_page_and_division(tmp_path):
    import src.db as db
    conn = db.get_connection(db_path=tmp_path / "test.db")
    path = _write(tmp_path, "sample_real.txt", SAMPLE_REAL_FORMAT)
    novel = parse_novel(path)
    novel_id = db.insert_novel(conn, novel, decade="1840-1849")

    rows = conn.execute(
        "SELECT s.text, p.page_number, d.division_type, d.division_number "
        "FROM sentences s "
        "LEFT JOIN pages p ON p.id = s.page_id "
        "LEFT JOIN divisions d ON d.id = s.division_id "
        "WHERE s.novel_id = ? ORDER BY s.sentence_index",
        (novel_id,),
    ).fetchall()

    assert rows, "no sentences inserted"
    first_page_numbers = {r[1] for r in rows}
    assert "1" in first_page_numbers
    assert "3" in first_page_numbers  # "Three years later" sentence -> page 3
    conn.close()


def test_short_file_flagged(tmp_path):
    path = _write(tmp_path, "tiny.txt", "Title: Tiny\nAuthor: X\nYear: 1810\n\nA short text.")
    novel = parse_novel(path)
    assert any("suspiciously short" in w for w in novel.warnings)
