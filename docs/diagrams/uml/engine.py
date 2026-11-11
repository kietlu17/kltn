"""Tiny layout engines that render UML sequence, UML activity and BPMN 2.0
process diagrams as self-contained HTML + inline SVG, using the
diagram-design skill tokens (paper / ink / muted / accent / link).

Specs live in specs.py; run build.py to regenerate every file.
"""
from __future__ import annotations

import html
import math
import re

# ---------------------------------------------------------------- tokens
PAPER = "#f5f5f5"
INK = "#2d3142"
MUTED = "#4f5d75"
SOFT = "#5a6580"
ACCENT = "#bf4520"
ACCENT_TINT = "rgba(191,69,32,0.08)"
LINK = "#2e5aa8"
WHITE = "#ffffff"
RULE = "rgba(45,49,66,0.22)"

# Geist / Instrument Serif have no Vietnamese subset, so the Vietnamese labels
# fall to faces that do (Be Vietnam Pro, Noto Serif). Technical labels stay Geist Mono.
SANS = "'Be Vietnam Pro', 'Geist', system-ui, sans-serif"
MONO = "'Geist Mono', ui-monospace, monospace"
SERIF = "'Noto Serif', 'Instrument Serif', serif"
FONT_LINK = (
    "https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600"
    "&family=Geist+Mono:wght@400;500;600&family=Noto+Serif:ital@0;1&display=swap"
)


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def is_mono(s: str) -> bool:
    return s.startswith("$")


def clean(s: str) -> str:
    return s[1:] if s.startswith("$") else s


def tw(s: str, size: float, mono: bool = False) -> float:
    s = clean(s)
    return len(s) * size * (0.62 if mono else 0.53)


def g4(v: float) -> int:
    return int(math.ceil(v / 4.0) * 4)


def wrap(s: str, maxw: float, size: float) -> list[str]:
    if "|" in s:
        out = []
        for part in s.split("|"):
            out += wrap(part, maxw, size)
        return out
    words = s.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if tw(cand, size) <= maxw or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def text(x, y, s, size=12, fill=INK, anchor="middle", weight=400, font=None,
         italic=False, ls=None):
    mono = is_mono(s)
    font = font or (MONO if mono else SANS)
    extra = ""
    if italic:
        extra += ' font-style="italic"'
    if ls:
        extra += f' letter-spacing="{ls}"'
    return (f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" '
            f'font-family="{font}" font-weight="{weight}" text-anchor="{anchor}"{extra}>'
            f'{esc(clean(s))}</text>')


def label(x, y, s, size=10.5, fill=MUTED, anchor="middle", weight=400, pad=4):
    """Text with an opaque paper mask behind it (baseline y)."""
    mono = is_mono(s)
    w = tw(s, size, mono)
    if anchor == "middle":
        rx = x - w / 2 - pad
    elif anchor == "start":
        rx = x - pad
    else:
        rx = x - w - pad
    return (f'<rect x="{rx:.1f}" y="{y - size:.1f}" width="{w + 2 * pad:.1f}" '
            f'height="{size + 4:.1f}" fill="{PAPER}"/>' + text(x, y, s, size, fill, anchor, weight))


def rpath(pts, r=8):
    """Orthogonal polyline with rounded corners."""
    p = []
    for q in pts:
        if not p or (abs(q[0] - p[-1][0]) > 0.01 or abs(q[1] - p[-1][1]) > 0.01):
            p.append(q)
    # drop collinear middle points
    i = 1
    while i < len(p) - 1:
        a, b, c = p[i - 1], p[i], p[i + 1]
        if (abs(a[0] - b[0]) < 0.01 and abs(b[0] - c[0]) < 0.01) or (
                abs(a[1] - b[1]) < 0.01 and abs(b[1] - c[1]) < 0.01):
            p.pop(i)
        else:
            i += 1
    d = f"M{p[0][0]:.1f},{p[0][1]:.1f}"
    for i in range(1, len(p) - 1):
        a, b, c = p[i - 1], p[i], p[i + 1]
        lin = math.hypot(b[0] - a[0], b[1] - a[1])
        lout = math.hypot(c[0] - b[0], c[1] - b[1])
        rr = min(r, lin / 2, lout / 2)
        ux, uy = (b[0] - a[0]) / lin, (b[1] - a[1]) / lin
        vx, vy = (c[0] - b[0]) / lout, (c[1] - b[1]) / lout
        d += f" L{b[0] - ux * rr:.1f},{b[1] - uy * rr:.1f} Q{b[0]:.1f},{b[1]:.1f} {b[0] + vx * rr:.1f},{b[1] + vy * rr:.1f}"
    d += f" L{p[-1][0]:.1f},{p[-1][1]:.1f}"
    return d, p


def defs():
    return f"""<defs>
  <marker id="m-fill" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto"><polygon points="0 0, 9 3.5, 0 7" fill="{MUTED}"/></marker>
  <marker id="m-fill-ink" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto"><polygon points="0 0, 9 3.5, 0 7" fill="{INK}"/></marker>
  <marker id="m-fill-accent" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto"><polygon points="0 0, 9 3.5, 0 7" fill="{ACCENT}"/></marker>
  <marker id="m-fill-link" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto"><polygon points="0 0, 9 3.5, 0 7" fill="{LINK}"/></marker>
  <marker id="m-open" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><polyline points="0.5 0.5, 9 4, 0.5 7.5" fill="none" stroke="{MUTED}" stroke-width="1.2"/></marker>
  <marker id="m-open-ink" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><polyline points="0.5 0.5, 9 4, 0.5 7.5" fill="none" stroke="{INK}" stroke-width="1.2"/></marker>
  <marker id="m-open-accent" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><polyline points="0.5 0.5, 9 4, 0.5 7.5" fill="none" stroke="{ACCENT}" stroke-width="1.2"/></marker>
  <marker id="m-open-link" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><polyline points="0.5 0.5, 9 4, 0.5 7.5" fill="none" stroke="{LINK}" stroke-width="1.2"/></marker>
  <marker id="m-hollow" markerWidth="11" markerHeight="9" refX="10" refY="4.5" orient="auto"><polygon points="0.8 0.8, 10 4.5, 0.8 8.2" fill="{WHITE}" stroke="{MUTED}" stroke-width="1"/></marker>
  <marker id="m-circ" markerWidth="9" markerHeight="9" refX="4.5" refY="4.5" orient="auto"><circle cx="4.5" cy="4.5" r="3.5" fill="{WHITE}" stroke="{MUTED}" stroke-width="1"/></marker>
</defs>"""


def frame_tab(x, y, kw, name, size=12):
    """UML diagram frame name tab (pentagon) e.g. 'sd Đặt hàng'."""
    w = g4(tw(kw, size, True) + tw(name, size) + 30)
    h = 24
    pts = f"{x},{y} {x + w},{y} {x + w},{y + h - 8} {x + w - 8},{y + h} {x},{y + h}"
    return (f'<polygon points="{pts}" fill="{WHITE}" stroke="{INK}" stroke-width="1"/>'
            f'<text x="{x + 10}" y="{y + 16}" font-size="{size}" fill="{INK}">'
            f'<tspan font-family="{MONO}" font-weight="600">{esc(kw)}</tspan>'
            f'<tspan font-family="{SANS}" font-weight="600" dx="6">{esc(name)}</tspan></text>')


def legend(items, x0, y, width):
    """Horizontal legend strip (wraps to extra rows). Returns (svg, used_height)."""
    out = [f'<line x1="{x0}" y1="{y}" x2="{x0 + width}" y2="{y}" stroke="{RULE}" stroke-width="1"/>',
           text(x0, y + 22, "$CHÚ GIẢI", 8, SOFT, "start", 500, ls="0.18em")]
    x = x0 + 76
    row = 0
    for fn, lab in items:
        wi = 40 + tw(lab, 10) + 24
        if x + wi > x0 + width and x > x0 + 76:
            row += 1
            x = x0 + 76
        yy = y + 18 + row * 26
        out.append(fn(x, yy))
        out.append(text(x + 40, yy + 4, lab, 10, MUTED, "start"))
        x += wi
    return "\n".join(out), 44 + row * 26


# ================================================================ SEQUENCE
def build_sequence(spec):
    parts = spec["parts"]
    steps = spec["steps"]
    n = len(parts)
    idx = {p["id"]: i for i, p in enumerate(parts)}

    # ---------- number messages
    num = 0
    msgs = []
    for st in steps:
        if st[0] == "m":
            _, a, b, lab, kind = (list(st) + [None])[:5]
            kind = kind or "call"
            if kind not in ("ret", "ret-ok"):
                num += 1
                lab_full = (lab[0] + f"{num}: " + lab[1:]) if is_mono(lab) else f"{num}: {lab}"
            else:
                lab_full = lab
            msgs.append(lab_full)

    # ---------- head widths
    heads = []
    for p in parts:
        if p.get("kind") == "actor":
            w = max(tw(p["label"], 12) + 16, 72)
        else:
            w = max(tw(p["label"], 12) + 28, tw(p.get("sub", ""), 9, True) + 24, 112)
        heads.append(g4(w))
    gaps = [max(heads[i] / 2 + heads[i + 1] / 2 + 28, 132) for i in range(n - 1)]
    right_extra = 0
    k = 0
    for st in steps:
        if st[0] != "m":
            continue
        a, b = idx[st[1]], idx[st[2]]
        lab = msgs[k]
        k += 1
        w = tw(lab, 10.5, is_mono(lab)) + 36
        if a == b:
            need = 44 + w
            if a < n - 1:
                gaps[a] = max(gaps[a], need)
            else:
                right_extra = max(right_extra, need)
            continue
        lo, hi = min(a, b), max(a, b)
        have = sum(gaps[lo:hi])
        if have < w:
            add = (w - have) / (hi - lo)
            for i in range(lo, hi):
                gaps[i] += add
    gaps = [g4(g) for g in gaps]
    X0 = 40 + max(heads[0] / 2, 40)
    xs = [X0]
    for g in gaps:
        xs.append(xs[-1] + g)
    xs = [g4(x) for x in xs]
    width = g4(xs[-1] + max(heads[-1] / 2, right_extra) + 48)

    HEAD_Y = 64
    BOX_H = 44
    ll_top = HEAD_Y + BOX_H
    # ---------- pass 1: vertical layout, activations, frames
    y = ll_top + 40
    stacks = {i: [] for i in range(n)}  # entries: dict(start, kind, last, level)
    bars = []
    placed = []  # message records
    frames = []
    fstack = []
    k = 0

    def close_idle(cur_y):
        for i in range(n):
            st_ = stacks[i]
            while st_ and st_[-1]["kind"] in ("async", "auto") and cur_y - st_[-1]["last"] > 40:
                e = st_.pop()
                bars.append((i, e["start"], e["last"] + 14, e["level"]))

    for st in steps:
        op = st[0]
        if op == "m":
            _, a_id, b_id, lab, kind = (list(st) + [None])[:5]
            kind = kind or "call"
            a, b = idx[a_id], idx[b_id]
            lab = msgs[k]
            k += 1
            close_idle(y)
            is_actor = lambda i: parts[i].get("kind") == "actor"
            rec = dict(a=a, b=b, y=y, lab=lab, kind=kind)
            # source level
            if not is_actor(a):
                if not stacks[a]:
                    stacks[a].append(dict(start=y - 8, kind="auto", last=y, level=0))
                stacks[a][-1]["last"] = y
            rec["la"] = len(stacks[a]) - 1 if stacks[a] else -1
            if a == b:
                lvl = len(stacks[a])
                bars.append((a, y + 20, y + 34, max(lvl, 1)))
                rec["lself"] = max(lvl, 1)
                y_next = y + 52
            else:
                if kind in ("ret", "ret-ok"):
                    if stacks[a]:
                        # pop up to and including the most recent sync entry
                        while stacks[a]:
                            e = stacks[a].pop()
                            bars.append((a, e["start"], y, e["level"]))
                            if e["kind"] == "sync":
                                break
                    rec["la"] = len(stacks[a])  # bar ended here; endpoint stays on it
                elif kind == "call":
                    if not is_actor(b):
                        if is_actor(a) and stacks[b]:
                            stacks[b][-1]["last"] = y
                        else:
                            stacks[b].append(dict(start=y, kind="sync", last=y, level=len(stacks[b])))
                else:  # async
                    if not is_actor(b):
                        if stacks[b]:
                            stacks[b][-1]["last"] = y
                        else:
                            stacks[b].append(dict(start=y, kind="async", last=y, level=0))
                rec["lb"] = len(stacks[b]) - 1 if stacks[b] else -1
                y_next = y + 36
            placed.append(rec)
            for f in fstack:
                f["parts"].update({a, b})
                if a == b:
                    f["xmax_extra"] = max(f.get("xmax_extra", 0), 44 + tw(lab, 10.5, is_mono(lab)) + 8)
                    f["self_parts"].add(a)
            y = y_next
        elif op in ("alt", "opt", "loop", "par", "break"):
            f = dict(op=op, guards=[(y - 8, st[1] if len(st) > 1 else "")], top=y - 8,
                     parts=set(), dividers=[], depth=len(fstack), self_parts=set(),
                     saved={i: [dict(e) for e in stacks[i]] for i in range(n)})
            frames.append(f)
            fstack.append(f)
            y += 36
        elif op == "else":
            f = fstack[-1]
            dy = y - 12
            f["dividers"].append(dy)
            for i in range(n):
                # close whatever region 1 left open, then restore the pre-alt state
                cur_ids = [(e["start"], e["level"]) for e in stacks[i]]
                saved_ids = [(e["start"], e["level"]) for e in f["saved"][i]]
                for e in stacks[i]:
                    if (e["start"], e["level"]) not in saved_ids:
                        bars.append((i, e["start"], max(e["last"] + 14, dy - 8), e["level"]))
                stacks[i] = [dict(e) for e in f["saved"][i]]
            f["guards"].append((dy, st[1] if len(st) > 1 else "[else]"))
            y += 28
        elif op == "end":
            f = fstack.pop()
            f["bottom"] = y - 14
            y += 12
    end_y = y + 8
    for i in range(n):
        while stacks[i]:
            e = stacks[i].pop()
            bars.append((i, e["start"], min(e["last"] + 14, end_y - 4) if e["kind"] != "sync" else end_y - 12, e["level"]))

    # ---------- frames x extents
    maxdepth = max([f["depth"] for f in frames] + [0])
    for f in frames:
        inset = 24 + 10 * (maxdepth - f["depth"])
        ps = f["parts"] or {0}
        x1 = xs[min(ps)] - inset
        x2 = xs[max(ps)] + inset
        for sp in f["self_parts"]:
            x2 = max(x2, xs[sp] + f.get("xmax_extra", 0) + 8)
        need = tw(f["op"], 10, True) + 26 + max(tw(g[1], 10.5) for g in f["guards"]) + 24
        x2 = max(x2, x1 + need)
        f["x1"], f["x2"] = g4(x1) - 4 if False else x1, x2
        width = max(width, g4(x2 + 32))

    # ---------- legend + size
    leg_items = [
        (lambda x, yy: f'<line x1="{x}" y1="{yy}" x2="{x + 30}" y2="{yy}" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#m-fill)"/>', "Thông điệp đồng bộ"),
        (lambda x, yy: f'<line x1="{x}" y1="{yy}" x2="{x + 30}" y2="{yy}" stroke="{LINK}" stroke-width="1.2" marker-end="url(#m-open-link)"/>', "Bất đồng bộ (Kafka/sự kiện)"),
        (lambda x, yy: f'<line x1="{x}" y1="{yy}" x2="{x + 30}" y2="{yy}" stroke="{MUTED}" stroke-width="1.2" stroke-dasharray="5,4" marker-end="url(#m-open)"/>', "Thông điệp trả về"),
        (lambda x, yy: f'<rect x="{x + 11}" y="{yy - 9}" width="8" height="18" fill="{WHITE}" stroke="{MUTED}" stroke-width="0.8"/>', "Activation"),
        (lambda x, yy: f'<rect x="{x}" y="{yy - 8}" width="30" height="16" rx="2" fill="rgba(45,49,66,0.03)" stroke="{RULE}"/>', "Combined fragment"),
    ]
    leg_y = end_y + 40
    leg_svg, leg_h = legend(leg_items, 32, leg_y, width - 64)
    height = g4(leg_y + leg_h)

    o = []
    o.append(f'<rect width="100%" height="100%" fill="{PAPER}"/>')
    o.append(f'<rect x="16" y="16" width="{width - 32}" height="{end_y + 16 - 16}" fill="none" stroke="{INK}" stroke-width="1"/>')
    o.append(frame_tab(16, 16, "sd", spec["title"]))
    # fragment frames (fills)
    for f in frames:
        o.append(f'<rect x="{f["x1"]:.1f}" y="{f["top"]:.1f}" width="{f["x2"] - f["x1"]:.1f}" height="{f["bottom"] - f["top"]:.1f}" '
                 f'fill="rgba(45,49,66,0.025)" stroke="{RULE}" stroke-width="1"/>')
    # lifelines
    for i, p in enumerate(parts):
        top = ll_top + (12 if p.get("kind") == "actor" else 0)
        o.append(f'<line x1="{xs[i]}" y1="{top}" x2="{xs[i]}" y2="{end_y}" stroke="rgba(45,49,66,0.30)" stroke-width="1" stroke-dasharray="4,4"/>')
    # bars
    for (i, s, e, lvl) in sorted(bars, key=lambda b: b[3]):
        if parts[i].get("kind") == "actor":
            continue
        bx = xs[i] - 4 + 5 * lvl
        o.append(f'<rect x="{bx:.1f}" y="{s:.1f}" width="8" height="{max(e - s, 8):.1f}" fill="{WHITE}" stroke="{MUTED}" stroke-width="0.8"/>')
    # messages
    labels = []
    for r in placed:
        a, b, yy, kind = r["a"], r["b"], r["y"], r["kind"]
        col = {"call": MUTED, "ret": MUTED, "async": LINK, "ok": ACCENT, "ret-ok": ACCENT}.get(kind, MUTED)
        if kind == "call":
            mk = "m-fill"
        elif kind == "ok":
            mk = "m-fill-accent"
        elif kind == "async":
            mk = "m-open-link"
        elif kind == "ret-ok":
            mk = "m-open-accent"
        else:
            mk = "m-open"
        dash = ' stroke-dasharray="5,4"' if kind in ("ret", "ret-ok") else ""
        if a == b:
            lvl = r["la"] if r["la"] >= 0 else 0
            x0 = xs[a] + 4 + 5 * max(lvl, 0)
            x1 = xs[a] + 4 + 5 * r["lself"]
            d, _ = rpath([(x0, yy), (xs[a] + 40, yy), (xs[a] + 40, yy + 22), (x1, yy + 22)], 6)
            o.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.2"{dash} marker-end="url(#{mk})"/>')
            labels.append(label(xs[a] + 48, yy + 4, r["lab"], 10.5, INK if kind != "ok" else ACCENT, "start"))
            continue
        sgn = 1 if b > a else -1
        la = r.get("la", -1)
        lb = r.get("lb", -1)
        if kind in ("ret", "ret-ok"):
            sx = xs[a] + (4 + 5 * max(la, 0)) * sgn if la >= 0 else xs[a]
        else:
            sx = xs[a] + (4 * sgn + 5 * la) if la >= 0 else xs[a]
        if lb >= 0:
            ex = xs[b] - 4 * sgn + 5 * lb
        else:
            ex = xs[b]
        o.append(f'<line x1="{sx:.1f}" y1="{yy}" x2="{ex - sgn * 1:.1f}" y2="{yy}" stroke="{col}" stroke-width="1.2"{dash} marker-end="url(#{mk})"/>')
        labels.append(label((sx + ex) / 2, yy - 7, r["lab"], 10.5,
                            ACCENT if kind in ("ok", "ret-ok") else (LINK if kind == "async" else INK)))
    o += labels
    # fragment tabs, guards, dividers
    for f in frames:
        for dv in f["dividers"]:
            o.append(f'<line x1="{f["x1"]:.1f}" y1="{dv}" x2="{f["x2"]:.1f}" y2="{dv}" stroke="{RULE}" stroke-width="1" stroke-dasharray="6,4"/>')
        tw_ = g4(tw(f["op"], 10, True) + 18)
        x, yt = f["x1"], f["top"]
        o.append(f'<polygon points="{x},{yt} {x + tw_},{yt} {x + tw_},{yt + 12} {x + tw_ - 6},{yt + 18} {x},{yt + 18}" fill="{WHITE}" stroke="{INK}" stroke-width="0.9"/>')
        o.append(text(x + 7, yt + 13, "$" + f["op"], 10, INK, "start", 600))
        for i, (gy, gt) in enumerate(f["guards"]):
            if not gt:
                continue
            if i == 0:
                o.append(label(x + tw_ + 10, gy + 14, gt, 10.5, INK, "start", 500, 3))
            else:
                o.append(label(x + 10, gy + 16, gt, 10.5, INK, "start", 500, 3))
    # heads
    for i, p in enumerate(parts):
        cx = xs[i]
        if p.get("kind") == "actor":
            hy = HEAD_Y - 2
            o.append(f'<g stroke="{INK}" stroke-width="1.4" fill="none">'
                     f'<circle cx="{cx}" cy="{hy + 6}" r="6" fill="{WHITE}"/>'
                     f'<line x1="{cx}" y1="{hy + 12}" x2="{cx}" y2="{hy + 28}"/>'
                     f'<line x1="{cx - 11}" y1="{hy + 17}" x2="{cx + 11}" y2="{hy + 17}"/>'
                     f'<line x1="{cx}" y1="{hy + 28}" x2="{cx - 9}" y2="{hy + 40}"/>'
                     f'<line x1="{cx}" y1="{hy + 28}" x2="{cx + 9}" y2="{hy + 40}"/></g>')
            o.append(text(cx, hy + 56, p["label"], 12, INK, "middle", 600))
        else:
            w = heads[i]
            ext = p.get("kind") == "ext"
            focal = p.get("focal")
            fill = ACCENT_TINT if focal else ("rgba(45,49,66,0.04)" if ext else WHITE)
            stroke = ACCENT if focal else (SOFT if ext else INK)
            dash = ' stroke-dasharray="4,3"' if ext else ""
            o.append(f'<rect x="{cx - w / 2:.1f}" y="{HEAD_Y}" width="{w}" height="{BOX_H}" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1.1"{dash}/>')
            o.append(text(cx, HEAD_Y + 19, p["label"], 12, INK, "middle", 600))
            if p.get("sub"):
                o.append(text(cx, HEAD_Y + 34, "$" + p["sub"], 9, SOFT, "middle"))
    o.append(leg_svg)
    return width, height, "\n".join(o)


# ================================================================ GRAPH (activity + BPMN shared)
class Node:
    def __init__(self, nid, d):
        self.id = nid
        self.__dict__.update(d)


def port(n, p):
    """p like 'b', 't', 'l', 'r' optionally with ':offset'."""
    off = 0.0
    if ":" in p:
        p, o_ = p.split(":")
        off = float(o_)
    if p == "t":
        return (n.cx + off, n.cy - n.h / 2), p
    if p == "b":
        return (n.cx + off, n.cy + n.h / 2), p
    if p == "l":
        return (n.cx - n.w / 2, n.cy + off), p
    return (n.cx + n.w / 2, n.cy + off), p


def route(src, dst, e, default_style):
    fp = e.get("fp")
    tp = e.get("tp")
    if not fp or not tp:
        dfp, dtp = default_style(src, dst)
        fp = fp or dfp
        tp = tp or dtp
    (sx, sy), fd = port(src, fp)
    (tx, ty), td = port(dst, tp)
    pts = [(sx, sy)]
    cur = [sx, sy]
    via = e.get("via")
    if via is None:
        via = []
        if fd in ("t", "b") and td in ("t", "b") and abs(sx - tx) > 0.5:
            mid = e.get("mid")
            if mid is None:
                mid = ty - 22 if td == "t" else ty + 22
            elif isinstance(mid, str) and mid == "src":
                mid = sy + 22 if fd == "b" else sy - 22
            via = [("y", mid)]
        elif fd in ("l", "r") and td in ("l", "r") and abs(sy - ty) > 0.5:
            if fd == td:
                ch = (max(src.cx + src.w / 2, dst.cx + dst.w / 2) + 28) if fd == "r" else (
                    min(src.cx - src.w / 2, dst.cx - dst.w / 2) - 28)
                via = [("x", e.get("chan", ch))]
            else:
                via = [("x", e.get("mid", (sx + tx) / 2))]
    for ax, v in via:
        if ax == "x":
            cur = [v, cur[1]]
        elif ax == "y":
            cur = [cur[0], v]
        elif ax == "dx":
            cur = [cur[0] + v, cur[1]]
        elif ax == "dy":
            cur = [cur[0], cur[1] + v]
        pts.append(tuple(cur))
    if td in ("t", "b"):
        pts.append((tx, cur[1]))
    else:
        pts.append((cur[0], ty))
    pts.append((tx, ty))
    return pts, fd


def edge_label(pts, s, style, pos=None):
    if not s:
        return ""
    (x0, y0), (x1, y1) = pts[0], pts[1]
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        if abs(x1 - x0) + abs(y1 - y0) > 0.5:
            break
    size = 10.5
    w = tw(s, size)
    if pos and pos.startswith("end"):
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        if abs(y1 - y0) > abs(x1 - x0):
            ym = (y0 + y1) / 2 + 4
            if pos == "end-l":
                return label(x1 - 8, ym, s, size, INK, "end")
            return label(x1 + 8, ym, s, size, INK, "start")
        return label((x0 + x1) / 2, y1 - 7, s, size, INK)
    if pos == "mid":
        best = max(range(len(pts) - 1), key=lambda i: abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1]))
        (x0, y0), (x1, y1) = pts[best], pts[best + 1]
        if abs(y1 - y0) < 0.5:
            return label((x0 + x1) / 2, y0 - 7, s, size, INK)
        return label(x0 + 8, (y0 + y1) / 2 + 4, s, size, INK, "start")
    if abs(y1 - y0) < 0.5:  # horizontal first segment
        sgn = 1 if x1 > x0 else -1
        seg = abs(x1 - x0)
        cx = x0 + sgn * min(w / 2 + 10, seg / 2)
        return label(cx, y0 - 7, s, size, INK)
    sgn = 1 if y1 > y0 else -1
    yy = y0 + sgn * 15 + (4 if sgn > 0 else 0)
    if pos == "left":
        return label(x0 - 8, yy, s, size, INK, "end")
    return label(x0 + 8, yy, s, size, INK, "start")


# ================================================================ ACTIVITY
def build_activity(spec):
    lanes = spec["lanes"]
    LW = spec.get("lw", 260)
    lws = spec.get("lws", [LW] * len(lanes))
    RH = spec.get("rh", 64)
    X0 = 32
    TOP = 56
    HEAD = 36
    lx = [X0]
    for w in lws:
        lx.append(lx[-1] + w)
    content_top = TOP + HEAD + 20
    nodes = {}
    for nid, d in spec["nodes"].items():
        n = Node(nid, d)
        n.k = d["k"]
        lane = d["lane"]
        n.cx = lx[lane] + lws[lane] / 2 + d.get("dx", 0)
        n.cy = content_top + d["row"] * RH + 16
        t = d.get("t", "")
        if n.k == "action":
            n.w = d.get("w", min(lws[lane] - 48, 196))
            n.lines = wrap(t, n.w - 20, 11.5)
            n.h = max(36, 14 + 15 * len(n.lines))
        elif n.k in ("decision", "merge"):
            n.w = n.h = 32
        elif n.k in ("fork", "join"):
            n.w = d.get("w", 120)
            n.h = 6
        elif n.k == "initial":
            n.w = n.h = 20
        elif n.k in ("final", "flowfinal"):
            n.w = n.h = 24
        elif n.k in ("send", "accept"):
            n.w = d.get("w", min(lws[lane] - 48, 196))
            n.lines = wrap(t, n.w - 36, 11.5)
            n.h = max(36, 14 + 15 * len(n.lines))
        nodes[nid] = n
    maxy = max(n.cy + n.h / 2 for n in nodes.values())
    bottom = maxy + 28
    width = lx[-1] + 32

    def dstyle(s, d):
        if d.cy > s.cy + 1 and abs(d.cx - s.cx) > 1 and (d.lane != s.lane):
            return ("r" if d.cx > s.cx else "l"), "t"
        if d.cy > s.cy + 1:
            return "b", "t"
        if abs(d.cy - s.cy) <= 1:
            return ("r", "l") if d.cx > s.cx else ("l", "r")
        return "r", "r"

    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    o.append(f'<rect x="16" y="16" width="{width - 32}" height="{bottom + 16 - 16}" fill="none" stroke="{INK}" stroke-width="1"/>')
    o.append(frame_tab(16, 16, "act", spec["title"]))
    # partitions
    o.append(f'<rect x="{X0}" y="{TOP}" width="{lx[-1] - X0}" height="{bottom - TOP}" fill="none" stroke="{INK}" stroke-width="1"/>')
    for i, name in enumerate(lanes):
        if i % 2 == 1:
            o.append(f'<rect x="{lx[i]}" y="{TOP + HEAD}" width="{lws[i]}" height="{bottom - TOP - HEAD}" fill="rgba(45,49,66,0.022)"/>')
        o.append(f'<rect x="{lx[i]}" y="{TOP}" width="{lws[i]}" height="{HEAD}" fill="rgba(79,93,117,0.10)" stroke="{INK}" stroke-width="1"/>')
        o.append(text(lx[i] + lws[i] / 2, TOP + 23, name, 12, INK, "middle", 600))
        if i > 0:
            o.append(f'<line x1="{lx[i]}" y1="{TOP}" x2="{lx[i]}" y2="{bottom}" stroke="{INK}" stroke-width="1"/>')
    labs = []
    for e in spec["edges"]:
        s, d = nodes[e["f"]], nodes[e["t"]]
        pts, _ = route(s, d, e, dstyle)
        dpath, pts = rpath(pts, 8)
        col = ACCENT if e.get("focal") else MUTED
        mk = "m-open-accent" if e.get("focal") else "m-open"
        o.append(f'<path d="{dpath}" fill="none" stroke="{col}" stroke-width="1.2" marker-end="url(#{mk})"/>')
        g = e.get("g")
        if g:
            labs.append(edge_label(pts, f"[{g}]", None, e.get("gpos")))
    for n in nodes.values():
        cx, cy = n.cx, n.cy
        if n.k == "initial":
            o.append(f'<circle cx="{cx}" cy="{cy}" r="9" fill="{INK}"/>')
        elif n.k == "final":
            o.append(f'<circle cx="{cx}" cy="{cy}" r="11" fill="{PAPER}" stroke="{INK}" stroke-width="1.4"/><circle cx="{cx}" cy="{cy}" r="6.5" fill="{INK}"/>')
        elif n.k == "flowfinal":
            o.append(f'<circle cx="{cx}" cy="{cy}" r="11" fill="{PAPER}" stroke="{INK}" stroke-width="1.4"/>'
                     f'<path d="M{cx - 7.8},{cy - 7.8} L{cx + 7.8},{cy + 7.8} M{cx + 7.8},{cy - 7.8} L{cx - 7.8},{cy + 7.8}" stroke="{INK}" stroke-width="1.4"/>')
        elif n.k in ("decision", "merge"):
            o.append(f'<polygon points="{cx},{cy - 16} {cx + 16},{cy} {cx},{cy + 16} {cx - 16},{cy}" fill="{WHITE}" stroke="{INK}" stroke-width="1.2"/>')
            if n.__dict__.get("t"):
                side = n.__dict__.get("tside", "l")
                if side == "l":
                    o.append(label(cx - 24, cy - 12, n.t, 10.5, SOFT, "end"))
                elif side == "r":
                    o.append(label(cx + 24, cy - 12, n.t, 10.5, SOFT, "start"))
                else:
                    o.append(label(cx, cy - 24, n.t, 10.5, SOFT, "middle"))
        elif n.k in ("fork", "join"):
            o.append(f'<rect x="{cx - n.w / 2}" y="{cy - 3}" width="{n.w}" height="6" rx="1" fill="{INK}"/>')
        elif n.k in ("action", "send", "accept"):
            focal = n.__dict__.get("focal")
            fill = ACCENT_TINT if focal else WHITE
            stroke = ACCENT if focal else INK
            x0, y0, w, h = cx - n.w / 2, cy - n.h / 2, n.w, n.h
            if n.k == "action":
                o.append(f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
                tx = cx
            elif n.k == "send":
                o.append(f'<polygon points="{x0},{y0} {x0 + w - 14},{y0} {x0 + w},{cy} {x0 + w - 14},{y0 + h} {x0},{y0 + h}" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
                tx = cx - 6
            else:
                o.append(f'<polygon points="{x0},{y0} {x0 + w},{y0} {x0 + w},{y0 + h} {x0},{y0 + h} {x0 + 14},{cy}" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
                tx = cx + 6
            ty0 = cy - (len(n.lines) - 1) * 7.5 + 4
            for i, ln in enumerate(n.lines):
                o.append(text(tx, ty0 + i * 15, ln, 11.5, INK, "middle", 500))
    o += labs
    leg_items = [
        (lambda x, yy: f'<circle cx="{x + 8}" cy="{yy}" r="7" fill="{INK}"/>', "Bắt đầu"),
        (lambda x, yy: f'<circle cx="{x + 8}" cy="{yy}" r="8" fill="{PAPER}" stroke="{INK}" stroke-width="1.2"/><circle cx="{x + 8}" cy="{yy}" r="4.5" fill="{INK}"/>', "Kết thúc"),
        (lambda x, yy: f'<rect x="{x}" y="{yy - 9}" width="32" height="18" rx="7" fill="{WHITE}" stroke="{INK}"/>', "Hành động"),
        (lambda x, yy: f'<polygon points="{x + 14},{yy - 10} {x + 24},{yy} {x + 14},{yy + 10} {x + 4},{yy}" fill="{WHITE}" stroke="{INK}"/>', "Quyết định / Hợp nhất"),
        (lambda x, yy: f'<rect x="{x}" y="{yy - 3}" width="30" height="6" fill="{INK}"/>', "Fork / Join"),
        (lambda x, yy: f'<line x1="{x}" y1="{yy}" x2="{x + 30}" y2="{yy}" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#m-open)"/>', "Luồng điều khiển [guard]"),
    ]
    leg_y = bottom + 48
    leg_svg, leg_h = legend(leg_items, 32, leg_y, width - 64)
    o.append(leg_svg)
    height = g4(leg_y + leg_h)
    return width, height, "\n".join(o)


# ================================================================ BPMN
def envelope(cx, cy, w=14, h=10, filled=False):
    x0, y0 = cx - w / 2, cy - h / 2
    f = INK if filled else WHITE
    s = WHITE if filled else INK
    return (f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="{f}" stroke="{INK}" stroke-width="1"/>'
            f'<polyline points="{x0},{y0} {cx},{cy + 1} {x0 + w},{y0}" fill="none" stroke="{s}" stroke-width="1"/>')


def task_icon(kind, x, y):
    if kind == "user":
        return (f'<g stroke="{INK}" stroke-width="1" fill="{WHITE}"><circle cx="{x + 7}" cy="{y + 5}" r="3.6"/>'
                f'<path d="M{x},{y + 16} Q{x},{y + 9} {x + 7},{y + 9} Q{x + 14},{y + 9} {x + 14},{y + 16} Z"/></g>')
    if kind == "service":
        cx, cy = x + 7, y + 8
        teeth = "".join(
            f'<line x1="{cx + 4.5 * math.cos(a):.1f}" y1="{cy + 4.5 * math.sin(a):.1f}" x2="{cx + 7.5 * math.cos(a):.1f}" y2="{cy + 7.5 * math.sin(a):.1f}" stroke="{INK}" stroke-width="2"/>'
            for a in [i * math.pi / 4 for i in range(8)])
        return teeth + f'<circle cx="{cx}" cy="{cy}" r="5" fill="{WHITE}" stroke="{INK}" stroke-width="1.2"/><circle cx="{cx}" cy="{cy}" r="2" fill="none" stroke="{INK}"/>'
    if kind == "send":
        return envelope(x + 8, y + 7, filled=True)
    if kind == "receive":
        return envelope(x + 8, y + 7)
    if kind == "manual":
        return f'<path d="M{x},{y + 5} h10 a2,2 0 0 1 0,4 h-3 M{x},{y + 5} v8 h9" fill="none" stroke="{INK}" stroke-width="1"/>'
    return ""


def build_bpmn(spec):
    lanes = spec["lanes"]
    CW = spec.get("cw", 150)
    LH = spec.get("lh", 128)
    lhs = spec.get("lhs", [LH] * len(lanes))
    ncols = spec["cols"]
    X0 = 32
    POOL_HDR = 32
    LANE_HDR = 104
    ext = spec.get("ext", [])  # [{"id","name","pos": "top"|"bottom"}]
    top_ext = [p for p in ext if p["pos"] == "top"]
    bot_ext = [p for p in ext if p["pos"] == "bottom"]
    y = 56
    pools = {}
    content_x0 = X0 + POOL_HDR + LANE_HDR
    pool_w = POOL_HDR + LANE_HDR + 24 + ncols * CW + 8
    for p in top_ext:
        pools[p["id"]] = (y, y + 48)
        y += 48 + 40
    pool_top = y
    ly = [pool_top]
    for h in lhs:
        ly.append(ly[-1] + h)
    pool_bottom = ly[-1]
    y = pool_bottom + 40
    for p in bot_ext:
        pools[p["id"]] = (y, y + 48)
        y += 48 + 40
    bottom = y - 40 + 24
    width = X0 + pool_w + 32

    nodes = {}
    for nid, d in spec["nodes"].items():
        n = Node(nid, d)
        lane = d["lane"]
        n.cx = content_x0 + 24 + d["col"] * CW + CW / 2 + d.get("dx", 0)
        n.cy = ly[lane] + lhs[lane] / 2 + d.get("dy", 0)
        k = d["k"]
        if k == "task":
            n.w = d.get("w", 116)
            n.lines = wrap(d.get("t", ""), n.w - 16, 11)
            n.h = max(60, 30 + 14 * len(n.lines))
        elif k in ("xor", "and", "evgw"):
            n.w = n.h = 40
        else:
            n.w = n.h = 32
        nodes[nid] = n

    def dstyle(s, d):
        if abs(d.cy - s.cy) <= 1:
            return ("r", "l") if d.cx > s.cx else ("l", "r")
        if abs(d.cx - s.cx) <= 1:
            return ("b", "t") if d.cy > s.cy else ("t", "b")
        if d.cx > s.cx:
            return ("b", "l") if d.cy > s.cy else ("t", "l")
        return ("b", "t") if d.cy > s.cy else ("t", "b")

    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    # external (collapsed) pools
    for p in ext:
        y0, y1 = pools[p["id"]]
        o.append(f'<rect x="{X0}" y="{y0}" width="{pool_w}" height="{y1 - y0}" fill="rgba(45,49,66,0.04)" stroke="{INK}" stroke-width="1.2"/>')
        o.append(text(X0 + pool_w / 2, y0 + 29, p["name"], 12, INK, "middle", 600))
    # main pool
    o.append(f'<rect x="{X0}" y="{pool_top}" width="{pool_w}" height="{pool_bottom - pool_top}" fill="{PAPER}" stroke="{INK}" stroke-width="1.4"/>')
    o.append(f'<rect x="{X0}" y="{pool_top}" width="{POOL_HDR}" height="{pool_bottom - pool_top}" fill="rgba(79,93,117,0.10)" stroke="{INK}" stroke-width="1.4"/>')
    pcy = (pool_top + pool_bottom) / 2
    o.append(f'<text x="{X0 + 20}" y="{pcy}" transform="rotate(-90 {X0 + 20} {pcy})" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">{esc(spec["pool"])}</text>')
    for i, name in enumerate(lanes):
        o.append(f'<rect x="{X0 + POOL_HDR}" y="{ly[i]}" width="{LANE_HDR}" height="{lhs[i]}" fill="rgba(79,93,117,0.05)" stroke="{INK}" stroke-width="1"/>')
        if i > 0:
            o.append(f'<line x1="{X0 + POOL_HDR}" y1="{ly[i]}" x2="{X0 + pool_w}" y2="{ly[i]}" stroke="{INK}" stroke-width="1"/>')
        lines = wrap(name, LANE_HDR - 16, 11.5)
        y0 = ly[i] + lhs[i] / 2 - (len(lines) - 1) * 7.5 + 4
        for j, ln in enumerate(lines):
            o.append(text(X0 + POOL_HDR + LANE_HDR / 2, y0 + j * 15, ln, 11.5, INK, "middle", 600))
    labs = []
    # message flows
    for m in spec.get("msgs", []):
        f, t = m["f"], m["t"]
        if f in pools:
            n = nodes[t]
            y0, y1 = pools[f]
            x = n.cx + m.get("dx", 0)
            if y1 <= n.cy:
                pts = [(x, y1), (x, n.cy - n.h / 2)]
            else:
                pts = [(x, y0), (x, n.cy + n.h / 2)]
        else:
            n = nodes[f]
            y0, y1 = pools[t]
            x = n.cx + m.get("dx", 0)
            if y1 <= n.cy:
                pts = [(x, n.cy - n.h / 2), (x, y1)]
            else:
                pts = [(x, n.cy + n.h / 2), (x, y0)]
        o.append(f'<line x1="{pts[0][0]}" y1="{pts[0][1]}" x2="{pts[1][0]}" y2="{pts[1][1] + (-2 if pts[1][1] > pts[0][1] else 2)}" stroke="{MUTED}" stroke-width="1.1" stroke-dasharray="6,4" marker-start="url(#m-circ)" marker-end="url(#m-hollow)"/>')
        if m.get("t_"):
            my = (pts[0][1] + pts[1][1]) / 2 + 4
            labs.append(label(x + 8, my, m["t_"], 10, SOFT, "start"))
    for e in spec["edges"]:
        s, d = nodes[e["f"]], nodes[e["t"]]
        pts, _ = route(s, d, e, dstyle)
        dpath, pts = rpath(pts, 8)
        col = ACCENT if e.get("focal") else INK
        mk = "m-fill-accent" if e.get("focal") else "m-fill-ink"
        o.append(f'<path d="{dpath}" fill="none" stroke="{col}" stroke-width="1.2" marker-end="url(#{mk})"/>')
        if e.get("g"):
            labs.append(edge_label(pts, e["g"], None, e.get("gpos")))
    for n in nodes.values():
        cx, cy, k = n.cx, n.cy, n.k
        t = n.__dict__.get("t", "")
        below = True
        if k in ("start", "start-msg", "start-timer"):
            o.append(f'<circle cx="{cx}" cy="{cy}" r="16" fill="{WHITE}" stroke="{INK}" stroke-width="1.4"/>')
            if k == "start-msg":
                o.append(envelope(cx, cy))
            if k == "start-timer":
                o.append(f'<circle cx="{cx}" cy="{cy}" r="9" fill="none" stroke="{INK}"/><path d="M{cx},{cy - 6} V{cy} H{cx + 4}" fill="none" stroke="{INK}"/>')
        elif k in ("end", "end-msg", "end-err"):
            o.append(f'<circle cx="{cx}" cy="{cy}" r="15" fill="{WHITE}" stroke="{INK}" stroke-width="3.4"/>')
            if k == "end-msg":
                o.append(envelope(cx, cy, filled=True))
            if k == "end-err":
                o.append(f'<path d="M{cx - 7},{cy + 6} L{cx - 3},{cy - 6} L{cx + 2},{cy + 1} L{cx + 7},{cy - 7} L{cx + 3},{cy + 6} L{cx - 2},{cy - 1} Z" fill="{INK}"/>')
        elif k in ("imsg", "imsg-throw", "itimer"):
            o.append(f'<circle cx="{cx}" cy="{cy}" r="16" fill="{WHITE}" stroke="{INK}" stroke-width="1.1"/><circle cx="{cx}" cy="{cy}" r="12.5" fill="none" stroke="{INK}" stroke-width="1.1"/>')
            if k == "imsg":
                o.append(envelope(cx, cy, 12, 8))
            elif k == "imsg-throw":
                o.append(envelope(cx, cy, 12, 8, True))
            else:
                o.append(f'<circle cx="{cx}" cy="{cy}" r="8" fill="none" stroke="{INK}"/><path d="M{cx},{cy - 5} V{cy} H{cx + 4}" fill="none" stroke="{INK}"/>')
        elif k in ("xor", "and", "evgw"):
            o.append(f'<polygon points="{cx},{cy - 20} {cx + 20},{cy} {cx},{cy + 20} {cx - 20},{cy}" fill="{WHITE}" stroke="{INK}" stroke-width="1.3"/>')
            if k == "xor":
                o.append(f'<path d="M{cx - 6},{cy - 6} L{cx + 6},{cy + 6} M{cx + 6},{cy - 6} L{cx - 6},{cy + 6}" stroke="{INK}" stroke-width="2.4"/>')
            elif k == "and":
                o.append(f'<path d="M{cx},{cy - 8} V{cy + 8} M{cx - 8},{cy} H{cx + 8}" stroke="{INK}" stroke-width="2.4"/>')
            else:
                o.append(f'<circle cx="{cx}" cy="{cy}" r="9" fill="none" stroke="{INK}"/><polygon points="{cx},{cy - 5} {cx + 5},{cy - 1} {cx + 3},{cy + 5} {cx - 3},{cy + 5} {cx - 5},{cy - 1}" fill="none" stroke="{INK}"/>')
        elif k == "task":
            focal = n.__dict__.get("focal")
            fill = ACCENT_TINT if focal else WHITE
            stroke = ACCENT if focal else INK
            o.append(f'<rect x="{cx - n.w / 2}" y="{cy - n.h / 2}" width="{n.w}" height="{n.h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
            o.append(task_icon(n.__dict__.get("tt", ""), cx - n.w / 2 + 7, cy - n.h / 2 + 6))
            ty0 = cy - (len(n.lines) - 1) * 7 + (10 if n.__dict__.get("tt") else 4)
            for i, ln in enumerate(n.lines):
                o.append(text(cx, ty0 + i * 14, ln, 11, INK, "middle", 500))
            below = False
        if below and t:
            pos = n.__dict__.get("tpos", "b")
            lines = wrap(t, 120, 10.5)
            anchor, lx = "middle", cx
            if pos.startswith("b"):
                base = cy + n.h / 2 + 15
            else:
                base = cy - n.h / 2 - 8 - (len(lines) - 1) * 13
            if pos.endswith("r") and len(pos) == 2:
                anchor, lx = "start", cx + 12
            elif pos.endswith("l") and len(pos) == 2:
                anchor, lx = "end", cx - 12
            for i, ln in enumerate(lines):
                labs.append(label(lx, base + i * 13, ln, 10.5, SOFT, anchor))
    o += labs
    leg_items = [
        (lambda x, yy: f'<circle cx="{x + 9}" cy="{yy}" r="8" fill="{WHITE}" stroke="{INK}" stroke-width="1.2"/>', "Sự kiện bắt đầu"),
        (lambda x, yy: f'<circle cx="{x + 9}" cy="{yy}" r="8" fill="{WHITE}" stroke="{INK}" stroke-width="1.1"/><circle cx="{x + 9}" cy="{yy}" r="5.5" fill="none" stroke="{INK}"/>', "Sự kiện trung gian"),
        (lambda x, yy: f'<circle cx="{x + 9}" cy="{yy}" r="7.5" fill="{WHITE}" stroke="{INK}" stroke-width="3"/>', "Sự kiện kết thúc"),
        (lambda x, yy: f'<rect x="{x}" y="{yy - 9}" width="32" height="18" rx="5" fill="{WHITE}" stroke="{INK}"/>', "Task"),
        (lambda x, yy: f'<polygon points="{x + 14},{yy - 10} {x + 24},{yy} {x + 14},{yy + 10} {x + 4},{yy}" fill="{WHITE}" stroke="{INK}"/><path d="M{x + 11},{yy - 3} l6,6 m0,-6 l-6,6" stroke="{INK}" stroke-width="1.6"/>', "Cổng XOR"),
        (lambda x, yy: f'<polygon points="{x + 14},{yy - 10} {x + 24},{yy} {x + 14},{yy + 10} {x + 4},{yy}" fill="{WHITE}" stroke="{INK}"/><path d="M{x + 14},{yy - 4} v8 m-4,-4 h8" stroke="{INK}" stroke-width="1.6"/>', "Cổng song song"),
        (lambda x, yy: f'<line x1="{x}" y1="{yy}" x2="{x + 30}" y2="{yy}" stroke="{INK}" stroke-width="1.2" marker-end="url(#m-fill-ink)"/>', "Sequence flow"),
        (lambda x, yy: f'<line x1="{x + 2}" y1="{yy}" x2="{x + 28}" y2="{yy}" stroke="{MUTED}" stroke-width="1.1" stroke-dasharray="5,3" marker-start="url(#m-circ)" marker-end="url(#m-hollow)"/>', "Message flow"),
    ]
    leg_y = bottom + 16
    leg_svg, leg_h = legend(leg_items, 32, leg_y, width - 64)
    o.append(leg_svg)
    # title above pool
    o.insert(1, text(X0, 40, spec["title"], 13, INK, "start", 600))
    o.insert(1, text(X0 + pool_w, 40, "$BPMN 2.0 · Process", 9, SOFT, "end", 500, ls="0.12em"))
    height = g4(leg_y + leg_h)
    return width, height, "\n".join(o)


# ================================================================ HTML page
def page(slug, eyebrow, h1, desc, w, h, body, note=""):
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(h1)}</title>
  <link href="{FONT_LINK}" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: {SANS}; background: {PAPER}; color: {INK}; min-height: 100vh;
           display: flex; align-items: flex-start; justify-content: center; padding: 3rem 2rem; }}
    .frame {{ max-width: {w + 40}px; width: 100%; }}
    .diagram-container {{ width: 100%; overflow-x: auto; }}
    .eyebrow {{ font-family: {MONO}; font-size: 0.66rem; font-weight: 500; letter-spacing: 0.18em;
               text-transform: uppercase; color: {MUTED}; margin-bottom: 0.5rem; }}
    h1 {{ font-family: {SERIF}; font-size: clamp(1.5rem, 2.4vw + 0.75rem, 2rem); font-weight: 400;
         letter-spacing: -0.02em; line-height: 1.2; color: {INK}; margin-bottom: 1.5rem; }}
    .note {{ font-size: 0.8rem; line-height: 1.6; color: {MUTED}; margin-top: 1rem; max-width: 70ch; }}
    .nav {{ font-family: {MONO}; font-size: 0.7rem; margin-bottom: 1rem; }}
    .nav a {{ color: {LINK}; text-decoration: none; margin-right: 1rem; }}
    svg {{ width: 100%; min-width: {w}px; display: block; }}
    @media print {{ .diagram-container {{ overflow-x: visible; }} svg {{ min-width: 0; }} .nav {{ display: none; }} }}
  </style>
</head>
<body>
  <div class="frame">
    <p class="nav"><a href="index.html">← Mục lục</a></p>
    <p class="eyebrow">{esc(eyebrow)}</p>
    <h1>{esc(h1)}</h1>
    <div class="diagram-container">
      <svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="{slug}-title {slug}-desc">
        <title id="{slug}-title">{esc(h1)}</title>
        <desc id="{slug}-desc">{esc(desc)}</desc>
        {defs()}
        {body}
      </svg>
    </div>
    {f'<p class="note">{esc(note)}</p>' if note else ''}
  </div>
</body>
</html>
"""
