"""
A web page of a draft program for the athlete to read and comment on before it goes on the
calendar. It is published as a Claude artifact from a Claude Code session, the athlete leaves
comments on it, and the coach changes the draft and publishes the page again to the same link.

build_html takes a program as saved by programs.validate and returns the page as text. It holds
only what the plan says. No rides, weight, heart rate or intake answers go on it, because the
page lives on claude.ai and not on this machine. Every element a comment might point at (a phase,
a day of the typical week, a week, a checkpoint) has a stable id and a visible label like
"Base, Tue" or "Week 6", so a comment can say which part it means.
"""
from __future__ import annotations

from datetime import date
from html import escape

import programs
import strength_text
from program_pdf import PHASE_COLORS


def _e(value) -> str:
    return escape(str(value or ""), quote=True)


def _ordinal(n: int) -> str:
    return {2: "second", 3: "third", 4: "fourth"}.get(n, f"{n}th")


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-") or "x"


def phase_load(p: dict) -> str:
    """One sentence on hours and weekly training load for a phase."""
    if not p["week_template"]:
        return "A break from structured riding. Ride for fun if you feel like it."
    out = f"About {p['weekly_hours']:g} hours a week. Training load {p['weekly_tss_start']:.0f}"
    if p["weekly_tss_start"] != p["weekly_tss_end"]:
        out += f" rising to {p['weekly_tss_end']:.0f}"
    out += " a week."
    if p["recovery_every"]:
        out += f" Every {_ordinal(p['recovery_every'])} week is lighter, about 60 percent."
    return out


def _bullets(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"


def _chart(weeks: list[dict], colors: dict) -> str:
    """Weekly TSS as bars, all on one scale, with the top value labelled."""
    top = max([w["tss"] for w in weeks] + [1])
    bars = []
    for w in weeks:
        pct = round(100 * w["tss"] / top, 1)
        tip = f"Week {w['week']}, {w['phase']}, {w['tss'] or 'off'}" + (" TSS" if w["tss"] else "")
        cls = "bar light" if w["recovery"] else "bar"
        bars.append(f'<div class="{cls}" style="height:{pct}%;--c:{colors[w["phase"]]}" '
                    f'title="{_e(tip)}"></div>')
    return (f'<figure class="chart" aria-label="Weekly training load">'
            f'<div class="axis"><span>{top:.0f}</span><span>0</span></div>'
            f'<div class="bars">{"".join(bars)}</div>'
            f'<div class="ticks"><span>Week 1</span><span>Week {len(weeks)}</span></div></figure>')


def build_html(program: dict, athlete_name: str = "", today: date | None = None) -> str:
    today = today or date.today()
    weeks = programs.week_plan(program)
    phases = program["phases"]
    colors = {p["name"]: PHASE_COLORS[i % len(PHASE_COLORS)] for i, p in enumerate(phases)}
    who = athlete_name.strip()
    version = program.get("version")
    eyebrow = "Draft plan" + (f" for {who}" if who else "") + (f" · version {version}" if version else "")
    title = f"{who} training plan" if who else program["title"]

    out = [f"<title>{_e(title)}</title>",
           '<meta name="claude:viewport-fit-sides" content="cover">',
           '<link rel="preconnect" href="https://fonts.googleapis.com">',
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700'
           '&family=Barlow:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@500&display=swap">',
           f"<style>{CSS}</style>", '<main class="page">']

    # The idea
    out += [f'<header class="top"><p class="eyebrow">{_e(eyebrow)}</p>',
            f"<h1>{_e(program['title'])}</h1>",
            f'<p class="meta">{_e(programs.friendly_range(program))} · {program["total_weeks"]} weeks · '
            f'{len(phases)} phases</p></header>',
            '<aside class="ask"><h2>Tell me what to change</h2><p>This is a draft. Nothing is on your '
            'calendar yet. Leave a comment on anything that does not fit your life or feels wrong, and '
            'name the part you mean, like <b>Week 6</b> or <b>Base, Tue</b>. I will change the plan and '
            'update this page at the same link.</p></aside>',
            '<section id="goal"><h2>The goal</h2>', f"<p>{_e(program['goal'])}</p>",
            f"<h3>How it is built</h3><p>{_e(program['overview'])}</p>"]
    if program["assumptions"]:
        out += ['<h3>What this plan assumes</h3>', _bullets(program["assumptions"]),
                '<p class="hint">If any of these are wrong, say so first. The rest depends on them.</p>']
    out.append("</section>")

    # At a glance
    legend = "".join(f'<li><i style="--c:{colors[p["name"]]}"></i>{_e(p["name"])}</li>' for p in phases)
    out += ['<section id="glance"><h2>The program at a glance</h2>',
            '<p class="hint">Weekly training load (TSS). Paler bars are lighter weeks.</p>',
            _chart(weeks, colors), f'<ul class="legend">{legend}</ul></section>']

    # Each phase
    n = 0
    for p in phases:
        first, last = weeks[n], weeks[n + p["weeks"] - 1]
        n += p["weeks"]
        pid = f"phase-{_slug(p['name'])}"
        span = (f"Weeks {first['week']} to {last['week']}" if p["weeks"] > 1 else f"Week {first['week']}")
        out += [f'<section class="phase" id="{pid}" style="--c:{colors[p["name"]]}">',
                f'<div class="phase-head"><h2>{_e(p["name"])}</h2>'
                f'<p class="meta">{span} · {_e(programs.span_label(first["start"], last["end"]))}</p></div>',
                f'<p class="focus">{_e(p["focus"])}</p><p>{_e(p["why"])}</p>',
                f'<p class="load">{_e(phase_load(p))}</p>']
        if p["week_template"]:
            mid = (p["weekly_tss_start"] + p["weekly_tss_end"]) / 2
            total = sum(d["share"] for d in p["week_template"]) or 1.0
            out.append('<h3>A typical week</h3><ol class="days">')
            for d in p["week_template"]:
                out.append(
                    f'<li id="{pid}-{d["day"].lower()}"><div class="day-head">'
                    f'<span class="day">{_e(d["day"])}</span><b>{_e(d["name"])}</b>'
                    f'<span class="tss">{mid * d["share"] / total:.0f} TSS</span></div>'
                    f'<p>{_e(d["description"])}</p>'
                    f'<p class="why">{_e(d["purpose"])}</p>'
                    f'<p class="feel">{_e(d["feel"])}</p>'
                    f'<p class="ref">{_e(p["name"])}, {_e(d["day"])}</p></li>')
            out.append("</ol>")
        if p["strength"]:
            s = p["strength"]
            lines = [strength_text.line(e) + (f" ({strength_text.note(e)})" if strength_text.note(e) else "")
                     for e in s["exercises"]]
            out += [f'<h3 id="{pid}-strength">Strength</h3>',
                    f"<p>{_e(s['name'])}, {_e(', '.join(s['days']))}, about {s['duration_minutes']} minutes. "
                    f"{_e(s['purpose'])}</p>", _bullets(lines)]
        if p["key_workouts"]:
            out += ["<h3>Key sessions to focus on</h3>", _bullets(p["key_workouts"])]
        if p["success_markers"]:
            out += ["<h3>Signs it is working</h3>", _bullets(p["success_markers"])]
        out.append("</section>")

    by_week = {w["week"]: w for w in weeks}
    if program["checkpoints"]:
        out.append('<section id="checkpoints"><h2>Checkpoints</h2><ol class="checks">')
        for c in program["checkpoints"]:
            out.append(f'<li id="checkpoint-week-{c["week"]}"><span class="when">Week {c["week"]}<br>'
                       f'{_e(programs.day_label(by_week[c["week"]]["start"]))}</span>'
                       f'<div><b>{_e(c["what"])}</b><p>{_e(c["why"])}</p></div></li>')
        out.append("</ol></section>")

    # Week by week
    cp_weeks = {c["week"]: c["what"] for c in program["checkpoints"]}
    rows = []
    for w in weeks:
        notes = (["Lighter week"] if w["recovery"] else []) + (["Set by hand"] if w.get("edited") else []) \
            + ([cp_weeks[w["week"]]] if w["week"] in cp_weeks else [])
        rows.append(f'<tr id="week-{w["week"]}" style="--c:{colors[w["phase"]]}"><th scope="row">{w["week"]}</th>'
                    f'<td>{_e(programs.span_label(w["start"], w["end"]))}</td><td>{_e(w["phase"])}</td>'
                    f'<td class="num">{w["hours"]:g}</td><td class="num">{w["tss"] or "Off"}</td>'
                    f'<td>{_e(", ".join(notes))}</td></tr>')
    out += ['<section id="weeks"><h2>Week by week</h2><div class="scroll"><table>',
            "<thead><tr><th>Week</th><th>Dates</th><th>Phase</th><th>Hours</th><th>TSS</th><th>Note</th></tr></thead>",
            f"<tbody>{''.join(rows)}</tbody></table></div></section>"]

    if program["notes"]:
        out += ['<section id="notes"><h2>Good to know</h2>', _bullets(program["notes"]), "</section>"]
    out += ['<section id="terms"><h2>Words used here</h2><dl>',
            "<dt>TSS</dt><dd>Training Stress Score. One hour flat out at your threshold is 100. "
            "It lets hard short rides and easy long rides be compared on one scale.</dd>",
            "<dt>Lighter week</dt><dd>A planned easier week so the work of the weeks before can sink in.</dd>",
            "</dl></section>",
            f'<footer>Draft made {_e(programs.day_label(today.isoformat()))}, {today.year}. '
            "It goes on your calendar only once we both agree.</footer></main>"]
    return "\n".join(out)


# Tokens first. Phase colours come from the PDF so both versions of a plan look alike.
# Layout: one readable column, phases as stripes of their own colour, the week table scrolls on its own.
CSS = """
:root{--bg:#F6F7FA;--surface:#FFFFFF;--ink:#1B2236;--muted:#5B6578;--line:#D5DAE5;--soft:#EDF0F6;
--accent:#2F6FDE;--display:'Barlow Condensed','Arial Narrow',sans-serif;
--body:'Barlow',system-ui,-apple-system,'Segoe UI',sans-serif;--mono:'IBM Plex Mono',ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#11151F;--surface:#181E2B;--ink:#E6E9F0;
--muted:#9AA3B5;--line:#2C3446;--soft:#1F2636;--accent:#7FA8F0;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#11151F;--surface:#181E2B;--ink:#E6E9F0;--muted:#9AA3B5;--line:#2C3446;
--soft:#1F2636;--accent:#7FA8F0;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font:400 1rem/1.55 var(--body)}
.page{max-width:44rem;margin:0 auto;padding-block:2rem 3rem;padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px));display:flex;flex-direction:column;gap:2.25rem}
h1,h2{font-family:var(--display);font-weight:700;line-height:1.1;text-wrap:balance;margin:0}
h1{font-size:clamp(2rem,6vw,2.75rem)}h2{font-size:1.6rem}
h3{font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:1.4rem 0 .5rem}
p{margin:.5rem 0}ul{margin:.4rem 0;padding-left:1.2rem}li{margin:.2rem 0}
.eyebrow{font-size:.8rem;text-transform:uppercase;letter-spacing:.1em;color:var(--accent);font-weight:600;margin:0 0 .4rem}
.meta{color:var(--muted);margin:.3rem 0 0;font-variant-numeric:tabular-nums}
.hint{color:var(--muted);font-size:.9rem}
.ask{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:1rem 1.2rem}
.ask h2{font-size:1.25rem}.ask p{margin-bottom:0}
.chart{margin:1rem 0 .5rem;display:grid;grid-template-columns:auto 1fr;grid-template-rows:9rem auto;gap:.3rem .5rem}
.axis{display:flex;flex-direction:column;justify-content:space-between;font:500 .7rem var(--mono);color:var(--muted);text-align:right}
.bars{display:flex;align-items:flex-end;gap:2px;border-bottom:1px solid var(--line);border-top:1px dashed var(--line)}
.bar{flex:1;min-width:0;background:var(--c);border-radius:2px 2px 0 0}.bar.light{opacity:.45}
.ticks{grid-column:2;display:flex;justify-content:space-between;font:500 .7rem var(--mono);color:var(--muted)}
.legend{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:.4rem 1rem;font-size:.9rem}
.legend i{display:inline-block;width:.7rem;height:.7rem;border-radius:2px;background:var(--c);margin-right:.35rem}
.phase{border-top:4px solid var(--c);padding-top:.9rem}
.phase-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:.25rem 1rem}
.focus{font-weight:600}.load{color:var(--muted);font-size:.92rem}
.days{list-style:none;padding:0;display:flex;flex-direction:column;gap:.6rem}
.days li{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:.75rem .9rem;margin:0}
.days p{margin:.25rem 0}
.day-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:.2rem .6rem}
.day{font:700 .95rem var(--display);text-transform:uppercase;letter-spacing:.06em;color:var(--c)}
.tss{margin-left:auto;font:500 .8rem var(--mono);color:var(--muted)}
.why{color:var(--ink)}.feel{color:var(--muted);font-style:italic}
.ref{font:500 .7rem var(--mono);color:var(--muted);text-align:right}
.checks{list-style:none;padding:0;display:flex;flex-direction:column;gap:.75rem}
.checks li{display:grid;grid-template-columns:5.5rem 1fr;gap:1rem;margin:0}
.checks p{margin:.15rem 0 0;color:var(--muted)}
.when{font:500 .8rem/1.4 var(--mono);color:var(--muted)}
.scroll{overflow-x:auto;margin-top:.75rem}
table{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:.4rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}
thead th{font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
tbody th{border-left:3px solid var(--c)}td.num{text-align:right;white-space:nowrap}
dl{margin:.5rem 0}dt{font-weight:600}dd{margin:0 0 .6rem;color:var(--muted)}
footer{color:var(--muted);font-size:.85rem;border-top:1px solid var(--line);padding-top:1rem}
"""
