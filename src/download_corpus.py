"""
Download and extract the HUM19UK corpus from Uppsala University's mirror.

Run this on a machine with normal internet access (this repo's dev sandbox
cannot reach uu.se). Usage:

    python -m src.download_corpus              # fetch everything
    python -m src.download_corpus --decade 1840-1849   # just one decade
"""
import argparse
import io
import sys
import zipfile
from pathlib import Path

import requests

from . import config


def _download_zip(url: str, dest_dir: Path) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    extracted = []
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            zf.extract(name, dest_dir)
            extracted.append(dest_dir / name)
    return extracted


def main():
    parser = argparse.ArgumentParser(description="Download HUM19UK corpus")
    parser.add_argument("--decade", default=None, help="e.g. 1840-1849; default = all")
    parser.add_argument("--with-description", action="store_true",
                         help="also fetch the 'Description of Contents' zip")
    args = parser.parse_args()

    decades = [args.decade] if args.decade else list(config.DECADE_ZIPS)
    total_files = 0
    for decade in decades:
        if decade not in config.DECADE_ZIPS:
            print(f"unknown decade {decade!r}; choices: {list(config.DECADE_ZIPS)}", file=sys.stderr)
            sys.exit(1)
        url = config.DECADE_ZIPS[decade]
        dest = config.RAW_DIR / decade
        print(f"[download] {decade} <- {url}")
        files = _download_zip(url, dest)
        print(f"  extracted {len(files)} file(s) -> {dest}")
        total_files += len(files)

    if args.with_description:
        print("[download] Description of Contents")
        _download_zip(config.DESCRIPTION_ZIP, config.RAW_DIR / "_description")

    print(f"done. {total_files} file(s) across {len(decades)} decade(s) in {config.RAW_DIR}")


if __name__ == "__main__":
    main()
