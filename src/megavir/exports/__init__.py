"""Downloads (FR16): CSV, Excel, PDF and a notebook that recomputes the result.

The notebook carries the regional monthly series and a self-contained copy of the trend
tests (NumPy/SciPy only), recomputes every headline number and checks it against the app's
stored values, so a judge can verify the result without trusting the server.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1] / "engine"


def _slug(result: dict) -> str:
    var = result.get("variable", {}).get("id", "result")
    reg = (result.get("region") or result.get("region_a") or {}).get("name", "region")
    safe = "".join(c if c.isalnum() else "_" for c in reg)[:40].strip("_")
    return f"megavirtrace_{var}_{safe}_{result['id'][:8]}"


def _summary_rows(result: dict) -> list[tuple[str, str]]:
    p = result["provenance"]
    rows = [
        ("Headline", result["verdict"]["headline"]),
        *[("Finding", s) for s in result["verdict"]["sentences"]],
        *[("Caveat", c) for c in result["verdict"]["caveats"]],
        ("Product", p["product"]),
        ("DOI", p.get("doi") or p.get("paper_doi") or ""),
        ("Citation", p["citation"]),
        ("Data version", str(p["data_version"])),
        ("Data kind", p["data_kind"]),
        ("Engine version", p["engine_version"]),
        ("Fingerprint", p["fingerprint"]),
    ]
    if result["kind"] == "trend":
        st = result["stats"]
        pd = st["per_decade"]
        rows[1:1] = [
            ("Sen slope per decade", f"{pd['sen']}"),
            ("Sen 95% interval per decade", f"{pd['sen_low']} to {pd['sen_high']}"),
            ("Least-squares slope per decade", f"{pd['ols']}"),
            ("Least-squares 95% interval per decade", f"{pd['ols_low']} to {pd['ols_high']}"),
            ("Mann-Kendall p (AR(1)-corrected)", f"{st['mk']['p']}"),
            ("Least-squares p (AR(1)-corrected)", f"{st['ols']['p']}"),
            ("Lag-1 autocorrelation (corrected)", f"{st['ols']['r1']}"),
            ("Effective sample size", f"{st['ols']['n_eff']}"),
            ("Significant (both tests agree)", str(st["significant"])),
            ("Years needed to detect", f"{st['years_needed']}"),
            ("Units", result["units"]),
        ]
    return rows


def to_csv(result: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["# MegavirTrace export"])
    for k, v in _summary_rows(result):
        w.writerow([f"# {k}", v])
    if result["kind"] == "trend":
        s = result["series"]
        w.writerow([])
        w.writerow(["label", "t_decimal_year", f"value ({result['units']})", "trend_line"])
        for row in zip(s["labels"], s["t"], s["values"], s["trend_line"], strict=True):
            w.writerow(row)
        m = result["monthly"]
        w.writerow([])
        w.writerow(["month", f"regional_mean ({m['units']})", "coverage_share"])
        for row in zip(m["labels"], m["values"], m["coverage"], strict=True):
            w.writerow(row)
    else:
        c = result["comparison"]
        w.writerow([])
        w.writerow(["label", "region_a", "region_b", "difference_a_minus_b"])
        for row in zip(c["labels"], c["a"], c["b"], c["diff"], strict=True):
            w.writerow(row)
    return buf.getvalue().encode("utf-8")


def to_xlsx(result: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["MegavirTrace result"])
    ws["A1"].font = Font(bold=True, size=14)
    for k, v in _summary_rows(result):
        ws.append([k, v])
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 110
    if result["kind"] == "trend":
        s = result["series"]
        ws2 = wb.create_sheet("Series")
        ws2.append(["label", "t (decimal year)", f"value ({result['units']})", "trend line"])
        for row in zip(s["labels"], s["t"], s["values"], s["trend_line"], strict=True):
            ws2.append(list(row))
        m = result["monthly"]
        ws3 = wb.create_sheet("Monthly")
        ws3.append(["month", f"regional mean ({m['units']})", "coverage share"])
        for row in zip(m["labels"], m["values"], m["coverage"], strict=True):
            ws3.append(list(row))
    else:
        c = result["comparison"]
        ws2 = wb.create_sheet("Difference")
        ws2.append(["label", "region A", "region B", "A minus B"])
        for row in zip(c["labels"], c["a"], c["b"], c["diff"], strict=True):
            ws2.append(list(row))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(result: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .chart import series_chart_drawing

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="MegavirTrace result",
        author="MegavirTrace",
    )
    ss = getSampleStyleSheet()
    body = ss["BodyText"]
    story = [
        Paragraph("MegavirTrace", ss["Title"]),
        Paragraph(_esc(result["verdict"]["headline"]), ss["Heading2"]),
    ]
    for s in result["verdict"]["sentences"]:
        story.append(Paragraph(_esc(s), body))
    story.append(Spacer(1, 6))
    if result["kind"] == "trend":
        story.append(series_chart_drawing(result))
        story.append(Spacer(1, 6))
    rows = [
        [Paragraph(f"<b>{_esc(k)}</b>", body), Paragraph(_esc(v), body)]
        for k, v in _summary_rows(result)
        if k not in ("Finding", "Headline")
    ]
    t = Table(rows, colWidths=[55 * mm, 115 * mm])
    t.setStyle(
        TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")])
    )
    story.append(t)
    doc.build(story)
    return buf.getvalue()


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_notebook(result: dict) -> bytes:
    import nbformat
    from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

    stats_src = (ENGINE_DIR / "stats.py").read_text()
    agg_src = (ENGINE_DIR / "aggregate.py").read_text()
    table_path = ENGINE_DIR / "data" / "ar1_ratio.npz"
    import base64

    table_b64 = base64.b64encode(table_path.read_bytes()).decode() if table_path.exists() else ""
    payload = {
        "kind": result["kind"],
        "request": result["request"],
        "provenance": result["provenance"],
    }
    if result["kind"] == "trend":
        payload["monthly"] = result["monthly"]
        payload["expected"] = {
            "sen_per_decade": result["stats"]["per_decade"]["sen"],
            "ols_per_decade": result["stats"]["per_decade"]["ols"],
            "p_mk": result["stats"]["mk"]["p"],
            "p_ols": result["stats"]["ols"]["p"],
            "significant": result["stats"]["significant"],
            "n": result["stats"]["n"],
        }
        payload["agg"] = result["variable"]["agg"]
    else:
        payload["series"] = {k: result["comparison"][k] for k in ("labels", "t", "a", "b", "diff")}
        payload["expected"] = {
            "diff_per_decade": result["comparison"]["difference"]["slope_per_decade"],
            "significant": result["comparison"]["difference"]["significant"],
        }
        payload["per_year"] = result["comparison"]["stats_diff"]["per_year"]

    nb = new_notebook()
    nb.cells = [
        new_markdown_cell(
            f"# MegavirTrace: recompute this result\n\n**{result['verdict']['headline']}**\n\n"
            f"Fingerprint `{result['id']}` · data version {result['provenance']['data_version']} "
            f"({result['provenance']['data_kind']}) · engine {result['provenance']['engine_version']}\n\n"
            f"Source: {result['provenance']['citation']}\n\n"
            "This notebook needs only NumPy and SciPy. It contains the regional monthly series the app used "
            "and an exact copy of the app's trend engine, recomputes every number and checks it against the app."
        ),
        new_code_cell(
            "import json, base64, io, sys, types\nimport numpy as np\n"
            f"DATA = json.loads({json.dumps(json.dumps(payload))})\nDATA['expected']"
        ),
        new_markdown_cell(
            "## The engine (copied verbatim from the app)\nThe AR(1) variance-ratio table is embedded so results match exactly."
        ),
        new_code_cell(
            "import pathlib, tempfile\n"
            "pkg = pathlib.Path(tempfile.mkdtemp()) / 'mt_engine'\n(pkg / 'data').mkdir(parents=True)\n"
            f"(pkg / 'data' / 'ar1_ratio.npz').write_bytes(base64.b64decode({table_b64!r}))\n"
            f"(pkg / 'stats.py').write_text({stats_src!r})\n"
            f"(pkg / 'aggregate.py').write_text({agg_src!r})\n"
            "(pkg / '__init__.py').write_text('')\n"
            "sys.path.insert(0, str(pkg.parent))\n"
            "from mt_engine.stats import analyse_trend, trend_test\nfrom mt_engine.aggregate import build_series"
        ),
        new_markdown_cell("## Recompute and check"),
        new_code_cell(_RECOMPUTE),
    ]
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    return nbformat.writes(nb).encode()


_RECOMPUTE = """r = DATA["request"]
exp = DATA["expected"]
if DATA["kind"] == "trend":
    m = DATA["monthly"]
    idx = np.array([int(l[:4]) * 12 + int(l[5:7]) - 1 for l in m["labels"]])
    vals = np.array([np.nan if v is None else v for v in m["values"]], float)
    cov = np.array([0.0 if c is None else c for c in m["coverage"]], float)
    s = build_series(idx, vals, r["mode"], r["season"], r["start_year"], r["end_year"], DATA["agg"], cov)
    st = analyse_trend(s.t, s.y, s.years, s.labels, s.per_year, s.group)
    got = {"sen_per_decade": st.sen.slope * 10, "ols_per_decade": st.ols.slope * 10,
           "p_mk": st.mk.p, "p_ols": st.ols.p, "significant": st.significant, "n": st.n}
else:
    sr = DATA["series"]
    t = np.array(sr["t"], float); d = np.array(sr["diff"], float)
    ols, mk, sen, agree, sig = trend_test(t, d, DATA["per_year"])
    got = {"diff_per_decade": sen.slope * 10, "significant": sig}
ok = True
for k, v in exp.items():
    g = got[k]
    same = (g == v) if isinstance(v, (bool, int)) and not isinstance(v, float) else abs(g - v) <= 1e-9 * max(1.0, abs(v))
    ok &= bool(same)
    print(f"{k:16s} app={v!r:28} notebook={g!r:28} {'OK' if same else 'MISMATCH'}")
print("\\nAll numbers reproduced." if ok else "\\nSome numbers differ: please report this.")"""


def related_csv(result: dict) -> bytes:
    rel = result["relationship"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["# MegavirTrace: moves together (related, not caused by)"])
    w.writerow(["# Headline", result["verdict"]["headline"]])
    for x in result["verdict"]["sentences"]:
        w.writerow(["# Finding", x])
    for x in result["verdict"]["caveats"]:
        w.writerow(["# Caveat", x])
    for side in ("a", "b"):
        pv = result["provenance"][side]
        w.writerow(
            [
                f"# Source {side.upper()}",
                pv["product"],
                pv.get("doi") or pv.get("paper_doi") or "",
                pv["citation"],
            ]
        )
    w.writerow([])
    w.writerow(["lag_months (B follows A when positive)", "r", "p_single_lag", "pairs"])
    for row in zip(rel["lags"], rel["r"], rel["p"], rel["n"], strict=True):
        w.writerow(row)
    w.writerow([])
    w.writerow(["month", "A standardized anomaly", "B standardized anomaly"])
    for row in zip(rel["labels"], rel["a_std"], rel["b_std"], strict=True):
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


class ExportNotAvailable(ValueError):
    pass


def export_report(result: dict, fmt: str) -> tuple[bytes, str, str]:
    if result.get("kind") == "related":
        name = f"megavirtrace_related_{result['id'][:8]}"
        if fmt == "csv":
            return related_csv(result), "text/csv; charset=utf-8", name + ".csv"
        if fmt == "json":
            return json.dumps(result, indent=1).encode(), "application/json", name + ".json"
        raise ExportNotAvailable("This result can be downloaded as CSV or JSON.")
    slug = _slug(result)
    if fmt == "csv":
        return to_csv(result), "text/csv; charset=utf-8", slug + ".csv"
    if fmt == "xlsx":
        return (
            to_xlsx(result),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            slug + ".xlsx",
        )
    if fmt == "pdf":
        return to_pdf(result), "application/pdf", slug + ".pdf"
    if fmt == "ipynb":
        return to_notebook(result), "application/x-ipynb+json", slug + ".ipynb"
    return json.dumps(result, indent=1).encode(), "application/json", slug + ".json"
