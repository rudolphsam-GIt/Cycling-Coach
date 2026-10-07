"""
A printable PDF of a multi month program: the idea in a page, a chart of the weekly load,
each phase with its typical week, the checkpoints and a week by week table.

build_pdf takes a program as saved by programs.validate and returns the file as bytes.
Everything the coach wrote goes through _t, which escapes it for reportlab and swaps any
character the standard PDF fonts cannot draw.
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

import programs
from metrics import explain

INK = colors.HexColor("#1B2236")
MUTED = colors.HexColor("#5B6578")
LINE = colors.HexColor("#D5DAE5")
SOFT = colors.HexColor("#F3F5FA")
ACCENT = colors.HexColor("#2F6FDE")
PHASE_COLORS = ["#2F6FDE", "#16A394", "#E09A1A", "#D9534F", "#8A5CD0", "#3B8EA5", "#C2688B", "#6B8E23"]

REPLACEMENTS = {"→": "to", "≥": ">=", "≤": "<=", "−": "-", "‑": "-",
                " ": " ", " ": " ", " ": " ", "→": "to"}


def _plain(value) -> str:
    """Text the standard PDF fonts can draw. Characters outside Windows Latin 1 are swapped."""
    s = "" if value is None else str(value)
    for old, new in REPLACEMENTS.items():
        s = s.replace(old, new)
    return s.encode("cp1252", "replace").decode("cp1252")


def _t(value) -> str:
    return escape(_plain(value))


def _ordinal(n: int) -> str:
    return {2: "2nd", 3: "3rd", 4: "4th"}.get(n, f"{n}th")


def phase_color(index: int):
    return colors.HexColor(PHASE_COLORS[index % len(PHASE_COLORS)])


def _styles() -> dict:
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK,
                          alignment=TA_LEFT)
    return {
        "base": base,
        "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=24, leading=28),
        "sub": ParagraphStyle("sub", parent=base, fontSize=11, leading=15, textColor=MUTED),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=15, leading=19,
                             spaceBefore=14, spaceAfter=6),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=12, leading=16,
                             spaceBefore=8, spaceAfter=3),
        "label": ParagraphStyle("label", parent=base, fontName="Helvetica-Bold", fontSize=8, leading=10,
                                textColor=MUTED, spaceBefore=6, spaceAfter=2),
        "small": ParagraphStyle("small", parent=base, fontSize=8.5, leading=11.5, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.5, leading=11),
        "cellb": ParagraphStyle("cellb", parent=base, fontName="Helvetica-Bold", fontSize=8.5, leading=11),
        "head": ParagraphStyle("head", parent=base, fontName="Helvetica-Bold", fontSize=8, leading=10,
                               textColor=colors.white),
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=12, bulletIndent=2, spaceAfter=2),
    }


def _bullets(items: list[str], st: dict) -> list:
    return [Paragraph(_t(i), st["bullet"], bulletText="•") for i in items]


def _table(rows: list[list], widths: list[float], st: dict, header: bool = True, zebra: bool = True) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), INK)]
    if zebra:
        for r in range(1 if header else 0, len(rows)):
            if r % 2 == 0:
                style.append(("BACKGROUND", (0, r), (-1, r), SOFT))
    t.setStyle(TableStyle(style))
    return t


def _nice_top(value: float) -> float:
    if value <= 0:
        return 100.0
    step = 50 if value < 400 else 100 if value < 1000 else 250
    return float(-(-value // step) * step)


def load_chart(program: dict, ctl_by_week: dict | None, width: float, height: float = 175) -> Drawing:
    """Weekly training load as bars coloured by phase, lighter weeks paler, with the projected
    fitness (CTL) as a line against the right hand scale."""
    weeks = programs.week_plan(program)
    names = [p["name"] for p in program["phases"]]
    d = Drawing(width, height)
    left, right, bottom, top = 34, 34, 24, 10
    w, h = width - left - right, height - bottom - top
    max_tss = _nice_top(max([x["tss"] for x in weeks] + [1]))
    max_ctl = _nice_top(max(ctl_by_week.values())) if ctl_by_week else None

    for i in range(5):
        y = bottom + h * i / 4
        d.add(Line(left, y, left + w, y, strokeColor=LINE, strokeWidth=0.4))
        d.add(String(left - 4, y - 3, f"{max_tss * i / 4:.0f}", fontName="Helvetica", fontSize=7,
                     fillColor=MUTED, textAnchor="end"))
        if max_ctl:
            d.add(String(left + w + 4, y - 3, f"{max_ctl * i / 4:.0f}", fontName="Helvetica", fontSize=7,
                         fillColor=ACCENT, textAnchor="start"))
    n = len(weeks)
    slot = w / n
    for k, wk in enumerate(weeks):
        base = phase_color(names.index(wk["phase"]))
        fill = colors.Color(base.red, base.green, base.blue, alpha=0.4 if wk["recovery"] else 0.95)
        bar_h = h * wk["tss"] / max_tss
        d.add(Rect(left + k * slot + slot * 0.12, bottom, slot * 0.76, bar_h, fillColor=fill, strokeColor=None))
    step = max(1, round(n / 12))
    for k in range(0, n, step):
        d.add(String(left + k * slot + slot / 2, bottom - 11, str(k + 1), fontName="Helvetica",
                     fontSize=7, fillColor=MUTED, textAnchor="middle"))
    if max_ctl:
        pts = []
        for k, wk in enumerate(weeks):
            if wk["week"] in ctl_by_week:
                pts += [left + k * slot + slot / 2, bottom + h * ctl_by_week[wk["week"]] / max_ctl]
        if len(pts) >= 4:
            d.add(PolyLine(pts, strokeColor=ACCENT, strokeWidth=1.6))
    d.add(String(left, height - 2, "Weekly training load (TSS)", fontName="Helvetica-Bold", fontSize=7.5,
                 fillColor=MUTED))
    if max_ctl:
        d.add(String(left + w, height - 2, "Projected fitness (CTL)", fontName="Helvetica-Bold", fontSize=7.5,
                     fillColor=ACCENT, textAnchor="end"))
    d.add(String(left + w / 2, 2, "Week of the program", fontName="Helvetica", fontSize=7,
                 fillColor=MUTED, textAnchor="middle"))
    return d


def _legend(program: dict, st: dict) -> Table:
    cells = []
    for i, p in enumerate(program["phases"]):
        chip = Drawing(9, 9)
        chip.add(Rect(0, 0, 9, 9, fillColor=phase_color(i), strokeColor=None))
        cells.append([chip, Paragraph(_t(p["name"]), st["small"])])
    flat = [c for pair in cells for c in pair]
    cols = 4
    per = cols * 2
    rows = [flat[i:i + per] for i in range(0, len(flat), per)]
    for r in rows:
        r += [""] * (per - len(r))
    widths = [12, 1.55 * inch] * cols
    t = Table(rows, colWidths=widths)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return t


def _glossary(st: dict) -> list:
    out = [Paragraph("How to read the numbers", st["h1"])]
    for key, label in (("ftp", "FTP"), ("tss", "TSS"), ("ctl", "CTL, your fitness")):
        t = explain.TERMS.get(key)
        if t:
            out.append(Paragraph(f"<b>{_t(label)}.</b> {_t(t['what'])}", st["base"]))
            out.append(Spacer(1, 3))
    out.append(Paragraph("A lighter week is on purpose. Fitness is built while you recover from the hard "
                         "weeks, so protect those weeks as much as the hard ones.", st["base"]))
    return out


def build_pdf(program: dict, ctl_by_week: dict | None = None, subtitle: str | None = None) -> bytes:
    """The program as a PDF. `ctl_by_week` ({week: CTL}) adds the projected fitness line."""
    st = _styles()
    buf = io.BytesIO()
    margin = 0.7 * inch
    doc = BaseDocTemplate(buf, pagesize=letter, leftMargin=margin, rightMargin=margin,
                          topMargin=0.75 * inch, bottomMargin=0.75 * inch,
                          title=_plain(program["title"]), author="Cycling Coach")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    title_short = _plain(program["title"])[:70]

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, 0.45 * inch, title_short)
        canvas.drawRightString(letter[0] - margin, 0.45 * inch, f"Page {canvas.getPageNumber()}")
        canvas.setStrokeColor(LINE)
        canvas.line(margin, 0.62 * inch, letter[0] - margin, 0.62 * inch)
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=footer)])
    width = doc.width
    weeks = programs.week_plan(program)
    story: list = []

    # Title and the idea in a page
    story += [Paragraph(_t(program["title"]), st["title"]), Spacer(1, 4),
              Paragraph(_t(f"{programs.friendly_range(program)} · {program['total_weeks']} weeks · "
                           f"{len(program['phases'])} phases"
                           + (f" · {subtitle}" if subtitle else "")), st["sub"]),
              Spacer(1, 10),
              Paragraph("The goal", st["label"]), Paragraph(_t(program["goal"]), st["base"]),
              Paragraph("How it is built", st["label"]), Paragraph(_t(program["overview"]), st["base"])]
    if program["assumptions"]:
        story += [Paragraph("What this plan assumes", st["label"])] + _bullets(program["assumptions"], st)

    # At a glance
    story += [Paragraph("The program at a glance", st["h1"]),
              load_chart(program, ctl_by_week, width), Spacer(1, 2), _legend(program, st), Spacer(1, 8)]
    rows = [[Paragraph(h, st["head"]) for h in ("Phase", "Weeks", "Dates", "Hours a week", "TSS a week", "Focus")]]
    n = 0
    for i, p in enumerate(program["phases"]):
        first, last = weeks[n], weeks[n + p["weeks"] - 1]
        n += p["weeks"]
        tss = (f"{p['weekly_tss_start']:.0f}" if p["weekly_tss_start"] == p["weekly_tss_end"]
               else f"{p['weekly_tss_start']:.0f} to {p['weekly_tss_end']:.0f}")
        rows.append([Paragraph(_t(p["name"]), st["cellb"]),
                     Paragraph(_t(f"{first['week']} to {last['week']}" if p["weeks"] > 1 else str(first["week"])), st["cell"]),
                     Paragraph(_t(programs.span_label(first["start"], last["end"])), st["cell"]),
                     Paragraph(_t(f"{p['weekly_hours']:g}"), st["cell"]),
                     Paragraph(_t(tss if p["weekly_tss_start"] or p["weekly_tss_end"] else "Off"), st["cell"]),
                     Paragraph(_t(p["focus"]), st["cell"])])
    t = _table(rows, [0.95 * inch, 0.55 * inch, 1.15 * inch, 0.65 * inch, 0.75 * inch,
                      width - 4.05 * inch], st)
    for i in range(len(program["phases"])):
        t.setStyle(TableStyle([("LINEBEFORE", (0, i + 1), (0, i + 1), 3, phase_color(i))]))
    story.append(t)

    # Each phase
    n = 0
    for i, p in enumerate(program["phases"]):
        first, last = weeks[n], weeks[n + p["weeks"] - 1]
        n += p["weeks"]
        wk_label = f"Weeks {first['week']} to {last['week']}" if p["weeks"] > 1 else f"Week {first['week']}"
        when = f"{wk_label} · {programs.span_label(first['start'], last['end'])}"
        head = Table([[Paragraph(f"<font color='white'><b>{_t(p['name'])}</b></font>", st["h2"]),
                       Paragraph(f"<font color='white'>{_t(when)}</font>", st["cell"])]],
                     colWidths=[width * 0.4, width * 0.6])
        head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), phase_color(i)),
                                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                  ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                                  ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
        block = [Spacer(1, 8), head, Spacer(1, 6),
                 Paragraph(f"<b>{_t(p['focus'])}</b>", st["base"]), Spacer(1, 2),
                 Paragraph(_t(p["why"]), st["base"])]
        story.append(KeepTogether(block))
        if not p["week_template"]:
            load = "A break from structured riding. Ride for fun if you feel like it."
        else:
            load = f"About {p['weekly_hours']:g} hours a week. Training load {p['weekly_tss_start']:.0f}"
            if p["weekly_tss_start"] != p["weekly_tss_end"]:
                load += f" rising to {p['weekly_tss_end']:.0f}"
            load += " a week."
            if p["recovery_every"]:
                load += f" Every {_ordinal(p['recovery_every'])} week is lighter, about 60 percent."
        story += [Spacer(1, 3), Paragraph(_t(load), st["small"])]

        if p["week_template"]:
            mid = (p["weekly_tss_start"] + p["weekly_tss_end"]) / 2
            total = sum(d["share"] for d in p["week_template"]) or 1.0
            rows = [[Paragraph(h, st["head"]) for h in ("Day", "Session", "What it is for and how it feels", "TSS")]]
            for d in p["week_template"]:
                rows.append([Paragraph(_t(d["day"]), st["cellb"]),
                             Paragraph(f"<b>{_t(d['name'])}</b><br/>{_t(d['description'])}", st["cell"]),
                             Paragraph(f"{_t(d['purpose'])}<br/><i>{_t(d['feel'])}</i>", st["cell"]),
                             Paragraph(_t(f"{mid * d['share'] / total:.0f}"), st["cell"])])
            story += [Paragraph("A typical week", st["label"]),
                      _table(rows, [0.45 * inch, 2.15 * inch, width - 3.2 * inch, 0.6 * inch], st)]
        if p["strength"]:
            s = p["strength"]
            ex = ", ".join(f"{e['name']} {e['sets']}x{e['reps']}" for e in s["exercises"])
            story += [Paragraph("Strength", st["label"]),
                      Paragraph(_t(f"{s['name']}, {', '.join(s['days'])}, about {s['duration_minutes']} minutes. {s['purpose']}"),
                                st["base"]),
                      Paragraph(_t(ex), st["small"])]
        if p["key_workouts"]:
            story += [Paragraph("Key sessions to focus on", st["label"])] + _bullets(p["key_workouts"], st)
        if p["success_markers"]:
            story += [Paragraph("Signs it is working", st["label"])] + _bullets(p["success_markers"], st)

    # Checkpoints
    if program["checkpoints"]:
        by_week = {w["week"]: w for w in weeks}
        rows = [[Paragraph(h, st["head"]) for h in ("Week", "Date", "Checkpoint", "Why")]]
        for c in program["checkpoints"]:
            rows.append([Paragraph(_t(str(c["week"])), st["cellb"]),
                         Paragraph(_t(programs.day_label(by_week[c["week"]]["start"])), st["cell"]),
                         Paragraph(_t(c["what"]), st["cellb"]), Paragraph(_t(c["why"]), st["cell"])])
        story += [KeepTogether([Paragraph("Checkpoints", st["h1"]),
                                _table(rows, [0.5 * inch, 0.7 * inch, 2.0 * inch, width - 3.2 * inch], st)])]

    # Week by week
    story.append(PageBreak())
    story.append(Paragraph("Week by week", st["h1"]))
    cp_weeks = {c["week"]: c["what"] for c in program["checkpoints"]}
    names = [p["name"] for p in program["phases"]]
    rows = [[Paragraph(h, st["head"]) for h in ("Week", "Dates", "Phase", "Hours", "TSS", "Note")]]
    for w in weeks:
        notes = []
        if w["recovery"]:
            notes.append("Lighter week")
        if w.get("edited"):
            notes.append("Set by you")
        if w["week"] in cp_weeks:
            notes.append(cp_weeks[w["week"]])
        rows.append([Paragraph(_t(str(w["week"])), st["cellb"]), Paragraph(_t(programs.span_label(w["start"], w["end"])), st["cell"]),
                     Paragraph(_t(w["phase"]), st["cell"]), Paragraph(_t(f"{w['hours']:g}"), st["cell"]),
                     Paragraph(_t(str(w["tss"]) if w["tss"] else "Off"), st["cell"]),
                     Paragraph(_t(", ".join(notes)), st["cell"])])
    t = _table(rows, [0.45 * inch, 1.3 * inch, 1.2 * inch, 0.5 * inch, 0.5 * inch, width - 3.95 * inch], st)
    for r, w in enumerate(weeks, start=1):
        t.setStyle(TableStyle([("LINEBEFORE", (0, r), (0, r), 3, phase_color(names.index(w["phase"])))]))
    story.append(t)

    if program["notes"]:
        story += [Paragraph("Good to know", st["h1"])] + _bullets(program["notes"], st)
    story += _glossary(st)

    doc.build(story)
    return buf.getvalue()


def filename(program: dict) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in _plain(program["title"])).strip("_")
    return f"{safe or 'training_program'}.pdf"
