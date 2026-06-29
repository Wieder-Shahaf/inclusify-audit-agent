"""Generate docs/architecture diagram PNG served by GET /api/model_architecture.

Run: python scripts/gen_architecture.py
Writes: src/inclusify_agent/static/architecture.png (committed; Docker/Vercel just serve it).

The LLM-call module names are pulled from MODULE_BY_TASK so the diagram can never
drift from the `steps[].module` log (assignment §C: names must be consistent).

ponytail: Pillow box-drawing, not graphviz/matplotlib. One PNG, regenerated only
when the pipeline changes. Pillow lives in the [dev] extra — runtime serves the file.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from inclusify_agent.server.recording_llm import MODULE_BY_TASK  # noqa: E402

LLM_MODULES = set(MODULE_BY_TASK.values())  # marked with * in the diagram

# Pipeline order (LLM + non-LLM). LLM ones must be in LLM_MODULES.
PIPELINE = [
    ("Input Text", "course material"),
    ("Chunker", "split + context"),
    ("LexiconScanner", "deterministic pass"),
    ("SpanClassifier", "flag / skip / ask"),
    ("CitationRetriever", "agentic-RAG"),
    ("RewriteComposer", "inclusive rewrite"),
    ("Reflector", "retract low-conf"),
    ("Audit Report", "findings + steps"),
]

W, H = 1280, 720
BG = (12, 12, 16)
INK = (236, 236, 240)
MUTED = (150, 150, 160)
LLM_FILL = (88, 80, 236)      # indigo — LLM modules
TOOL_FILL = (30, 30, 38)      # dark — deterministic modules
IO_FILL = (40, 44, 52)        # I/O endpoints
LINE = (90, 90, 110)
ACCENT = (124, 246, 198)      # mint — Router/control flow


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
                return ImageFont.truetype(c, size)
            except OSError:
                pass
    return ImageFont.load_default()


def _center(draw, box, text, font, fill):
    x0, y0, x1, y1 = box
    tb = draw.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    draw.text((x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2 - tb[1]),
              text, font=font, fill=fill)


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_title = _font(34, bold=True)
    f_box = _font(20, bold=True)
    f_sub = _font(14)
    f_legend = _font(15)

    d.text((48, 36), "Inclusify Audit Agent — Architecture", font=f_title, fill=INK)
    d.text((48, 80), "LangGraph ReAct + Reflection + Agentic-RAG", font=f_sub, fill=MUTED)

    # Two rows of 4 boxes each.
    bw, bh, gap = 250, 96, 38
    rows = [PIPELINE[:4], PIPELINE[4:]]
    coords: dict[str, tuple[int, int, int, int]] = {}
    y0_rows = [160, 380]
    for row, ry in zip(rows, y0_rows):
        x = 60
        for name, sub in row:
            box = (x, ry, x + bw, ry + bh)
            coords[name] = box
            is_llm = name in LLM_MODULES
            is_io = name in ("Input Text", "Audit Report")
            fill = LLM_FILL if is_llm else (IO_FILL if is_io else TOOL_FILL)
            d.rounded_rectangle(box, radius=14, fill=fill,
                                outline=ACCENT if is_llm else LINE, width=2)
            label = f"{name} *" if is_llm else name
            _center(d, (box[0], box[1] + 14, box[2], box[1] + 50), label, f_box, INK)
            _center(d, (box[0], box[1] + 52, box[2], box[3] - 8), sub, f_sub,
                    (210, 210, 220) if is_llm else MUTED)
            x += bw + gap

    # Arrows: row1 left->right, wrap down to row2, row2 left->right.
    def arrow(p, q, color=LINE):
        d.line([p, q], fill=color, width=3)
        # arrowhead
        import math
        ang = math.atan2(q[1] - p[1], q[0] - p[0])
        for da in (2.6, -2.6):
            d.line([q, (q[0] + 12 * math.cos(ang + da),
                        q[1] + 12 * math.sin(ang + da))], fill=color, width=3)

    flat = [n for n, _ in PIPELINE]
    for a, b in zip(flat, flat[1:]):
        ba, bb = coords[a], coords[b]
        if ba[1] == bb[1]:  # same row
            arrow((ba[2], (ba[1] + ba[3]) // 2), (bb[0], (bb[1] + bb[3]) // 2))
        else:  # wrap: down from last-of-row1 to first-of-row2
            arrow((ba[0] + bw // 2, ba[3]), (bb[0] + bw // 2, bb[1]))

    # Router control-flow banner (the ReAct loop owns next-module selection).
    rb = (60, 300, W - 60, 344)
    d.rounded_rectangle(rb, radius=12, fill=(20, 22, 30), outline=ACCENT, width=2)
    _center(d, rb,
            "Router *  —  ReAct controller: after each module, chooses the next "
            "(loops over chunks until Reflector -> stop)",
            f_legend, ACCENT)

    # Legend.
    ly = H - 56
    d.rectangle((60, ly, 84, ly + 24), fill=LLM_FILL, outline=ACCENT, width=2)
    d.text((94, ly + 3), "* LLM call — appears in /api/execute  steps[].module",
           font=f_legend, fill=INK)
    d.rectangle((560, ly, 584, ly + 24), fill=TOOL_FILL, outline=LINE, width=2)
    d.text((594, ly + 3), "deterministic module (no LLM)", font=f_legend, fill=MUTED)

    out = Path(__file__).resolve().parents[1] / "src" / "inclusify_agent" / "static"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "architecture.png"
    img.save(path, "PNG")
    print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
