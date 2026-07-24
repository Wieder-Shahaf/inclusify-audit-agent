"""Generate the v2 architecture diagram PNG served by GET /api/model_architecture.

Run: python scripts/gen_architecture.py
Writes: src/inclusify_agent/static/architecture.png (committed; Docker/Vercel just serve it).

Fixed pixel layout (no timestamps, no randomness) so the PNG is byte-for-byte
reproducible across runs. The three LLM module names are pulled straight from
MODULE_BY_TASK so this diagram can never drift from the `steps[].module` log
(assignment §C: names must be consistent across diagram / steps / agent_info).

ponytail: Pillow box-drawing, same renderer the v1 diagram already used (pyproject's
[dev] extra already carries Pillow; nothing new to install). One PNG, regenerated
only when the pipeline shape changes.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from inclusify_agent.server.recording_llm import MODULE_BY_TASK  # noqa: E402

DOCUMENT_AUDITOR = MODULE_BY_TASK["audit"]
EVIDENCE_INVESTIGATOR = MODULE_BY_TASK["investigate"]
REPORT_CONSOLIDATOR = MODULE_BY_TASK["consolidate"]

# ---- canvas + palette (spec: landscape ~1500x950, white bg) -----------------------------------
BG = (255, 255, 255)
INK = (28, 32, 38)
MUTED = (105, 111, 120)
LINE = (105, 111, 120)

GREY_FILL, GREY_BORDER = (231, 235, 240), (91, 107, 124)      # deterministic code
AMBER_FILL, AMBER_BORDER = (245, 217, 168), (122, 78, 16)     # LLM call
VIOLET_FILL, VIOLET_BORDER = (217, 204, 242), (94, 67, 165)   # vector retrieval
RUST_FILL, RUST_BORDER = (239, 201, 184), (140, 59, 27)       # live API, env-gated

PAD = 40
COL_W = 220
# Gap AFTER column i. Most inter-column arrows carry no label and sit fine in a tight
# 20px gap; the two that DO carry an inline label ("windows + hints" after col 1,
# "candidates (fan-out)" after col 2) need a gap wide enough for that label's text to
# clear both neighboring boxes entirely, not just float on top of them. This pushes
# the canvas a bit past the spec's approximate "~1500" width -- legible labels over a
# nominally-exact width (see module docstring / PR notes for the tradeoff).
COL_GAPS = [20, 130, 170, 20, 20]


def _col_edges() -> list[tuple[int, int]]:
    edges = []
    x = PAD
    for i in range(len(COL_GAPS) + 1):
        edges.append((x, x + COL_W))
        x += COL_W + (COL_GAPS[i] if i < len(COL_GAPS) else 0)
    return edges


_COLS = _col_edges()


def _col_x(i: int) -> tuple[int, int]:
    return _COLS[i]


W, H = _COLS[-1][1] + PAD, 950

# Pillow's ImageDraw has no anti-aliasing for shapes/lines/rounded corners -- every
# diagonal arrow and rounded box would render visibly jagged at 1x. Standard fix:
# rasterize everything at SS times the target resolution, then downsample with a
# LANCZOS filter (a real low-pass filter, i.e. free anti-aliasing) before saving.
# `_ScaledDraw` below multiplies every coordinate/width by SS transparently, so all
# the layout code above and below keeps working in plain "logical" 1x pixels.
SS = 4


def _vstack(x0: int, x1: int, y_center: float, heights: list[int], gaps: list[int]) -> list[tuple]:
    """Boxes of the given heights, stacked with the given gaps between them,
    vertically centered as a group on `y_center`. Pure arithmetic -- deterministic,
    no hand-picked absolute y's to keep in sync when a height changes."""
    total = sum(heights) + sum(gaps)
    y = y_center - total / 2
    boxes = []
    for i, h in enumerate(heights):
        boxes.append((x0, y, x1, y + h))
        y += h
        if i < len(gaps):
            y += gaps[i]
    return boxes


def _font(size: int, bold: bool = False):
    """Requested size is in LOGICAL px; the actual glyph is rasterized at SS times
    that (matching the supersampled canvas) so downsampling anti-aliases text too."""
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size * SS)
            except OSError:
                pass
    return ImageFont.load_default()


class _ScaledDraw:
    """Wraps an `ImageDraw.Draw`, multiplying every coordinate/width by SS so the
    rest of the script can keep laying things out in plain logical pixels while
    everything actually rasterizes at SS times the resolution (see SS's docstring
    above). `textbbox` is the mirror image: scale the query point up, then divide
    the measured box back down, so the caller's logical-space wrap/center math
    (already written and visually verified against the 1x layout) needs no changes."""

    def __init__(self, draw, scale: int) -> None:
        self._d = draw
        self._s = scale

    def _pt(self, xy):
        return tuple(c * self._s for c in xy)

    def _pts(self, points):
        return [self._pt(p) for p in points]

    def rounded_rectangle(self, box, *, radius=0, **kw):
        if "width" in kw:
            kw["width"] = max(1, round(kw["width"] * self._s))
        self._d.rounded_rectangle(self._pt(box), radius=radius * self._s, **kw)

    def rectangle(self, box, **kw):
        if "width" in kw:
            kw["width"] = max(1, round(kw["width"] * self._s))
        self._d.rectangle(self._pt(box), **kw)

    def line(self, points, **kw):
        if "width" in kw:
            kw["width"] = max(1, round(kw["width"] * self._s))
        self._d.line(self._pts(points), **kw)

    def text(self, xy, text, **kw):
        self._d.text(self._pt(xy), text, **kw)

    def textbbox(self, xy, text, **kw):
        x0, y0, x1, y1 = self._d.textbbox(self._pt(xy), text, **kw)
        s = self._s
        return (x0 / s, y0 / s, x1 / s, y1 / s)


def _line_h(draw, font) -> float:
    tb = draw.textbbox((0, 0), "Agy", font=font)
    return (tb[3] - tb[1]) + 5


def _wrap(draw, text: str, font, max_width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _center_text(draw, cx: float, y: float, text: str, font, fill) -> None:
    tb = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (tb[2] - tb[0]) / 2, y), text, font=font, fill=fill)


def _dashed_line(draw, p, q, *, color, width=2, dash=9, gap=6) -> None:
    length = math.hypot(q[0] - p[0], q[1] - p[1])
    if length == 0:
        return
    n = max(1, int(length // (dash + gap)) + 1)
    for i in range(n):
        t0 = (i * (dash + gap)) / length
        if t0 >= 1.0:
            break
        t1 = min(1.0, t0 + dash / length)
        p0 = (p[0] + (q[0] - p[0]) * t0, p[1] + (q[1] - p[1]) * t0)
        p1 = (p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1)
        draw.line([p0, p1], fill=color, width=width)


def _dashed_rect_border(draw, box, *, color, width=2) -> None:
    """Approximate a dashed rounded-rect border with dashed straight edges --
    close enough for the small radius used here, and far simpler than dashing
    along an actual arc."""
    x0, y0, x1, y1 = box
    r = 14
    _dashed_line(draw, (x0 + r, y0), (x1 - r, y0), color=color, width=width)
    _dashed_line(draw, (x1, y0 + r), (x1, y1 - r), color=color, width=width)
    _dashed_line(draw, (x1 - r, y1), (x0 + r, y1), color=color, width=width)
    _dashed_line(draw, (x0, y1 - r), (x0, y0 + r), color=color, width=width)


def _box(draw, box, *, fill, border, dashed=False, width=2) -> None:
    if dashed:
        draw.rounded_rectangle(box, radius=14, fill=fill)
        _dashed_rect_border(draw, box, color=border, width=width)
    else:
        draw.rounded_rectangle(box, radius=14, fill=fill, outline=border, width=width)


def _box_label(draw, box, name, sub, *, f_name, f_sub, name_fill=INK, sub_fill=None) -> None:
    x0, y0, x1, y1 = box
    cx, inner_w = (x0 + x1) / 2, (x1 - x0) - 20
    sub_fill = sub_fill or MUTED
    name_lines = _wrap(draw, name, f_name, inner_w)
    sub_lines = _wrap(draw, sub, f_sub, inner_w) if sub else []
    lh_name, lh_sub = _line_h(draw, f_name), _line_h(draw, f_sub)
    total_h = len(name_lines) * lh_name + (6 if sub_lines else 0) + len(sub_lines) * lh_sub
    y = (y0 + y1) / 2 - total_h / 2
    for line in name_lines:
        _center_text(draw, cx, y, line, f_name, name_fill)
        y += lh_name
    if sub_lines:
        y += 6
        for line in sub_lines:
            _center_text(draw, cx, y, line, f_sub, sub_fill)
            y += lh_sub


def _arrowhead(draw, p, q, *, color, width) -> None:
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    for da in (2.6, -2.6):
        draw.line([q, (q[0] + 12 * math.cos(ang + da), q[1] + 12 * math.sin(ang + da))],
                   fill=color, width=width)


def _path_arrow(
    draw, points: list[tuple[float, float]], *, color=LINE, width=3, dashed=False,
    both_heads=False, label=None, label_pos=None, font=None,
) -> None:
    """A (poly)line from points[0] through points[-1] with an arrowhead at the end
    (and, if `both_heads`, at the start too) -- covers both plain 2-point arrows
    and the multi-segment "bypass" elbows the same way."""
    for p, q in zip(points, points[1:]):
        if dashed:
            _dashed_line(draw, p, q, color=color, width=width)
        else:
            draw.line([p, q], fill=color, width=width)
    _arrowhead(draw, points[-2], points[-1], color=color, width=width)
    if both_heads:
        _arrowhead(draw, points[1], points[0], color=color, width=width)
    if label and font:
        if label_pos is None:
            label_pos = ((points[0][0] + points[-1][0]) / 2, (points[0][1] + points[-1][1]) / 2)
        lx, ly = label_pos
        tb = draw.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        pad = 4
        knockout = (
            lx - tw / 2 - pad, ly - th / 2 - pad - tb[1],
            lx + tw / 2 + pad, ly + th / 2 + pad - tb[1],
        )
        draw.rectangle(knockout, fill=BG)
        draw.text((lx - tw / 2, ly - th / 2 - tb[1]), label, font=font, fill=MUTED)


def _mid(box, side: str) -> tuple[float, float]:
    x0, y0, x1, y1 = box
    return {
        "left": (x0, (y0 + y1) / 2), "right": (x1, (y0 + y1) / 2),
        "top": ((x0 + x1) / 2, y0), "bottom": ((x0 + x1) / 2, y1),
    }[side]


def main() -> None:
    img = Image.new("RGB", (W * SS, H * SS), BG)
    d = _ScaledDraw(ImageDraw.Draw(img), SS)
    f_title = _font(28, bold=True)
    f_subtitle = _font(14)
    f_name = _font(17, bold=True)
    f_sub = _font(12)
    f_label = _font(12)
    f_legend = _font(14)

    # ---- title (top-left, per spec) ------------------------------------------------------
    d.text((PAD, 20), "Inclusify Audit Agent — v2 (Auditor → Investigators → Consolidator)",
           font=f_title, fill=INK)
    d.text((PAD, 62),
           "steps[] logs every LLM call; module names below match steps[].module exactly",
           font=f_subtitle, fill=MUTED)

    diagram_cy = 490.0

    # ---- column 0: inputs -----------------------------------------------------------------
    x0, x1 = _col_x(0)
    execute_box, why_box = _vstack(x0, x1, diagram_cy, [110, 110], [70])
    _box(d, execute_box, fill=GREY_FILL, border=GREY_BORDER)
    _box_label(d, execute_box, "POST /api/execute", "{prompt}", f_name=f_name, f_sub=f_sub)
    _box(d, why_box, fill=GREY_FILL, border=GREY_BORDER, dashed=True)
    _box_label(d, why_box, "POST /api/why", "(on-demand)", f_name=f_name, f_sub=f_sub)

    # ---- column 1: deterministic pre-pass ---------------------------------------------------
    # `_vstack` centers the whole 3-box GROUP on its y_center, which puts the middle box
    # (Chunker) on that line, not the last one. LexiconScanner is the box whose outgoing
    # arrow must land as a clean horizontal on the Auditor, so its own center needs to be
    # diagram_cy: shift the group's center up by (one box height + one gap) to compensate.
    x0, x1 = _col_x(1)
    box_h, box_gap = 100, 50
    guards_box, chunker_box, lexicon_box = _vstack(
        x0, x1, diagram_cy - (box_h + box_gap), [box_h, box_h, box_h], [box_gap, box_gap],
    )
    for box, name, sub in (
        (guards_box, "Guards", "English check · size cap"),
        (chunker_box, "Chunker", "blocks · sentences · windows (offset-exact)"),
        (lexicon_box, "LexiconScanner", "1,530-term scan → sensor hints"),
    ):
        _box(d, box, fill=GREY_FILL, border=GREY_BORDER)
        _box_label(d, box, name, sub, f_name=f_name, f_sub=f_sub)

    # ---- column 2: DocumentAuditor ----------------------------------------------------------
    x0, x1 = _col_x(2)
    (auditor_box,) = _vstack(x0, x1, diagram_cy, [190], [])
    _box(d, auditor_box, fill=AMBER_FILL, border=AMBER_BORDER)
    _box_label(d, auditor_box, DOCUMENT_AUDITOR,
               "LLM × N windows · adjudicates every hint · finds implied bias",
               f_name=f_name, f_sub=f_sub)

    # ---- column 3: EvidenceInvestigator (stacked = parallel instances) ----------------------
    x0, x1 = _col_x(3)
    (investigator_box,) = _vstack(x0, x1, diagram_cy, [190], [])
    # Two "ghost" copies offset down-right, drawn first so the real (unshifted) box
    # occludes their top-left corner -- reads as a stack of parallel instances peeking
    # out bottom-right, front card = the one everything actually connects to.
    for dx in (40, 20):
        ghost = (investigator_box[0] + dx, investigator_box[1] + dx,
                 investigator_box[2] + dx, investigator_box[3] + dx)
        _box(d, ghost, fill=AMBER_FILL, border=AMBER_BORDER)
    _box(d, investigator_box, fill=AMBER_FILL, border=AMBER_BORDER)
    _box_label(d, investigator_box, EVIDENCE_INVESTIGATOR,
               "LLM × K findings · parallel ≤5 · ≤4 turns · confirm/reject",
               f_name=f_name, f_sub=f_sub)

    # ---- column 4: evidence tools -----------------------------------------------------------
    x0, x1 = _col_x(4)
    corpus_box, live_box = _vstack(x0, x1, diagram_cy, [110, 110], [110])
    _box(d, corpus_box, fill=VIOLET_FILL, border=VIOLET_BORDER)
    _box_label(d, corpus_box, "CorpusSearch", "Pinecone · ERIC corpus (42MB)",
               f_name=f_name, f_sub=f_sub)
    _box(d, live_box, fill=RUST_FILL, border=RUST_BORDER, dashed=True)
    _box_label(d, live_box, "LiveSearch", "ERIC API Lucene ladder (env-gated)",
               f_name=f_name, f_sub=f_sub)

    # ---- column 5: ReportConsolidator -> Report ---------------------------------------------
    x0, x1 = _col_x(5)
    consolidator_box, report_box = _vstack(x0, x1, diagram_cy, [170, 170], [70])
    _box(d, consolidator_box, fill=AMBER_FILL, border=AMBER_BORDER)
    _box_label(d, consolidator_box, REPORT_CONSOLIDATOR,
               "LLM × 1 · retract/patterns/severity · skipped if none confirmed",
               f_name=f_name, f_sub=f_sub)
    _box(d, report_box, fill=GREY_FILL, border=GREY_BORDER)
    _box_label(
        d, report_box, "Report",
        "per finding: quote · category · why · evidence · rewrite (+ patterns, steps[])",
        f_name=f_name, f_sub=f_sub,
    )

    # ---- arrows -----------------------------------------------------------------------------
    _path_arrow(d, [_mid(execute_box, "right"), _mid(guards_box, "left")])
    _path_arrow(d, [_mid(guards_box, "bottom"), _mid(chunker_box, "top")])
    _path_arrow(d, [_mid(chunker_box, "bottom"), _mid(lexicon_box, "top")])
    _path_arrow(d, [_mid(lexicon_box, "right"), _mid(auditor_box, "left")],
               label="windows + hints", font=f_label)
    _path_arrow(d, [_mid(auditor_box, "right"), _mid(investigator_box, "left")],
               label="candidates (fan-out)", font=f_label)
    _path_arrow(d, [_mid(investigator_box, "right"), _mid(corpus_box, "left")], both_heads=True)
    _path_arrow(d, [_mid(investigator_box, "right"), _mid(live_box, "left")], both_heads=True)
    _path_arrow(d, [_mid(consolidator_box, "bottom"), _mid(report_box, "top")])

    # investigators -> Consolidator: routed ABOVE the tools column (elbow) so the
    # straight-line path never cuts through CorpusSearch/LiveSearch.
    inv_top = _mid(investigator_box, "top")
    cons_top = _mid(consolidator_box, "top")
    bend_y = 230.0
    _path_arrow(
        d,
        [(inv_top[0] + 30, inv_top[1]), (inv_top[0] + 30, bend_y),
         (cons_top[0], bend_y), cons_top],
        label="verdicts", font=f_label, label_pos=((inv_top[0] + 30 + cons_top[0]) / 2, bend_y),
    )

    # /api/why -> EvidenceInvestigator: dashed bypass routed above the pre-pass/auditor
    # chain entirely (visual cue: this path skips them), exiting the why box on its
    # right edge (clear of the execute box directly above it in the same column).
    why_right = _mid(why_box, "right")
    bypass_y = 110.0
    inv_left_x = inv_top[0] - 30
    _path_arrow(
        d,
        [why_right, (why_right[0], bypass_y), (inv_left_x, bypass_y), (inv_left_x, inv_top[1])],
        dashed=True, label="single finding", font=f_label,
        label_pos=((why_right[0] + inv_left_x) / 2, bypass_y),
    )

    # ---- legend -------------------------------------------------------------------------------
    ly0, ly1 = H - 95, H - 95 + 26
    chip_w = 26
    legend = [
        (AMBER_FILL, AMBER_BORDER, False, "LLM call (appears in steps[])"),
        (GREY_FILL, GREY_BORDER, False, "deterministic code"),
        (VIOLET_FILL, VIOLET_BORDER, False, "vector retrieval"),
        (RUST_FILL, RUST_BORDER, True, "live API, env-gated"),
    ]
    lx = PAD
    for fill, border, dashed, text in legend:
        chip = (lx, ly0, lx + chip_w, ly1)
        _box(d, chip, fill=fill, border=border, dashed=dashed, width=2)
        tb = d.textbbox((0, 0), text, font=f_legend)
        d.text((lx + chip_w + 10, ly0 + (ly1 - ly0 - (tb[3] - tb[1])) / 2 - tb[1]),
               text, font=f_legend, fill=INK)
        lx += chip_w + 10 + (tb[2] - tb[0]) + 46

    img = img.resize((W, H), Image.LANCZOS)  # the actual anti-aliasing step

    out = Path(__file__).resolve().parents[1] / "src" / "inclusify_agent" / "static"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "architecture.png"
    img.save(path, "PNG")
    print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
