"""
Publication-quality static exports of the Phase 3 views (SOW: "export to
publication-quality static figures (SVG/PDF)"; "publication-quality figures
for 5+ novels").

    python -m src.export_figures                      # the publication set (9 novels)
    python -m src.export_figures --novel 1862.txt --novel 1892.txt
    python -m src.export_figures --all                # every analyzed novel

Writes reports/figures/phase3/<stem>_{timeline,pace,flashbacks}.{svg,pdf,png}.
Rendering uses Kaleido, which drives a local Chrome or Edge.
"""
import argparse

from . import config
from .analyze_temporal import TEST_SLICE
from .viz import data, flashback_map, pace, timeline

OUT = config.ROOT / "reports" / "figures" / "phase3"

# the 5 Phase 2 test novels plus four that carry this project's findings:
# Lady Audley's confession (the timeline's analepsis), Pooter's diary (dates
# and clock time), Broughton's present tense, and Vernon Lee's "suddenly"
PUBLICATION_SET = TEST_SLICE + ["1862.txt", "1892.txt", "1870.txt", "1886.txt"]

VIEWS = {
    "timeline": (lambda c, fn: timeline.build_timeline(data.load_timeline(c, fn)), dict(width=1400, height=460)),
    "pace": (lambda c, fn: pace.build_pace(data.load_pace(c, fn)), dict(width=1400, height=600)),
    "flashbacks": (lambda c, fn: flashback_map.build_flashback_map(data.load_flashback_map(c, fn)),
                   dict(width=1400, height=600)),
}


def export(conn, filename: str, formats=("svg", "pdf", "png"), views=tuple(VIEWS)) -> list:
    stem = filename.removesuffix(".txt")
    paths = []
    for view in views:
        build, size = VIEWS[view]
        fig = build(conn, filename)
        for fmt in formats:
            path = OUT / f"{stem}_{view}.{fmt}"
            fig.write_image(path, **size, scale=2 if fmt == "png" else 1)
            paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description="Export Phase 3 figures (SVG/PDF/PNG)")
    parser.add_argument("--novel", action="append", help="filename, e.g. 1847.txt (repeatable)")
    parser.add_argument("--all", action="store_true", help="every analyzed novel")
    args = parser.parse_args()

    conn = data.connect()
    novels = ([n["filename"] for n in data.list_novels(conn)] if args.all
              else args.novel or PUBLICATION_SET)
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in novels:
        export(conn, fn)
        print(f"  {fn}: timeline, pace, flashback map (svg, pdf, png)")
    print(f"wrote {len(novels)} novel(s) to {OUT}")


if __name__ == "__main__":
    main()
