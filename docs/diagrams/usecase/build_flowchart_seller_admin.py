"""Seller and admin use cases drawn as a flowchart (same content as the Mermaid source).

    python docs/diagrams/usecase/build_flowchart_seller_admin.py
    node docs/diagrams/uml/render_png.cjs --dir usecase usecase-nguoi-ban-admin-flowchart
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uml"))
sys.path.insert(0, str(HERE))

from engine import INK, MUTED, PAPER, SOFT, WHITE, legend, page, text  # noqa: E402
from build_flowchart import INPUT_FILL, line, rect_node  # noqa: E402

W = 1512
UW, UH, UY = 208, 56, 268
GROUPS = [
    ("Người bán", ["Quản lý gian hàng và sản phẩm", "Quản lý đơn của gian hàng", "Trao đổi với người mua"]),
    ("Quản trị viên", ["Quản lý tài khoản và danh mục", "Kiểm duyệt sản phẩm", "Quản lý đơn và khiếu nại"]),
]
X0, GAP, GROUP_GAP = 72, 20, 56


def build():
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    zx, zy, zw, zh = 48, 228, W - 96, 140
    o.append(f'<rect x="{zx}" y="{zy}" width="{zw}" height="{zh}" rx="8" fill="rgba(45,49,66,0.025)" stroke="rgba(45,49,66,0.30)" stroke-width="1" stroke-dasharray="5,4"/>')
    o.append(f'<rect x="{zx + 16}" y="{zy + zh - 9}" width="196" height="18" rx="2" fill="{PAPER}"/>')
    o.append(text(zx + 24, zy + zh + 5, "Nền tảng thương mại điện tử", 12, SOFT, "start", 600))

    nodes = []
    x = X0
    for gi, (actor, cases) in enumerate(GROUPS):
        xs = []
        for name in cases:
            xs.append(x)
            nodes.append((x, name))
            x += UW + GAP
        x += GROUP_GAP - GAP
        cxs = [v + UW / 2 for v in xs]
        ax, ay, aw, ah = cxs[1] - 100, 72, 200, 56
        ports = [cxs[1] - 40, cxs[1], cxs[1] + 40]
        # connectors first, then the actor box on top
        o.append(line([(ports[0], ay + ah), (ports[0], 160), (cxs[0], 160), (cxs[0], UY)]))
        o.append(line([(ports[1], ay + ah), (cxs[1], UY)]))
        o.append(line([(ports[2], ay + ah), (ports[2], 160), (cxs[2], 160), (cxs[2], UY)]))
        o.append(rect_node(ax, ay, aw, ah, actor, "actor", INPUT_FILL, SOFT))

    for nx, name in nodes:
        o.append(f'<rect x="{nx}" y="{UY}" width="{UW}" height="{UH}" rx="28" fill="{WHITE}" stroke="{INK}" stroke-width="1.2"/>')
        o.append(text(nx + UW / 2, UY + UH / 2 + 5, name, 12, INK, "middle", 500))

    leg_items = [
        (lambda lx, ly: f'<rect x="{lx}" y="{ly - 8}" width="30" height="16" rx="3" fill="{INPUT_FILL}" stroke="{SOFT}"/>', "Người dùng"),
        (lambda lx, ly: f'<rect x="{lx}" y="{ly - 8}" width="30" height="16" rx="8" fill="{WHITE}" stroke="{INK}"/>', "Chức năng (use case)"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 30}" y2="{ly}" stroke="{MUTED}" stroke-width="1.2"/>', "Liên kết"),
        (lambda lx, ly: f'<rect x="{lx}" y="{ly - 8}" width="30" height="16" rx="3" fill="rgba(45,49,66,0.025)" stroke="rgba(45,49,66,0.30)" stroke-dasharray="5,4"/>', "Phạm vi nền tảng"),
    ]
    leg, lh = legend(leg_items, 32, 424, W - 64)
    o.append(leg)
    return W, 424 + lh + 8, "\n".join(o)


def main():
    w, h, body = build()
    html = page("usecase-nguoi-ban-admin-flowchart", "Flowchart · Người bán & Quản trị viên",
                "Chức năng của Người bán và Quản trị viên",
                "Người bán và quản trị viên, mỗi bên dùng ba chức năng của nền tảng thương mại điện tử.",
                w, h, body)
    html = html.replace('<p class="nav"><a href="index.html">← Mục lục</a></p>', "")
    (HERE / "usecase-nguoi-ban-admin-flowchart.html").write_text(html, encoding="utf-8")
    print("usecase-nguoi-ban-admin-flowchart.html")


if __name__ == "__main__":
    main()
