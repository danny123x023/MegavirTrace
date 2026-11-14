"""Static chart for the PDF export (print = light palette, validated: see web/lib/palette.ts)."""

from __future__ import annotations

import math

from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, String
from reportlab.lib import colors

SURFACE = colors.HexColor("#fcfcfb")
SERIES_1 = colors.HexColor("#2a78d6")  # values
SERIES_2 = colors.HexColor("#eb6834")  # Sen trend line
GRID = colors.HexColor("#e1e0d9")
AXIS = colors.HexColor("#c3c2b7")
INK_2 = colors.HexColor("#52514e")
MUTED = colors.HexColor("#898781")


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=mag * 10)
    start = math.floor(lo / step) * step
    ticks = []
    v = start
    while v <= hi + 1e-9 * step:
        if v >= lo - 1e-9 * step:
            ticks.append(round(v, 10))
        v += step
    return ticks


def series_chart_drawing(result: dict, width: float = 480, height: float = 210) -> Drawing:
    s = result["series"]
    pts = [(t, v) for t, v in zip(s["t"], s["plot_values"], strict=True) if v is not None]
    trend = [(t, v) for t, v in zip(s["t"], s["trend_line"], strict=True) if v is not None]
    d = Drawing(width, height)
    if not pts:
        return d
    left, right, bottom, top = 46, 12, 34, 22
    pw, ph = width - left - right, height - bottom - top
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts] + ([p[1] for p in trend] if s["mode"] != "raw" else [])
    x0, x1 = min(xs), max(xs)
    yt = _nice_ticks(min(ys), max(ys))
    y0, y1 = min(yt[0], min(ys)), max(yt[-1], max(ys))

    def X(t):
        return left + (t - x0) / ((x1 - x0) or 1) * pw

    def Y(v):
        return bottom + (v - y0) / ((y1 - y0) or 1) * ph

    for v in yt:
        d.add(Line(left, Y(v), left + pw, Y(v), strokeColor=GRID, strokeWidth=0.5))
        d.add(String(left - 4, Y(v) - 3, f"{v:g}", fontSize=7, fillColor=MUTED, textAnchor="end"))
    d.add(Line(left, bottom, left + pw, bottom, strokeColor=AXIS, strokeWidth=0.7))
    for t in _nice_ticks(x0, x1, 6):
        d.add(String(X(t), bottom - 11, f"{int(t)}", fontSize=7, fillColor=MUTED, textAnchor="middle"))
    d.add(
        PolyLine(
            [c for p in pts for c in (X(p[0]), Y(p[1]))],
            strokeColor=SERIES_1,
            strokeWidth=1.5,
            strokeLineJoin=1,
            strokeLineCap=1,
        )
    )
    if len(pts) <= 60:
        for p in pts:
            d.add(Circle(X(p[0]), Y(p[1]), 2.2, fillColor=SERIES_1, strokeColor=SURFACE, strokeWidth=1))
    if s["mode"] != "raw" and trend:
        d.add(
            PolyLine(
                [c for p in (trend[0], trend[-1]) for c in (X(p[0]), Y(p[1]))],
                strokeColor=SERIES_2,
                strokeWidth=1.5,
            )
        )
    # legend (two series)
    lab = {
        "annual": "Yearly values",
        "season": f"{s.get('season') or ''} values",
        "monthly": "Monthly anomalies",
        "raw": "Monthly values",
    }[s["mode"]]
    d.add(Line(left, height - 10, left + 14, height - 10, strokeColor=SERIES_1, strokeWidth=2))
    d.add(String(left + 18, height - 13, lab, fontSize=8, fillColor=INK_2))
    if s["mode"] != "raw":
        d.add(Line(left + 130, height - 10, left + 144, height - 10, strokeColor=SERIES_2, strokeWidth=2))
        d.add(String(left + 148, height - 13, "Trend (Sen's slope)", fontSize=8, fillColor=INK_2))
    d.add(String(width - right, height - 13, result["units"], fontSize=8, fillColor=MUTED, textAnchor="end"))
    return d
