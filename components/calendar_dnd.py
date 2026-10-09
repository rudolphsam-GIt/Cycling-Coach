"""
The interactive month grid, as a Streamlit v2 component.

Python sends one JSON payload (components.calendar.build_payload) and gets back
three one shot events:

    move    {kind, id, from, to}   a workout or strength session was dropped on a day
    open    {kind, id, date}       a workout chip was clicked
    select  {date}                 an empty part of a day was clicked

The grid moves the chip on screen straight away. Python then saves the change
and sends fresh data, which redraws the grid from the database.

All text from the payload goes in with textContent. The only exception is the
hover tooltip, which components.calendar.day_tooltip has already escaped.
"""
from __future__ import annotations

import streamlit as st

HTML = '<div class="cal" role="grid" aria-label="Training calendar"></div>'

CSS = """
:host { display: block; }
.cal { position: relative; font-family: inherit; color: var(--text1); user-select: none; }
.cal * { box-sizing: border-box; }
.head, .grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }
.head div { text-align: center; font-size: 0.8rem; font-weight: 600; color: var(--text3);
            padding: 4px 0 6px; }
.cell { position: relative; min-height: 112px; padding: 6px 5px 5px; border-radius: 8px;
        border: 1px solid var(--border); cursor: pointer; overflow: hidden;
        transition: border-color .12s, box-shadow .12s; }
.cell.out { opacity: .7; }
.cell:hover { border-color: var(--text3); }
.cell.today { border: 2px solid var(--accent); }
.cell.selected { box-shadow: 0 0 0 2px var(--text1) inset; }
.cell.drop-ok { border: 2px dashed var(--accent); background-image:
    linear-gradient(rgba(77,159,255,.18), rgba(77,159,255,.18)); }
.cell.drop-no { cursor: not-allowed; }
.race-bar { position: absolute; top: 0; left: 0; right: 0; height: 4px; background: var(--race); }
.top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.num { font-size: 0.85rem; font-weight: 700; }
.cell.out .num { color: var(--text3); font-weight: 500; }
.cell.today .num { color: var(--accent); }
.race-name { font-size: 0.7rem; font-weight: 600; color: var(--race); overflow: hidden;
             text-overflow: ellipsis; white-space: nowrap; max-width: 70%; }
.chips { display: flex; flex-direction: column; gap: 3px; }
.chip { display: flex; justify-content: space-between; align-items: center; gap: 4px;
        padding: 3px 6px; border-radius: 5px; font-size: 0.75rem; line-height: 1.25;
        background: var(--raised); border-left: 3px solid var(--c); outline: none; }
.chip .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip .tss { color: var(--text2); font-size: 0.7rem; flex: none; }
.chip .flag { color: var(--warn); font-weight: 800; font-size: 0.75rem; flex: none; margin-left: 2px; }
.chip.drag { cursor: grab; }
.chip.drag:hover, .chip.open:hover { filter: brightness(1.25); }
.chip.drag:active { cursor: grabbing; }
.chip.locked { opacity: .85; }
.chip.dragging { opacity: .35; }
.chip:focus-visible { box-shadow: 0 0 0 2px var(--accent); }
.chip.open { cursor: pointer; }
.more { font-size: 0.7rem; color: var(--text3); padding-left: 4px; }
.tip { position: absolute; z-index: 20; max-width: 300px; padding: 8px 10px; border-radius: 8px;
       background: var(--surface); border: 1px solid var(--border); color: var(--text1);
       font-size: 0.8rem; line-height: 1.45; pointer-events: none; display: none;
       box-shadow: 0 6px 20px rgba(0,0,0,.45); }
"""

JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector('.cal');
  if (!root || !data) return;
  for (const [k, v] of Object.entries(data.colors || {})) root.style.setProperty('--' + k, v);
  root.replaceChildren();

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  };
  const fire = (name, payload) => setTriggerValue(name, { ...payload, nonce: Date.now() });

  const head = el('div', 'head');
  for (const d of data.weekdays) head.append(el('div', '', d));
  const grid = el('div', 'grid');
  const tip = el('div', 'tip');
  root.append(head, grid, tip);

  let drag = null;
  let tipTimer = null;
  const hideTip = () => { clearTimeout(tipTimer); tip.style.display = 'none'; };
  const showTip = (cell, html) => {
    tip.innerHTML = html;               // escaped in Python by day_tooltip
    tip.style.display = 'block';
    const r = root.getBoundingClientRect();
    const c = cell.getBoundingClientRect();
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = c.right - r.left + 6;
    if (x + w > r.width) x = c.left - r.left - w - 6;     // flip to the left near the right edge
    if (x < 0) x = Math.max(0, Math.min(c.left - r.left, r.width - w));
    let y = c.top - r.top;
    if (y + h > root.offsetHeight) y = Math.max(0, root.offsetHeight - h);
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  };

  const cells = [];
  for (const day of data.days) {
    const cell = el('div', 'cell');
    cell.dataset.date = day.date;
    cell.setAttribute('role', 'gridcell');
    cell.style.backgroundColor = day.tint;
    if (!day.in_month) cell.classList.add('out');
    if (day.today) cell.classList.add('today');
    if (day.date === data.selected) cell.classList.add('selected');
    if (day.race) cell.append(el('div', 'race-bar'));

    const top = el('div', 'top');
    top.append(el('span', 'num', String(day.num)));
    if (day.race) top.append(el('span', 'race-name', day.race));
    cell.append(top);

    const chips = el('div', 'chips');
    for (const c of day.chips) {
      const chip = el('div', 'chip');
      chip.style.setProperty('--c', c.color);
      chip.append(el('span', 'name', c.label));
      if (c.tss) chip.append(el('span', 'tss', String(c.tss)));
      if (c.flag) {
        const f = el('span', 'flag', '!');
        f.title = c.flag;
        f.setAttribute('aria-label', c.flag);
        chip.append(f);
      }
      chip.dataset.kind = c.kind;
      chip.dataset.id = c.id;
      chip.classList.add('open');
      if (c.locked) chip.classList.add('locked');
      chip.tabIndex = 0;
      chip.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ' || e.key.toLowerCase() === 'm') {
          e.preventDefault();
          fire('open', { kind: c.kind, id: c.id, date: day.date });
        }
      });
      if (!c.locked) {
        chip.draggable = true;
        chip.classList.add('drag');
        chip.addEventListener('dragstart', (e) => {
          hideTip();
          drag = { kind: c.kind, id: c.id, from: day.date, node: chip };
          e.dataTransfer.effectAllowed = 'move';
          e.dataTransfer.setData('text/plain', c.kind + ':' + c.id);
          setTimeout(() => chip.classList.add('dragging'), 0);
        });
        chip.addEventListener('dragend', () => {
          chip.classList.remove('dragging');
          cells.forEach((n) => n.classList.remove('drop-ok', 'drop-no'));
          drag = null;
        });
      }
      chip.addEventListener('click', (e) => {
        e.stopPropagation();
        fire('open', { kind: c.kind, id: c.id, date: day.date });
      });
      chips.append(chip);
    }
    cell.append(chips);
    if (day.more) cell.append(el('div', 'more', '+' + day.more + ' more'));

    const canDrop = () => drag && !day.past && day.date !== drag.from;
    cell.addEventListener('dragover', (e) => {
      if (!drag) return;
      if (canDrop()) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; cell.classList.add('drop-ok'); }
      else cell.classList.add('drop-no');
    });
    cell.addEventListener('dragleave', () => cell.classList.remove('drop-ok', 'drop-no'));
    cell.addEventListener('drop', (e) => {
      e.preventDefault();
      cell.classList.remove('drop-ok', 'drop-no');
      if (!canDrop()) return;
      const d = drag;
      drag = null;
      d.node.classList.remove('dragging');
      cell.querySelector('.chips').append(d.node);      // move on screen now, Python redraws after saving
      d.node.dataset.moved = '1';
      fire('move', { kind: d.kind, id: d.id, from: d.from, to: day.date });
    });
    cell.addEventListener('click', () => fire('select', { date: day.date }));
    cell.addEventListener('mouseenter', () => {
      if (drag) return;
      clearTimeout(tipTimer);
      tipTimer = setTimeout(() => showTip(cell, day.tip), 250);
    });
    cell.addEventListener('mouseleave', hideTip);

    cells.push(cell);
    grid.append(cell);
  }
  return () => { clearTimeout(tipTimer); };
}
"""

_component = None


def _mount():
    global _component
    if _component is None:
        _component = st.components.v2.component(
            "interactive_calendar", html=HTML, css=CSS, js=JS, isolate_styles=True)
    return _component


def render_grid(payload: dict, *, key: str, on_event) -> None:
    """Draw the grid. `on_event(key)` runs before the rerun that follows a drop,
    a click on a workout, or a click on a day."""
    cb = lambda: on_event(key)
    _mount()(key=key, data=payload, on_move_change=cb, on_open_change=cb,
             on_select_change=cb)
