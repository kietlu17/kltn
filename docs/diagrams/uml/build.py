"""Regenerate every UML / BPMN diagram page plus index.html.

    python docs/diagrams/uml/build.py
    node docs/diagrams/uml/render_png.cjs      # PNG export (Edge via Playwright)
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine import build_activity, build_bpmn, build_sequence, esc, page, MONO, SANS, SERIF, PAPER, INK, MUTED, LINK, FONT_LINK  # noqa: E402
from specs import USECASES  # noqa: E402

KINDS = [
    ("sequence", "Sequence", "UML 2.5 · Sequence diagram", build_sequence),
    ("activity", "Activity", "UML 2.5 · Activity diagram", build_activity),
    ("bpmn", "BPMN", "BPMN 2.0 · Process diagram", build_bpmn),
]


def main(only=None):
    files = []
    for uc in USECASES:
        if only and uc["slug"] not in only:
            continue
        for key, short, eyebrow, fn in KINDS:
            spec = uc[key]
            spec.setdefault("title", uc["name"])
            w, h, body = fn(spec)
            slug = f'{uc["slug"]}-{key}'
            desc = spec.get("desc") or f'{short} diagram cho use case "{uc["name"]}" của tác nhân {uc["actor"]}.'
            html = page(slug, f'{eyebrow} · {uc["code"]} · {uc["actor"]}', f'{uc["code"]} · {uc["name"]}', desc, w, h, body,
                        spec.get("note", ""))
            out = HERE / f"{slug}.html"
            out.write_text(html, encoding="utf-8")
            files.append(out.name)
    write_index()
    print("\n".join(files))


def write_index():
    groups = {}
    for uc in USECASES:
        groups.setdefault(uc["actor"], []).append(uc)
    rows = []
    for actor, ucs in groups.items():
        rows.append(f'<h2>{esc(actor)}</h2><table>')
        for uc in ucs:
            links = " ".join(
                f'<a href="{uc["slug"]}-{k}.html">{s}</a> <a class="png" href="png/{uc["slug"]}-{k}.png">png</a>'
                for k, s, _, _ in KINDS)
            rows.append(f'<tr><td class="code">{esc(uc["code"])}</td><td>{esc(uc["name"])}</td><td class="links">{links}</td></tr>')
        rows.append('</table>')
    html = f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bộ sơ đồ UML &amp; BPMN theo use case</title>
<link href="{FONT_LINK}" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:{SANS};background:{PAPER};color:{INK};padding:3rem 2rem;display:flex;justify-content:center}}
.frame{{max-width:960px;width:100%}}
.eyebrow{{font-family:{MONO};font-size:.66rem;font-weight:500;letter-spacing:.18em;text-transform:uppercase;color:{MUTED};margin-bottom:.5rem}}
h1{{font-family:{SERIF};font-weight:400;font-size:2rem;letter-spacing:-.02em;margin-bottom:1rem}}
p.lead{{color:{MUTED};font-size:.9rem;line-height:1.6;margin-bottom:2rem;max-width:72ch}}
h2{{font-size:1rem;font-weight:600;margin:2rem 0 .5rem}}
table{{width:100%;border-collapse:collapse;font-size:.9rem}}
td{{padding:.6rem .5rem;border-top:1px solid rgba(45,49,66,.12);vertical-align:middle}}
td.code{{font-family:{MONO};font-size:.75rem;color:{MUTED};width:4.5rem}}
td.links{{text-align:right;white-space:nowrap}}
td.links a{{font-family:{MONO};font-size:.75rem;color:{LINK};text-decoration:none;margin-left:.25rem}}
td.links a.png{{color:{MUTED};margin-right:.9rem}}
</style></head><body><div class="frame">
<p class="eyebrow">ecommerce-microservices · UML 2.5 &amp; BPMN 2.0</p>
<h1>Sơ đồ Sequence, Activity và BPMN theo use case</h1>
<p class="lead">Mỗi use case có ba góc nhìn: Sequence (trao đổi thông điệp giữa các lifeline theo thời gian),
Activity (luồng hành động có phân vùng trách nhiệm) và BPMN (quy trình nghiệp vụ theo pool/lane).
Tên service, endpoint và topic Kafka lấy từ mã nguồn hiện tại của repo.</p>
{''.join(rows)}
</div></body></html>"""
    (HERE / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:] or None)
