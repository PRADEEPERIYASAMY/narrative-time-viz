"""
Calibration tool: run this on a few real downloaded files BEFORE trusting
preprocess.py on the full corpus. It shows you the raw head/tail of a file
and reports how many times each config.py pattern matches, so you can tell
immediately whether the header/division/page regexes need adjusting.

Usage:
    python -m src.inspect_corpus data/raw/1840-1849/SomeNovel.txt
    python -m src.inspect_corpus data/raw/1840-1849/*.txt   # several at once
"""
import sys
from pathlib import Path

from . import config
from .preprocess import _normalize_encoding

# stdout may be a Windows console using a legacy codepage (e.g. cp1252) that
# can't represent every character real corpus files contain; degrade to '?'
# rather than crashing the calibration run.
sys.stdout.reconfigure(errors="replace")


def inspect(path: Path):
    # decode exactly the way preprocess.py will, so what's printed here is
    # what the real pipeline actually sees (not utf-8-with-replace, which
    # papers over encoding issues the real pipeline's latin-1 fallback avoids).
    text = _normalize_encoding(path.read_bytes())
    print("=" * 70)
    print(path)
    print("-" * 70)
    print("HEAD (first 600 chars):")
    print(text[:600])
    print("-" * 70)
    print("TAIL (last 400 chars):")
    print(text[-400:])
    print("-" * 70)

    header_matches = config.HEADER_FIELD_PATTERN.findall(text[:2000])
    div_tag_matches = config.DIVISION_TAG_PATTERN.findall(text)
    div_plain_matches = config.DIVISION_PLAIN_PATTERN.findall(text)
    page_matches = config.PAGE_TAG_PATTERN.findall(text)

    print(f"header fields matched:     {header_matches}")
    print(f"division TAG matches:      {len(div_tag_matches)}")
    print(f"division PLAIN-TEXT matches: {len(div_plain_matches)}")
    print(f"page tag matches:          {len(page_matches)}")
    if not header_matches:
        print("  !! no header fields found -- inspect HEAD above and update "
              "HEADER_FIELD_PATTERN in config.py")
    if not div_tag_matches and not div_plain_matches:
        print("  !! no chapter/volume divisions found -- inspect the file "
              "for the real marker style and update DIVISION_* patterns")
    if not page_matches:
        print("  !! no page markers found -- inspect the file for the real "
              "page-break style and update PAGE_TAG_PATTERN")
    print()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for arg in sys.argv[1:]:
        inspect(Path(arg))


if __name__ == "__main__":
    main()
