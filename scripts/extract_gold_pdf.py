"""Extract the document-level Achva gold set from an annotated PDF (R3, BUILD_PLAN v0.3 §3).

Reads PDF `/Highlight` annotations (QuadPoints + RGB), maps each highlight's color to a
label via the `Legend.txt` color legend (nearest-anchor in RGB space), and fuzzy-matches
each highlight's extracted text into the paper's plain-text fulltext to recover exact
character offsets. Double-marked highlights (the same span highlighted more than once)
are deduped; highlights that cover the same span under different labels are merged into
one gold span carrying a `labels` list.

Usage:
    python scripts/extract_gold_pdf.py --pdf <annotated.pdf> --legend <Legend.txt> \\
        --out data/gold/achva/doc_gold.json

Requires `pymupdf`, imported lazily so it is never a runtime dependency of the
`inclusify_agent` package. Install it with:

    uv pip install pymupdf --python .venv/bin/python
    # or: pip install -e ".[gold]"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from bisect import bisect_left
from pathlib import Path
from typing import Any

# Canonical RGB anchors per basic color name. Real highlight colors are semi-transparent
# pastels, not these exact values — nearest-anchor only needs the 5 legend colors to be
# mutually discriminative, not pixel-perfect (verified against the actual gold PDF).
_COLOR_RGB: dict[str, tuple[float, float, float]] = {
    "ירוק": (0.49, 0.94, 0.40),  # green
    "צהוב": (0.98, 0.90, 0.30),  # yellow
    "ורוד": (0.98, 0.60, 0.80),  # pink
    "אדום": (0.95, 0.20, 0.20),  # red
    "כחול": (0.30, 0.55, 0.95),  # blue
}

_Y_TOLERANCE = 5.0  # points; highlights within this + same page/text = one double-marked span


def _slugify(label: str) -> str:
    return label.strip().lower().replace(" ", "-")


def load_legend(path: Path) -> dict[str, tuple[float, float, float]]:
    """Parse `Legend.txt` (`'<label> - <hebrew color name>'` per line) into
    `{label_slug: rgb_anchor}`."""
    anchors: dict[str, tuple[float, float, float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or " - " not in line:
            continue
        label, color_name = (part.strip() for part in line.split(" - ", 1))
        rgb = _COLOR_RGB.get(color_name)
        if rgb is None:
            continue
        anchors[_slugify(label)] = rgb
    return anchors


def _nearest_label(
    rgb: tuple[float, float, float], anchors: dict[str, tuple[float, float, float]],
) -> str:
    def _dist(name: str) -> float:
        return sum((a - b) ** 2 for a, b in zip(anchors[name], rgb, strict=True))
    return min(anchors, key=_dist)


def _normalize_for_match(s: str) -> tuple[str, list[int]]:
    """Collapse whitespace runs to a single space, and merge a hyphen line-break
    artifact ('word-\\ncont' -> 'word-cont', dropping the space) so a highlight's
    text matches the fulltext regardless of which side kept the space.

    Returns (normalized_text, index_map) where index_map[i] is the original index in
    `s` of normalized_text[i] — used to map a match on the normalized text back to
    real character offsets.
    """
    out: list[str] = []
    idx_map: list[int] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            j = i
            while j < n and s[j].isspace():
                j += 1
            if out and out[-1] == "-":
                i = j  # drop the space entirely: "same-" + "\n" + "gender" -> "same-gender"
                continue
            out.append(" ")
            idx_map.append(i)
            i = j
            continue
        out.append(c)
        idx_map.append(i)
        i += 1
    return "".join(out), idx_map


def _strip_trailing_clipped_letter(text: str) -> str | None:
    """A quad-rect text grab sometimes clips a trailing word to one letter
    (e.g. 'gender-atypical f'). Drop it so the shortened query can still match.

    ponytail: trailing-clip only, no leading-clip fallback (e.g. 'at meets t
    lesbians,' clipped from '...that meets the... lesbians,'). Clears the 90%
    match bar as-is (94/97 on the real gold PDF); add a leading-clip strip (or a
    real bbox->text-offset mapper) only if a future gold PDF needs full closure.
    """
    parts = text.rsplit(" ", 1)
    if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha():
        return parts[0]
    return None


def _find_offset(
    query: str, norm_full: str, idx_map: list[int], *, start: int, end: int,
) -> tuple[int, int, int] | None:
    """Search `norm_full[start:end]` for normalized `query`.

    Returns (orig_char_start, orig_char_end, norm_match_end) or None.
    """
    norm_query, _ = _normalize_for_match(query)
    norm_query = norm_query.strip()
    if not norm_query:
        return None
    pos = norm_full.find(norm_query, start, end)
    if pos == -1:
        return None
    match_end = pos + len(norm_query)
    return idx_map[pos], idx_map[match_end - 1] + 1, match_end


def _extract_highlights(
    doc: Any, anchors: dict[str, tuple[float, float, float]],
) -> list[dict[str, Any]]:
    """One row per `/Highlight` annotation: page, nearest-anchor label, joined quad
    text, and the top quad's y (for sequential same-page ordering)."""
    import fitz  # PyMuPDF — see the helpful ImportError in main()

    rows: list[dict[str, Any]] = []
    for pno, page in enumerate(doc, start=1):
        for annot in page.annots(types=[fitz.PDF_ANNOT_HIGHLIGHT]) or []:
            colors = annot.colors or {}
            stroke_or_fill = colors.get("stroke") or colors.get("fill") or (0, 0, 0)
            rgb = tuple(round(x, 3) for x in stroke_or_fill)
            quads = annot.vertices or []
            parts = []
            for i in range(0, len(quads), 4):
                rect = fitz.Quad(quads[i:i + 4]).rect
                rect += (-1, -1, 1, 1)  # tolerance
                parts.append(page.get_textbox(rect).strip())
            text = " ".join(" ".join(parts).split())
            if not text:
                continue
            rows.append({
                "page": pno,
                "label": _nearest_label(rgb, anchors),
                "text": text,
                "y": round(fitz.Quad(quads[0:4]).rect.y0, 1),
            })
    rows.sort(key=lambda r: (r["page"], r["y"]))
    return rows


def _extract_fulltext(doc: Any) -> tuple[str, list[int]]:
    """Fulltext = page texts joined by a blank line; also return each page's start
    offset in that joined string (1-indexed page N starts at page_offsets[N-1])."""
    page_texts = [page.get_text() for page in doc]
    fulltext = "\n\n".join(page_texts)
    offsets = []
    cursor = 0
    for t in page_texts:
        offsets.append(cursor)
        cursor += len(t) + 2  # + the "\n\n" separator
    return fulltext, offsets


def _group_and_match(
    rows: list[dict[str, Any]], fulltext: str, page_offsets: list[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Dedupe double-marked highlights and merge same-span different-label ones,
    then fuzzy-match each resulting group's text into `fulltext` for char offsets.

    Rows arrive sorted by (page, y): a double-marked highlight is always the very
    next row with the same page/text within `_Y_TOLERANCE` points, so only the
    previous group needs checking, not the whole accumulated list.
    """
    norm_full, idx_map = _normalize_for_match(fulltext)
    raw_bounds = [*page_offsets, len(fulltext)]
    norm_bounds = [bisect_left(idx_map, b) for b in raw_bounds]

    groups: list[dict[str, Any]] = []
    cursor_by_page: dict[int, int] = {}
    matched = 0
    unmatched: list[str] = []

    for row in rows:
        page, text, y, label = row["page"], row["text"], row["y"], row["label"]
        prev = groups[-1] if groups else None
        if (prev is not None and prev["page"] == page and prev["text"] == text
                and abs(prev["y"] - y) <= _Y_TOLERANCE):
            prev["labels"].add(label)
            group = prev
        else:
            norm_start = norm_bounds[page - 1]
            norm_end = norm_bounds[page]
            cursor = cursor_by_page.get(page, norm_start)

            found = _find_offset(text, norm_full, idx_map, start=cursor, end=norm_end)
            if found is None:
                found = _find_offset(text, norm_full, idx_map, start=norm_start, end=norm_end)
            if found is None:
                stripped = _strip_trailing_clipped_letter(text)
                if stripped:
                    found = _find_offset(stripped, norm_full, idx_map, start=cursor, end=norm_end)
                    if found is None:
                        found = _find_offset(
                            stripped, norm_full, idx_map, start=norm_start, end=norm_end,
                        )

            group = {"page": page, "text": text, "y": y, "labels": {label}, "found": found}
            groups.append(group)
            if found is not None:
                cursor_by_page[page] = found[2]

        if group["found"] is not None:
            matched += 1
        else:
            unmatched.append(text)

    spans = []
    for g in groups:
        if g["found"] is None:
            continue
        start, end, _ = g["found"]
        spans.append({
            "char_start": start,
            "char_end": end,
            "labels": sorted(g["labels"]),
            "page": g["page"],
            "text": fulltext[start:end],
        })
    return spans, {"matched": matched, "unmatched": unmatched}


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def extract(pdf_path: Path, legend_path: Path) -> dict[str, Any]:
    try:
        import fitz  # PyMuPDF — lazy import: never a package runtime dependency
    except ImportError as exc:
        raise SystemExit(
            "pymupdf is required to run this script (not a package runtime dependency). "
            "Install it with: uv pip install pymupdf --python .venv/bin/python "
            "(or: pip install -e '.[gold]')"
        ) from exc

    anchors = load_legend(legend_path)
    doc = fitz.open(pdf_path)
    rows = _extract_highlights(doc, anchors)
    fulltext, page_offsets = _extract_fulltext(doc)
    spans, match_report = _group_and_match(rows, fulltext, page_offsets)

    return {
        "source_pdf": str(pdf_path),
        "extracted_at_sha": _git_sha(),
        "fulltext": fulltext,
        "spans": spans,
        "match_report": match_report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extract_gold_pdf", description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path, help="Annotated gold PDF.")
    parser.add_argument("--legend", required=True, type=Path, help="Legend.txt color legend.")
    parser.add_argument("--out", required=True, type=Path, help="Output doc_gold.json path.")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    result = extract(args.pdf, args.legend)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    report = result["match_report"]
    total = report["matched"] + len(report["unmatched"])
    rate = report["matched"] / total if total else 1.0
    by_label: dict[str, int] = {}
    for span in result["spans"]:
        for label in span["labels"]:
            by_label[label] = by_label.get(label, 0) + 1

    print(f"matched {report['matched']}/{total} highlights ({rate:.1%})")
    if report["unmatched"]:
        print(f"unmatched ({len(report['unmatched'])}):")
        for t in report["unmatched"]:
            print(f"  - {t!r}")
    print(f"gold spans written: {len(result['spans'])} -> {args.out}")
    print(f"spans by label: {by_label}")

    if rate < 0.90:
        print(f"FAIL: match rate {rate:.1%} is below the 90% bar", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
