"""Generate THE architecture diagram — served by GET /api/model_architecture.

Run: python scripts/gen_architecture.py
Writes: src/inclusify_agent/static/architecture.png (committed; bundled into the Vercel
function via vercel.json includeFiles src/**; docs/ is excluded from the bundle, which is
why the file must live here).

Module names are pulled from server/recording_llm.py's MODULE_BY_TASK so the diagram can
never drift from steps[].module (course spec §C). Deterministic Pillow render (fixed
layout, 4x supersample + LANCZOS; no timestamps/randomness) — the __main__ self-check
asserts two runs are byte-identical. Shows the full v2 flow: guards, perceive,
DocumentAuditor, the EvidenceInvestigator tool loop (plan -> search -> review ->
sufficiency -> finalize, with revise/live-search branches), ReportConsolidator, report,
provider panels, and a legend.
"""
from __future__ import annotations

import io
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from inclusify_agent.server.recording_llm import MODULE_BY_TASK  # noqa: E402
from inclusify_agent.tools.guards import DEFAULT_MAX_WINDOWS  # noqa: E402

AUDITOR_NAME = MODULE_BY_TASK["audit"]
INVESTIGATOR_NAME = MODULE_BY_TASK["investigate"]
CONSOLIDATOR_NAME = MODULE_BY_TASK["consolidate"]

# Pulled from code (like MODULE_BY_TASK) so the diagram can't drift from the guards.
GUARDS_SUB = f"empty · English-only · ≤ {DEFAULT_MAX_WINDOWS} windows"
RUN_LOG_CHIP = "Supabase · steps[] · token usage"

# ---- palette (spec hex values) -----------------------------------------------------
BG = (255, 255, 255)
INK = (26, 35, 50)              # #1A2332
MUTED = (95, 102, 112)
NEUTRAL_FILL = (237, 239, 242)  # ink-border boxes (not LLM/deterministic/data)
DIVIDER = (206, 210, 216)

PURPLE_BORDER, PURPLE_FILL = (108, 75, 184), (240, 234, 251)   # #6C4BB8 / #F0EAFB
GREEN_BORDER, GREEN_FILL = (47, 111, 87), (230, 242, 236)      # #2F6F57 / #E6F2EC
BLUE_BORDER, BLUE_FILL = (59, 110, 168), (234, 241, 249)       # #3B6EA8 / #EAF1F9
RED = (192, 58, 43)                                             # #C03A2B

SS = 4  # supersample factor; see gen_architecture.py's SS docstring for the rationale

OUT_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "inclusify_agent" / "static" / "architecture.png"
)


# ============================================================================
# low-level render primitives (ported from gen_architecture.py's approach)
# ============================================================================

def _font(size: int, bold: bool = False):
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
    """See gen_architecture.py: wraps ImageDraw, multiplying every coordinate/width by
    SS so layout code stays in plain logical pixels while everything rasterizes at SS×
    for a later LANCZOS downsample (free anti-aliasing on shapes Pillow can't AA itself)."""

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

    def polygon(self, points, **kw):
        self._d.polygon(self._pts(points), **kw)

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


def _text_size(draw, text, font) -> tuple[float, float]:
    tb = draw.textbbox((0, 0), text, font=font)
    return tb[2] - tb[0], tb[3] - tb[1]


def _wrap(draw, text: str, font, max_width: float) -> list[str]:
    """Word-wrap, respecting explicit '\\n' as a hard break (used to force an exact
    two-line name like 'single-finding' / 'EvidenceInvestigator')."""
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
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


def _center_text(draw, cx: float, y: float, text: str, font, fill) -> float:
    tb = draw.textbbox((0, 0), text, font=font)
    w = tb[2] - tb[0]
    draw.text((cx - w / 2, y), text, font=font, fill=fill)
    return w


def _center_multicolor(draw, cx: float, y: float, parts: list[tuple[str, object, tuple]]) -> None:
    """One line, several (text, font, fill) runs concatenated, whole line centered."""
    widths = [_text_size(draw, t, f)[0] for t, f, _ in parts]
    x = cx - sum(widths) / 2
    for (t, f, fill), w in zip(parts, widths):
        draw.text((x, y), t, font=f, fill=fill)
        x += w


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


def _dashed_rect_border(draw, box, *, color, width=2, radius=14) -> None:
    x0, y0, x1, y1 = box
    r = radius
    _dashed_line(draw, (x0 + r, y0), (x1 - r, y0), color=color, width=width)
    _dashed_line(draw, (x1, y0 + r), (x1, y1 - r), color=color, width=width)
    _dashed_line(draw, (x1 - r, y1), (x0 + r, y1), color=color, width=width)
    _dashed_line(draw, (x0, y1 - r), (x0, y0 + r), color=color, width=width)


def _box(draw, box, *, fill, border, dashed=False, width=2, radius=14) -> None:
    if dashed:
        draw.rounded_rectangle(box, radius=radius, fill=fill)
        _dashed_rect_border(draw, box, color=border, width=width, radius=radius)
    else:
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=border, width=width)


def _arrowhead(draw, p, q, *, color, width) -> None:
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    for da in (2.6, -2.6):
        draw.line([q, (q[0] + 12 * math.cos(ang + da), q[1] + 12 * math.sin(ang + da))],
                   fill=color, width=width)


def _path_arrow(
    draw, points: list[tuple[float, float]], *, color=MUTED, width=3, dashed=False,
    label=None, label_pos=None, font=None, label_fill=None,
) -> None:
    for p, q in zip(points, points[1:]):
        if dashed:
            _dashed_line(draw, p, q, color=color, width=width)
        else:
            draw.line([p, q], fill=color, width=width)
    _arrowhead(draw, points[-2], points[-1], color=color, width=width)
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
        draw.text((lx - tw / 2, ly - th / 2 - tb[1]), label, font=font, fill=label_fill or color)


def _mid(box, side: str) -> tuple[float, float]:
    x0, y0, x1, y1 = box
    return {
        "left": (x0, (y0 + y1) / 2), "right": (x1, (y0 + y1) / 2),
        "top": ((x0 + x1) / 2, y0), "bottom": ((x0 + x1) / 2, y1),
    }[side]


def _diamond_points(cx: float, cy: float, half_w: float, half_h: float):
    return [(cx, cy - half_h), (cx + half_w, cy), (cx, cy + half_h), (cx - half_w, cy)]


def _diamond(draw, cx, cy, half_w, half_h, *, fill, border, width=2) -> None:
    pts = _diamond_points(cx, cy, half_w, half_h)
    draw.polygon(pts, fill=fill)
    for p, q in zip(pts, pts[1:] + pts[:1]):
        draw.line([p, q], fill=border, width=width)


def _fits_or_raise(what: str, needed: float, available: float) -> None:
    """The anti-gibberish guarantee: raise loudly at build time rather than silently
    clipping text that doesn't fit its box."""
    if needed > available:
        raise ValueError(
            f"{what}: wrapped content needs {needed:.0f}px but box only has "
            f"{available:.0f}px -- widen the box or shorten the text"
        )


def _measure_label_h(draw, width: float, name: str, sub: str, f_name, f_sub, *, gap=6) -> float:
    inner_w = width - 24
    name_lines = _wrap(draw, name, f_name, inner_w)
    sub_lines = _wrap(draw, sub, f_sub, inner_w) if sub else []
    lh_n, lh_s = _line_h(draw, f_name), _line_h(draw, f_sub)
    return len(name_lines) * lh_n + (gap if sub_lines else 0) + len(sub_lines) * lh_s


def _draw_label(draw, box, name: str, sub: str, *, f_name, f_sub,
                name_fill=INK, sub_fill=None, gap=6, what="") -> None:
    x0, y0, x1, y1 = box
    cx, inner_w = (x0 + x1) / 2, (x1 - x0) - 24
    sub_fill = sub_fill or MUTED
    name_lines = _wrap(draw, name, f_name, inner_w)
    sub_lines = _wrap(draw, sub, f_sub, inner_w) if sub else []
    lh_n, lh_s = _line_h(draw, f_name), _line_h(draw, f_sub)
    total = len(name_lines) * lh_n + (gap if sub_lines else 0) + len(sub_lines) * lh_s
    _fits_or_raise(what or name, total, (y1 - y0) - 10)
    y = (y0 + y1) / 2 - total / 2
    for line in name_lines:
        _center_text(draw, cx, y, line, f_name, name_fill)
        y += lh_n
    if sub_lines:
        y += gap
        for line in sub_lines:
            _center_text(draw, cx, y, line, f_sub, sub_fill)
            y += lh_s


def _diamond_label(draw, cx, cy, half_w, half_h, name, sub, *, f_name, f_sub,
                    name_fill=INK, sub_fill=None) -> None:
    sub_fill = sub_fill or MUTED
    usable = half_w * 2 * 0.56
    name_lines = _wrap(draw, name, f_name, usable)
    sub_lines = _wrap(draw, sub, f_sub, usable) if sub else []
    lh_n, lh_s = _line_h(draw, f_name), _line_h(draw, f_sub)
    total = len(name_lines) * lh_n + (4 if sub_lines else 0) + len(sub_lines) * lh_s
    _fits_or_raise(f"diamond {name!r}", total, half_h * 1.5)
    y = cy - total / 2
    for line in name_lines:
        _center_text(draw, cx, y, line, f_name, name_fill)
        y += lh_n
    if sub_lines:
        y += 4
        for line in sub_lines:
            _center_text(draw, cx, y, line, f_sub, sub_fill)
            y += lh_s


def _divider(draw, x0, x1, y) -> None:
    draw.line([(x0 + 10, y), (x1 - 10, y)], fill=DIVIDER, width=1)


def _chip(draw, cx, y, text, font, *, border) -> tuple:
    """Auto-sized pill; returns its box. White fill so it reads against any parent
    box's tinted fill; border color ties it to the parent's theme."""
    w, h = _text_size(draw, text, font)
    pad_x, pad_y = 10, 6
    box = (cx - w / 2 - pad_x, y, cx + w / 2 + pad_x, y + h + 2 * pad_y)
    draw.rounded_rectangle(box, radius=9, fill=BG, outline=border, width=2)
    draw.text((cx - w / 2, y + pad_y), text, font=font, fill=INK)
    return box


def _chip_row(draw, cx, y, texts, font, *, border, gap=14) -> float:
    """Row of auto-sized chips, centered as a group on cx. Returns bottom y."""
    sizes = [_text_size(draw, t, font) for t in texts]
    widths = [w + 20 for w, _h in sizes]
    total = sum(widths) + gap * (len(texts) - 1)
    x = cx - total / 2
    bottom = y
    for t, w, (_, h) in zip(texts, widths, sizes):
        chip_box = _chip(draw, x + w / 2, y, t, font, border=border)
        bottom = chip_box[3]
        x += w + gap
    return bottom


def _bullets(draw, x0, x1, y, items, font, *, fill=INK, line_gap=5) -> float:
    lh = _line_h(draw, font)
    max_w = (x1 - x0) - 20
    for item in items:
        lines = _wrap(draw, item, font, max_w)
        for i, line in enumerate(lines):
            prefix = "•  " if i == 0 else "    "
            draw.text((x0, y), prefix + line, font=font, fill=fill)
            y += lh
        y += line_gap
    return y - line_gap


def _centered_box(x0, x1, cy, h) -> tuple:
    return (x0, cy - h / 2, x1, cy + h / 2)


def _hspan(x_start: float, widths: list[float], gaps: list[float]) -> list[tuple]:
    xs = []
    x = x_start
    for i, w in enumerate(widths):
        xs.append((x, x + w))
        x += w + (gaps[i] if i < len(gaps) else 0)
    return xs


# ============================================================================
# build
# ============================================================================

def build() -> Image.Image:
    # Generous provisional canvas; trimmed to actual content extent at the end so the
    # PNG has no dead margin (deterministic -- purely a function of the fixed layout
    # below, no measurement of drawn pixels).
    PROVISIONAL_W, PROVISIONAL_H = 1900, 1500
    img = Image.new("RGB", (PROVISIONAL_W * SS, PROVISIONAL_H * SS), BG)
    d = _ScaledDraw(ImageDraw.Draw(img), SS)

    f_title = _font(34, bold=True)
    f_subtitle = _font(15)
    f_section = _font(12, bold=True)
    f_name = _font(16, bold=True)
    f_container_h = _font(19, bold=True)
    f_sub = _font(12)
    f_chip = _font(12)
    f_label = _font(12)
    f_label_b = _font(12, bold=True)
    f_legend = _font(13)
    f_diamond = _font(15, bold=True)

    PAD = 32
    W = PROVISIONAL_W

    # ---- TITLE (top-left) --------------------------------------------------------
    title_y = 26
    d.text((PAD, title_y), "Inclusify Audit Agent — v2 Architecture (shipped)",
            font=f_title, fill=INK)
    subtitle_y = title_y + _line_h(d, f_title) + 6
    d.text((PAD, subtitle_y), "Orchestrator–Workers · Agentic RAG · English-only",
            font=f_subtitle, fill=BLUE_BORDER)
    title_block_bottom = subtitle_y + _line_h(d, f_subtitle)

    # ---- OPTIONAL ENTRY inset (top-right, dashed container) -----------------------
    inset_w = 360
    inset_x1 = W - PAD
    inset_x0 = inset_x1 - inset_w
    inset_y0 = title_y
    label_h = _line_h(d, f_section)
    why_h = _measure_label_h(d, inset_w - 40, "POST /api/why", "", f_name, f_sub) + 14
    inv_h = _measure_label_h(d, inset_w - 40, "single-finding\nEvidenceInvestigator", "",
                              f_name, f_sub) + 14
    plain_h = _line_h(d, f_sub)
    arrow_gap = 30
    inset_content_top = inset_y0 + 14 + label_h + 8
    why_box = _centered_box(inset_x0 + 20, inset_x1 - 20,
                             inset_content_top + why_h / 2, why_h)
    inv_top = why_box[3] + arrow_gap
    inv_box = _centered_box(inset_x0 + 20, inset_x1 - 20, inv_top + inv_h / 2, inv_h)
    plain_y = inv_box[3] + arrow_gap - 6
    inset_y1 = plain_y + plain_h + 16

    d.text((inset_x0 + 16, inset_y0 + 14), "OPTIONAL ENTRY", font=f_section, fill=MUTED)
    _box(d, why_box, fill=GREEN_FILL, border=GREEN_BORDER)
    _draw_label(d, why_box, "POST /api/why", "", f_name=f_name, f_sub=f_sub)
    _box(d, inv_box, fill=PURPLE_FILL, border=PURPLE_BORDER)
    _draw_label(d, inv_box, "single-finding\nEvidenceInvestigator", "", f_name=f_name, f_sub=f_sub)
    _center_text(d, (inset_x0 + inset_x1) / 2, plain_y,
                 "{explanation, citations, steps[]}", f_sub, MUTED)
    _path_arrow(d, [_mid(why_box, "bottom"), _mid(inv_box, "top")])
    _path_arrow(d, [_mid(inv_box, "bottom"), ((inv_box[0] + inv_box[2]) / 2, plain_y - 4)])
    _dashed_rect_border(d, (inset_x0, inset_y0, inset_x1, inset_y1), color=MUTED, width=2)

    # ================================================================================
    # MAIN ROW: execute -> Guards -> Perceive -> DocumentAuditor -> Candidates? -> Clean report
    # ================================================================================
    row2_top = max(title_block_bottom, inset_y1) + 34

    execute_w, guards_w, perceive_w, auditor_w = 190, 168, 258, 236
    diamond_hw, diamond_hh = 92, 60
    clean_w = 190
    gaps2 = [34, 34, 34, 40, 62]
    widths2 = [execute_w, guards_w, perceive_w, auditor_w, diamond_hw * 2]
    spans2 = _hspan(PAD, widths2, gaps2)
    execute_span, guards_span, perceive_span, auditor_span, diamond_span = spans2
    clean_x0 = diamond_span[1] + gaps2[4]
    clean_span = (clean_x0, clean_x0 + clean_w)

    # heights: measure each, take the max for a uniform rectangular-box row height,
    # diamond sized independently (smaller) but centered on the same row axis.
    execute_h = _measure_label_h(d, execute_w, "POST /api/execute", "{prompt}", f_name, f_sub)
    guards_h = _measure_label_h(d, guards_w, "[0] Guards", GUARDS_SUB, f_name, f_sub)
    auditor_h = _measure_label_h(
        d, auditor_w, f"[2] {AUDITOR_NAME}",
        "LLM · 1 call/window · adjudicates every lexicon hint (flag/clean per term)",
        f_name, f_sub,
    )
    clean_h = _measure_label_h(d, clean_w, "Clean report", "", f_name, f_sub)
    # Perceive: name + chip row + divider + sub -- measured by hand below (compound box).
    perceive_name_h = _line_h(d, f_name)
    perceive_chip_h = _text_size(d, "Chunker", f_chip)[1] + 12 + 8
    perceive_sub_lines = _wrap(d, "blocks · sentences · 1.8k-token windows · exact offsets",
                                f_sub, perceive_w - 24)
    perceive_sub_h = len(perceive_sub_lines) * _line_h(d, f_sub)
    perceive_h = perceive_name_h + 8 + perceive_chip_h + 10 + perceive_sub_h + 8

    row2_h = max(execute_h, guards_h, auditor_h, clean_h, perceive_h) + 26
    row2_cy = row2_top + max(row2_h, diamond_hh * 2) / 2

    execute_box = _centered_box(*execute_span, row2_cy, row2_h)
    guards_box = _centered_box(*guards_span, row2_cy, row2_h)
    perceive_box = _centered_box(*perceive_span, row2_cy, row2_h)
    auditor_box = _centered_box(*auditor_span, row2_cy, row2_h)
    clean_box = _centered_box(*clean_span, row2_cy, row2_h)
    diamond_cx = (diamond_span[0] + diamond_span[1]) / 2

    _box(d, execute_box, fill=NEUTRAL_FILL, border=INK)
    _draw_label(d, execute_box, "POST /api/execute", "{prompt}", f_name=f_name, f_sub=f_sub)

    _box(d, guards_box, fill=GREEN_FILL, border=GREEN_BORDER)
    _draw_label(d, guards_box, "[0] Guards", GUARDS_SUB, f_name=f_name, f_sub=f_sub)

    _box(d, perceive_box, fill=GREEN_FILL, border=GREEN_BORDER)
    px0, py0, px1, py1 = perceive_box
    pcx = (px0 + px1) / 2
    py = py0 + 13
    _center_text(d, pcx, py, "[1] Perceive", f_name, INK)
    py += perceive_name_h + 8
    chip_bottom = _chip_row(d, pcx, py, ["Chunker", "LexiconScanner"], f_chip, border=GREEN_BORDER)
    py = chip_bottom + 10
    _divider(d, px0, px1, py)
    py += 10
    for line in perceive_sub_lines:
        _center_text(d, pcx, py, line, f_sub, MUTED)
        py += _line_h(d, f_sub)
    _fits_or_raise("[1] Perceive", py - py0, (py1 - py0))

    _box(d, auditor_box, fill=PURPLE_FILL, border=PURPLE_BORDER)
    _draw_label(d, auditor_box, f"[2] {AUDITOR_NAME}",
                "LLM · 1 call/window · adjudicates every lexicon hint (flag/clean per term)",
                f_name=f_name, f_sub=f_sub)

    _diamond(d, diamond_cx, row2_cy, diamond_hw, diamond_hh, fill=GREEN_FILL, border=GREEN_BORDER)
    _diamond_label(d, diamond_cx, row2_cy, diamond_hw, diamond_hh, "Candidates?", "",
                   f_name=f_diamond, f_sub=f_sub)

    _box(d, clean_box, fill=GREEN_FILL, border=GREEN_BORDER)
    _draw_label(d, clean_box, "Clean report", "", f_name=f_name, f_sub=f_sub)

    # arrows: main row chain
    _path_arrow(d, [_mid(execute_box, "right"), _mid(guards_box, "left")])
    _path_arrow(d, [_mid(guards_box, "right"), _mid(perceive_box, "left")])
    _path_arrow(d, [_mid(perceive_box, "right"), _mid(auditor_box, "left")])
    _path_arrow(d, [_mid(auditor_box, "right"), (diamond_cx - diamond_hw, row2_cy)])
    _path_arrow(d, [(diamond_cx + diamond_hw, row2_cy), _mid(clean_box, "left")],
                color=RED, label="NO", font=f_label_b, label_fill=RED,
                label_pos=((diamond_cx + diamond_hw + clean_box[0]) / 2, row2_cy - 16))

    # ================================================================================
    # [3] CONTAINER: EvidenceInvestigator x N
    # ================================================================================
    container_top = row2_cy + diamond_hh + 74
    container_x0 = PAD
    header_name = f"[3] {INVESTIGATOR_NAME} × N"
    header_sub = "parallel workers, ≤5 concurrent · one per distinct framing"

    plan_w, corpus_w, review_w = 168, 196, 196
    suff_hw, suff_hh = 100, 66
    finalize_w = 320
    row3_gaps = [34, 34, 34, 54]
    row3_widths = [plan_w, corpus_w, review_w, suff_hw * 2]
    header_h = _line_h(d, f_container_h) + 6 + _line_h(d, f_sub) + 18
    row3_top = container_top + header_h
    row3_spans = _hspan(container_x0 + 26, row3_widths, row3_gaps)
    plan_span, corpus_span, review_span, suff_span = row3_spans
    finalize_x0 = suff_span[1] + 60
    finalize_span = (finalize_x0, finalize_x0 + finalize_w)
    container_x1 = finalize_span[1] + 26

    plan_h = _measure_label_h(d, plan_w, "Plan evidence query", "", f_name, f_sub)
    corpus_h = _measure_label_h(d, corpus_w, "CorpusSearch", "over-fetch ×5 · dedupe · top 3",
                                 f_name, f_sub)
    review_h = _measure_label_h(d, review_w, "Review returned evidence", "", f_name, f_sub)
    finalize_sub = ("confirmed requires cited evidence — an evidence-free confirm is bounced "
                    "once, then accepted only with confidence capped to low + needs_human_review")
    finalize_name_h = _line_h(d, f_name)
    finalize_sub_lines = _wrap(d, finalize_sub, f_sub, finalize_w - 24)
    finalize_h = finalize_name_h + 8 + 10 + len(finalize_sub_lines) * _line_h(d, f_sub) + 8

    row3_h = max(plan_h, corpus_h, review_h, finalize_h) + 26
    row3_cy = row3_top + max(row3_h, suff_hh * 2) / 2

    plan_box = _centered_box(*plan_span, row3_cy, row3_h)
    corpus_box = _centered_box(*corpus_span, row3_cy, row3_h)
    review_box = _centered_box(*review_span, row3_cy, row3_h)
    finalize_box = _centered_box(*finalize_span, row3_cy, row3_h)
    suff_cx = (suff_span[0] + suff_span[1]) / 2

    corpus_chip_y = corpus_box[3] + 8
    corpus_chip_box = _chip(d, (corpus_box[0] + corpus_box[2]) / 2, corpus_chip_y,
                             "ERIC vector index", f_chip, border=BLUE_BORDER)

    row3_bottom_extent = corpus_chip_box[3]
    bypass_y = row3_bottom_extent + 34

    live_w = 340
    live_cx = (review_span[0] + suff_span[1]) / 2
    live_sub = ("env-gated (ERIC_LIVE_SEARCH) · Lucene ladder: strict → relaxed → broad "
                "(stops at first rung with ≥3 hits), then embed re-rank of the results")
    live_name_h = _line_h(d, f_name)
    live_sub_lines = _wrap(d, live_sub, f_sub, live_w - 24)
    live_h = live_name_h + 8 + len(live_sub_lines) * _line_h(d, f_sub) + 22
    live_top = bypass_y + 26
    live_box = (live_cx - live_w / 2, live_top, live_cx + live_w / 2, live_top + live_h)

    container_content_bottom = live_box[3]
    container_y1 = container_content_bottom + 30
    container_box = (container_x0, container_top, container_x1, container_y1)

    _box(d, container_box, fill=BG, border=PURPLE_BORDER, width=3, radius=14)
    d.text((container_x0 + 30, container_top + 20), header_name, font=f_container_h,
           fill=PURPLE_BORDER)
    d.text((container_x0 + 30, container_top + 20 + _line_h(d, f_container_h) + 4),
           header_sub, font=f_sub, fill=MUTED)

    # Candidates? YES -> down into the [3] container's top edge (fan-out to parallel
    # investigators). Drawn after the container so the arrowhead sits on top of its border.
    _path_arrow(
        d, [(diamond_cx, row2_cy + diamond_hh), (diamond_cx, container_top)],
        color=GREEN_BORDER, label="YES | candidates (fan-out)", font=f_label_b,
        label_fill=GREEN_BORDER,
        label_pos=(diamond_cx, (row2_cy + diamond_hh + container_top) / 2),
    )

    _box(d, plan_box, fill=PURPLE_FILL, border=PURPLE_BORDER)
    _draw_label(d, plan_box, "Plan evidence query", "", f_name=f_name, f_sub=f_sub)

    _box(d, corpus_box, fill=BLUE_FILL, border=BLUE_BORDER)
    _draw_label(d, corpus_box, "CorpusSearch", "over-fetch ×5 · dedupe · top 3",
                f_name=f_name, f_sub=f_sub)
    # corpus_chip was drawn earlier purely to MEASURE its height for the row3/bypass_y
    # layout math below; container_box + corpus_box are drawn after that (on top of
    # it), so redraw it now that it's the topmost thing at this position.
    _chip(d, (corpus_box[0] + corpus_box[2]) / 2, corpus_chip_y, "ERIC vector index",
          f_chip, border=BLUE_BORDER)

    _box(d, review_box, fill=PURPLE_FILL, border=PURPLE_BORDER)
    _draw_label(d, review_box, "Review returned evidence", "", f_name=f_name, f_sub=f_sub)

    _diamond(d, suff_cx, row3_cy, suff_hw, suff_hh, fill=PURPLE_FILL, border=PURPLE_BORDER)
    _diamond_label(d, suff_cx, row3_cy, suff_hw, suff_hh, "Evidence sufficient?",
                   "(model's judgment)", f_name=f_diamond, f_sub=f_sub)

    _box(d, finalize_box, fill=PURPLE_FILL, border=PURPLE_BORDER, width=3)
    fx0, fy0, fx1, fy1 = finalize_box
    fcx = (fx0 + fx1) / 2
    fy = fy0 + (row3_h - finalize_h) / 2 + 6
    _center_multicolor(d, fcx, fy, [
        ("Finalize: confirm / ", f_name, INK), ("reject", f_name, RED),
    ])
    fy += finalize_name_h + 8
    _divider(d, fx0, fx1, fy)
    fy += 10
    for line in finalize_sub_lines:
        _center_text(d, fcx, fy, line, f_sub, MUTED)
        fy += _line_h(d, f_sub)
    _fits_or_raise("Finalize box", fy - fy0, (fy1 - fy0))

    _box(d, live_box, fill=BLUE_FILL, border=BLUE_BORDER, dashed=True)
    lx0, ly0, lx1, ly1 = live_box
    lcx = (lx0 + lx1) / 2
    ly = ly0 + 10
    _center_text(d, lcx, ly, "LiveSearch", f_name, INK)
    ly += live_name_h + 8
    for line in live_sub_lines:
        _center_text(d, lcx, ly, line, f_sub, MUTED)
        ly += _line_h(d, f_sub)
    _fits_or_raise("LiveSearch box", ly - ly0, (ly1 - ly0))

    # ---- container-internal arrows -------------------------------------------------
    _path_arrow(d, [_mid(plan_box, "right"), _mid(corpus_box, "left")])
    _path_arrow(d, [_mid(corpus_box, "right"), _mid(review_box, "left")])
    _path_arrow(d, [_mid(review_box, "right"), (suff_cx - suff_hw, row3_cy)])
    _path_arrow(d, [(suff_cx + suff_hw, row3_cy), _mid(finalize_box, "left")],
                color=GREEN_BORDER, label="YES", font=f_label_b, label_fill=GREEN_BORDER,
                label_pos=((suff_cx + suff_hw + finalize_box[0]) / 2, row3_cy - 16))

    # NO: solid bypass below the row, back into Plan evidence query
    plan_cx = (plan_box[0] + plan_box[2]) / 2
    _path_arrow(
        d,
        [(suff_cx, row3_cy + suff_hh), (suff_cx, bypass_y), (plan_cx, bypass_y),
         (plan_cx, plan_box[3])],
        color=MUTED, label="revise query · ≤4 LLM turns total (incl. finalize)",
        font=f_label, label_fill=MUTED, label_pos=((suff_cx + plan_cx) / 2 + 40, bypass_y - 12),
    )
    # NO: dashed blue tap -> LiveSearch, then solid LiveSearch -> Review
    _path_arrow(
        d, [(suff_cx, row3_cy + suff_hh), (suff_cx, bypass_y - 14), (lcx, bypass_y - 14),
            (lcx, live_box[1])],
        color=BLUE_BORDER, dashed=True, label="weak local evidence", font=f_label,
        label_fill=BLUE_BORDER, label_pos=(lcx + 20, bypass_y - 26),
    )
    review_cx = (review_box[0] + review_box[2]) / 2
    live_top_mid = _mid(live_box, "top")
    live_elbow_y = (review_box[3] + live_box[1]) / 2
    _path_arrow(
        d, [(live_top_mid[0], live_box[1]), (live_top_mid[0], live_elbow_y),
            (review_cx, live_elbow_y), (review_cx, review_box[3])],
        color=MUTED,
    )

    # ================================================================================
    # RIGHT of container: [4] ReportConsolidator -> [5] Report
    # ================================================================================
    right_x0 = container_x1 + 40
    right_w = 320
    right_x1 = right_x0 + right_w

    cons_sub1 = "LLM · one call, only if ≥1 finding confirmed (skipped otherwise)"
    cons_sub2 = "merge · retract · group patterns · severity"
    cons_name_h = _line_h(d, f_name)
    cons_sub1_lines = _wrap(d, cons_sub1, f_sub, right_w - 24)
    cons_sub2_lines = _wrap(d, cons_sub2, f_sub, right_w - 24)
    cons_h = (cons_name_h + 8 + len(cons_sub1_lines) * _line_h(d, f_sub) + 10 + 10
              + len(cons_sub2_lines) * _line_h(d, f_sub) + 14)

    cons_top = row3_cy - cons_h / 2  # align with Finalize's row (arrow lands horizontal)
    consolidator_box = (right_x0, cons_top, right_x1, cons_top + cons_h)

    report_top = consolidator_box[3] + 34
    report_bullets = [
        "Quoted text + offsets", "Classification", "Grounded explanation [n]",
        "Evidence snippet + source", "Inclusive alternative",
    ]
    report_sub2 = "confidence · human review · document patterns"
    report_name_h = _line_h(d, f_name)
    bullets_h = len(report_bullets) * _line_h(d, f_sub) + (len(report_bullets)) * 5
    report_sub2_lines = _wrap(d, report_sub2, f_sub, right_w - 24)
    report_h = (report_name_h + 8 + bullets_h + 6 + 10
                + len(report_sub2_lines) * _line_h(d, f_sub) + 14)
    report_box = (right_x0, report_top, right_x1, report_top + report_h)

    # API/GUI and Run logging: side by side, spanning under container+right column
    out_top = max(container_y1, report_box[3]) + 44
    out_w = 340
    out_gap = 50
    total_out_w = out_w * 2 + out_gap
    out_center = (container_x0 + report_box[2]) / 2
    api_x0 = out_center - total_out_w / 2
    api_span = (api_x0, api_x0 + out_w)
    run_span = (api_span[1] + out_gap, api_span[1] + out_gap + out_w)

    api_sub = ("response = markdown report (+ token-usage footer) · steps[] = every "
               "LLM call {module, prompt, response}")
    api_name_h = _line_h(d, f_name)
    api_sub_lines = _wrap(d, api_sub, f_sub, out_w - 24)
    api_h = api_name_h + 8 + len(api_sub_lines) * _line_h(d, f_sub) + 20

    run_name_h = _line_h(d, f_name)
    run_chip_h = _text_size(d, RUN_LOG_CHIP, f_chip)[1] + 12
    run_h = run_name_h + 8 + run_chip_h + 8 + run_chip_h + 16

    out_h = max(api_h, run_h)
    api_box = _centered_box(*api_span, out_top + out_h / 2, out_h)
    run_box = _centered_box(*run_span, out_top + out_h / 2, out_h)

    _box(d, consolidator_box, fill=PURPLE_FILL, border=PURPLE_BORDER)
    ccx = (right_x0 + right_x1) / 2
    sub_lh = _line_h(d, f_sub)
    cons_content_h = (cons_name_h + 8 + len(cons_sub1_lines) * sub_lh
                       + 10 + 10 + len(cons_sub2_lines) * sub_lh)
    cy_ = consolidator_box[1] + (cons_h - cons_content_h) / 2
    _center_text(d, ccx, cy_, f"[4] {CONSOLIDATOR_NAME}", f_name, INK)
    cy_ += cons_name_h + 8
    for line in cons_sub1_lines:
        _center_text(d, ccx, cy_, line, f_sub, MUTED)
        cy_ += _line_h(d, f_sub)
    cy_ += 6
    _divider(d, right_x0, right_x1, cy_)
    cy_ += 10
    for line in cons_sub2_lines:
        _center_text(d, ccx, cy_, line, f_sub, MUTED)
        cy_ += _line_h(d, f_sub)
    _fits_or_raise("[4] ReportConsolidator", cy_ - consolidator_box[1], cons_h)

    _box(d, report_box, fill=GREEN_FILL, border=GREEN_BORDER)
    rcx = (right_x0 + right_x1) / 2
    ry = report_box[1] + 12
    _center_text(d, rcx, ry, "[5] Report", f_name, INK)
    ry += report_name_h + 8
    ry = _bullets(d, right_x0 + 14, right_x1 - 14, ry, report_bullets, f_sub) + 6
    _divider(d, right_x0, right_x1, ry)
    ry += 10
    for line in report_sub2_lines:
        _center_text(d, rcx, ry, line, f_sub, MUTED)
        ry += _line_h(d, f_sub)
    _fits_or_raise("[5] Report", ry - report_box[1], report_h)

    _box(d, api_box, fill=BLUE_FILL, border=BLUE_BORDER)
    _draw_label(d, api_box, "API / GUI", api_sub, f_name=f_name, f_sub=f_sub, what="API / GUI")

    _box(d, run_box, fill=BLUE_FILL, border=BLUE_BORDER)
    rx0, ry0, rx1, ry1 = run_box
    rcx2 = (rx0 + rx1) / 2
    ry2 = ry0 + 12
    _center_text(d, rcx2, ry2, "Run logging", f_name, INK)
    ry2 += run_name_h + 8
    chip1_box = _chip(d, rcx2, ry2, "Null (offline)", f_chip, border=BLUE_BORDER)
    ry2 = chip1_box[3] + 8
    chip2_box = _chip(d, rcx2, ry2, RUN_LOG_CHIP, f_chip, border=BLUE_BORDER)
    _fits_or_raise("Run logging box", chip2_box[3] - ry0, (ry1 - ry0))

    # arrows: Finalize -> [4] -> [5] -> {API/GUI, Run logging}; Clean report -> both outputs
    _path_arrow(d, [_mid(finalize_box, "right"), _mid(consolidator_box, "left")])
    _path_arrow(d, [_mid(consolidator_box, "bottom"), _mid(report_box, "top")])
    api_cx = (api_box[0] + api_box[2]) / 2
    run_cx = (run_box[0] + run_box[2]) / 2
    report_bottom_mid = _mid(report_box, "bottom")
    out_elbow_y = (report_box[3] + api_box[1]) / 2
    _path_arrow(
        d, [report_bottom_mid, (report_bottom_mid[0], out_elbow_y),
            (api_cx, out_elbow_y), (api_cx, api_box[1])],
    )
    _path_arrow(
        d, [report_bottom_mid, (report_bottom_mid[0], out_elbow_y + 14),
            (run_cx, out_elbow_y + 14), (run_cx, run_box[1])],
    )

    clean_cx = (clean_box[0] + clean_box[2]) / 2
    detour_x1, detour_x2 = clean_cx + 14, clean_cx - 14
    corridor_y = max(container_y1, report_box[3]) + 20
    _path_arrow(
        d, [(detour_x1, clean_box[3]), (detour_x1, corridor_y), (api_cx + 26, corridor_y),
            (api_cx + 26, api_box[1])],
        color=MUTED,
    )
    _path_arrow(
        d, [(detour_x2, clean_box[3]), (detour_x2, corridor_y - 12), (run_cx - 26, corridor_y - 12),
            (run_cx - 26, run_box[1])],
        color=MUTED,
    )

    # ================================================================================
    # BOTTOM PANELS: LLM providers / Embeddings / Vector stores
    # ================================================================================
    panels_top = max(api_box[3], run_box[3]) + 56

    def _panel_size(title: str, chips: list[str]) -> tuple[float, float]:
        chip_w = sum(_text_size(d, c, f_chip)[0] + 20 for c in chips) + 14 * (len(chips) - 1)
        title_w = _text_size(d, title, f_name)[0]
        w = max(chip_w, title_w) + 48
        h = _line_h(d, f_name) + 10 + (_text_size(d, chips[0], f_chip)[1] + 12) + 26
        return w, h

    llm_chips = ["MockLLM (offline)", "LLMod.ai · gpt-5.4-mini"]
    emb_chips = ["Hash (offline)", "text-embedding-3-small", "local-ST (offline, optional)"]
    vec_chips = ["In-memory · Chroma · Pinecone"]

    llm_w, llm_h = _panel_size("LLM providers", llm_chips)
    emb_w, emb_h = _panel_size("Embeddings", emb_chips)
    vec_w, vec_h = _panel_size("Vector stores", vec_chips)
    panel_h = max(llm_h, emb_h, vec_h)

    panel_gap = 40
    panel_spans = _hspan(PAD, [llm_w, emb_w, vec_w], [panel_gap, panel_gap])
    llm_span, emb_span, vec_span = panel_spans
    llm_box = (llm_span[0], panels_top, llm_span[1], panels_top + panel_h)
    emb_box = (emb_span[0], panels_top, emb_span[1], panels_top + panel_h)
    vec_box = (vec_span[0], panels_top, vec_span[1], panels_top + panel_h)

    def _draw_panel(box, title, chips, border_for_chips=BLUE_BORDER):
        _box(d, box, fill=BLUE_FILL, border=BLUE_BORDER)
        x0, y0, x1, y1 = box
        d.text((x0 + 18, y0 + 14), title, font=f_name, fill=INK)
        cy = y0 + 14 + _line_h(d, f_name) + 10
        _chip_row(d, (x0 + x1) / 2, cy, chips, f_chip, border=border_for_chips)

    _draw_panel(llm_box, "LLM providers", llm_chips)
    _draw_panel(emb_box, "Embeddings", emb_chips)
    _draw_panel(vec_box, "Vector stores", vec_chips)

    # dashed taps rising from panels into the diagram above -- routed through row3's
    # column gaps and the clear bands below the container / beside the output boxes,
    # so a dashed line never cuts through a box (crossing another arrow is fine;
    # crossing a box reads as a rendering bug, so these deliberately avoid it).
    llm_cx = (llm_box[0] + llm_box[2]) / 2
    band_lo = (max(api_box[3], run_box[3]) + panels_top) / 2  # between outputs & panels
    mid_gap_x = (api_box[2] + run_box[0]) / 2  # clear lane between API/GUI and Run logging
    row3_gap_xs = [
        (plan_box[2] + corpus_box[0]) / 2,
        (corpus_box[2] + review_box[0]) / 2,
        (review_box[2] + suff_span[0]) / 2,
        (suff_span[1] + finalize_box[0]) / 2,
    ]
    auditor_cx = _mid(auditor_box, "bottom")[0]
    gap_to_auditor = min(row3_gap_xs, key=lambda gx: abs(gx - auditor_cx))
    above_container_y = container_top - 20
    below_container_y = container_y1 + 12

    tap1_x = llm_box[0] + 40
    _path_arrow(
        d,
        [(tap1_x, llm_box[1]), (tap1_x, band_lo), (mid_gap_x, band_lo),
         (mid_gap_x, below_container_y), (gap_to_auditor, below_container_y),
         (gap_to_auditor, above_container_y), (auditor_cx, above_container_y),
         (auditor_cx, auditor_box[3])],
        color=PURPLE_BORDER, dashed=True,
    )
    tap2_x = llm_cx
    _path_arrow(d, [(tap2_x, llm_box[1]), (tap2_x, container_y1)],
                color=PURPLE_BORDER, dashed=True)

    right_gap_x = (container_x1 + right_x0) / 2
    # offset from dead-center so this arrowhead doesn't land on top of the [4]->[5]
    # connector, which uses the exact center-bottom point.
    cons_cx2 = consolidator_box[0] + (consolidator_box[2] - consolidator_box[0]) * 0.25
    tap3_x = llm_box[2] - 40
    _path_arrow(
        d,
        [(tap3_x, llm_box[1]), (tap3_x, band_lo), (right_gap_x, band_lo),
         (right_gap_x, consolidator_box[3] + 14), (cons_cx2, consolidator_box[3] + 14),
         (cons_cx2, consolidator_box[3])],
        color=PURPLE_BORDER, dashed=True,
    )

    corpus_chip_cx = (corpus_chip_box[0] + corpus_chip_box[2]) / 2
    live_cx2 = (live_box[0] + live_box[2]) / 2

    # tap: Embeddings -> "ERIC vector index" chip. emb_box[0]+60 is clear of both
    # output boxes (api_box/run_box) for its whole rise, so no jog needed.
    emb_chip_x, chip_land_y = emb_box[0] + 60, corpus_chip_box[3] + 30
    _path_arrow(
        d, [(emb_chip_x, emb_box[1]), (emb_chip_x, chip_land_y),
            (corpus_chip_cx - 18, chip_land_y), (corpus_chip_cx - 18, corpus_chip_box[3])],
        color=BLUE_BORDER, dashed=True,
    )
    # tap: Embeddings -> LiveSearch. emb_box[2]-60 falls inside api_box's span, so this
    # one needs the same below-container jog through mid_gap_x that the LLM taps use.
    _path_arrow(
        d,
        [(emb_box[2] - 60, emb_box[1]), (emb_box[2] - 60, band_lo), (mid_gap_x, band_lo),
         (mid_gap_x, below_container_y), (live_cx2, below_container_y), (live_cx2, live_box[3])],
        color=BLUE_BORDER, dashed=True,
    )

    # tap: Vector stores -> "ERIC vector index" chip. vec_cx falls inside run_box's
    # span, so route the same way: jog through mid_gap_x below the output-box layer.
    vec_cx = (vec_box[0] + vec_box[2]) / 2
    _path_arrow(
        d,
        [(vec_cx, vec_box[1]), (vec_cx, band_lo), (mid_gap_x, band_lo),
         (mid_gap_x, below_container_y), (corpus_chip_cx + 18, below_container_y),
         (corpus_chip_cx + 18, corpus_chip_box[3])],
        color=BLUE_BORDER, dashed=True,
    )

    # ================================================================================
    # LEGEND (bottom-left, dashed border)
    # ================================================================================
    legend_top = panels_top + panel_h + 44
    swatches = [
        (PURPLE_FILL, PURPLE_BORDER, "LLM judgment"),
        (GREEN_FILL, GREEN_BORDER, "Deterministic code"),
        (BLUE_FILL, BLUE_BORDER, "Evidence / data / tools"),
        (NEUTRAL_FILL, RED, "Rejection / retraction"),
    ]
    chip_dim = 22
    x = PAD + 20
    y = legend_top + 20
    item_gap = 34
    for fill, border, text in swatches:
        _box(d, (x, y, x + chip_dim, y + chip_dim), fill=fill, border=border, radius=5)
        tw, _ = _text_size(d, text, f_legend)
        d.text((x + chip_dim + 10, y + (chip_dim - _line_h(d, f_legend)) / 2 + 2), text,
               font=f_legend, fill=INK)
        x += chip_dim + 10 + tw + item_gap

    arrow_w = 46
    line_y = y + chip_dim / 2
    d.line([(x, line_y), (x + arrow_w, line_y)], fill=INK, width=3)
    _arrowhead(d, (x, line_y), (x + arrow_w, line_y), color=INK, width=3)
    tw, _ = _text_size(d, "Primary flow", f_legend)
    d.text((x + arrow_w + 10, y + (chip_dim - _line_h(d, f_legend)) / 2 + 2), "Primary flow",
           font=f_legend, fill=INK)
    x += arrow_w + 10 + tw + item_gap

    _dashed_line(d, (x, line_y), (x + arrow_w, line_y), color=INK, width=3)
    _arrowhead(d, (x, line_y), (x + arrow_w, line_y), color=INK, width=3)
    tw, _ = _text_size(d, "Optional / conditional", f_legend)
    d.text((x + arrow_w + 10, y + (chip_dim - _line_h(d, f_legend)) / 2 + 2),
           "Optional / conditional", font=f_legend, fill=INK)
    x += arrow_w + 10 + tw + 16

    legend_x1 = x + 16
    legend_y1 = y + chip_dim + 18
    _dashed_rect_border(d, (PAD, legend_top, legend_x1, legend_y1), color=MUTED, width=2)

    # ---- trim canvas to actual content extent --------------------------------------
    content_w = max(legend_x1, panels_top and vec_box[2], inset_x1) + PAD
    content_h = legend_y1 + PAD
    img = img.crop((0, 0, int(content_w * SS), int(content_h * SS)))
    img = img.resize((int(content_w), int(content_h)), Image.LANCZOS)
    return img


def main() -> Path:
    img = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH, "PNG")
    return OUT_PATH


if __name__ == "__main__":
    path = main()
    size = path.stat().st_size
    print(f"wrote {path} ({path.stat().st_size} bytes, {Image.open(path).size})")
    assert path.exists(), "output PNG missing"
    assert size > 100_000, f"output PNG suspiciously small: {size} bytes"

    buf1, buf2 = io.BytesIO(), io.BytesIO()
    build().save(buf1, "PNG")
    build().save(buf2, "PNG")
    assert buf1.getvalue() == buf2.getvalue(), "render is not deterministic across in-memory runs"
    assert path.read_bytes() == buf1.getvalue(), "saved PNG differs from a fresh in-memory render"
    print("self-check OK: >100KB, deterministic, byte-identical across renders")
