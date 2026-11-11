"""
Publication-quality static exports of the Phase 3 views (SOW: "export to
publication-quality static figures (SVG/PDF)").

    python -m src.export_figures                      # the 5 test novels
    python -m src.export_figures --novel 1862.txt --novel 1892.txt
    python -m src.export_figures --all                # every analyzed novel

Writes reports/figures/phase3/<stem>_timeline.{svg,pdf,png}. Rendering uses
Kaleido, which drives a local Chrome install.
"""
import argparse

from . import config
from .analyze_temporal import TEST_SLICE
from .viz import data, timeline

OUT = config.ROOT / "reports" / "figures" / "phase3"
SIZE = dict(width=1400, height=460)


def export(conn, filename: str, formats=("svg", "pdf", "png")) -> list:
    fig = timeline.build_timeline(data.load_timeline(conn, filename))
    stem = filename.removesuffix(".txt")
    paths = []
    for fmt in formats:
        path = OUT / f"{stem}_timeline.{fmt}"
        fig.write_image(path, **SIZE, scale=2 if fmt == "png" else 1)
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description="Export Phase 3 figures (SVG/PDF/PNG)")
    parser.add_argument("--novel", action="append", help="filename, e.g. 1847.txt (repeatable)")
    parser.add_argument("--all", action="store_true", help="every analyzed novel")
    args = parser.parse_args()

    conn = data.connect()
    novels = ([n["filename"] for n in data.list_novels(conn)] if args.all
              else args.novel or TEST_SLICE)
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in novels:
        export(conn, fn)
        print(f"  {fn}: timeline svg, pdf, png")
    print(f"wrote {len(novels)} novel(s) to {OUT}")


if __name__ == "__main__":
    main()
