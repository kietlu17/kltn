"""Buyer use cases drawn as a flowchart (same content as the Mermaid source).

    python docs/diagrams/usecase/build_flowchart.py
    node docs/diagrams/uml/render_png.cjs --dir usecase usecase-nguoi-mua-flowchart
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uml"))

from engine import INK, MUTED, PAPER, SOFT, WHITE, legend, page, rpath, text  # noqa: E402

W = 1280
EXT_FILL, EXT_STROKE = "rgba(45,49,66,0.03)", "rgba(45,49,66,0.45)"
INPUT_FILL = "rgba(79,93,117,0.10)"

USE_CASES = [
    "Quản lý tài khoản và địa chỉ",
    "Tìm sản phẩm và hỏi chính sách",
    "Quản lý giỏ hàng",
    "Đặt hàng và thanh toán",
    "Tra cứu đơn và hỗ trợ sau mua",
]
UW, UH, UY = 208, 56, 268
UX = [72 + i * (UW + 24) for i in range(5)]
UCX = [x + UW / 2 for x in UX]
BUYER = (540, 72, 200, 56)
AI = (UCX[1] - 100, 448, 200, 56)
PAY = (UCX[3] - 124, 448, 248, 56)


def rect_node(x, y, w, h, name, sub, fill, stroke, dash=""):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>'
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.2"{dash}/>'
            + text(x + w / 2, y + 25, name, 13, INK, "middle", 600)
            + text(x + w / 2, y + 42, "$" + sub, 9, SOFT, "middle"))


def line(pts):
    d, _ = rpath(pts, 8)
    return f'<path d="{d}" fill="none" stroke="{MUTED}" stroke-width="1.2"/>'


def build():
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    # platform subgraph
    zx, zy, zw, zh = 48, 228, 1184, 140
    o.append(f'<rect x="{zx}" y="{zy}" width="{zw}" height="{zh}" rx="8" fill="rgba(45,49,66,0.025)" stroke="rgba(45,49,66,0.30)" stroke-width="1" stroke-dasharray="5,4"/>')
    # label sits on the bottom-left border, where no connector crosses
    o.append(f'<rect x="{zx + 16}" y="{zy + zh - 9}" width="196" height="18" rx="2" fill="{PAPER}"/>')
    o.append(text(zx + 24, zy + zh + 5, "Nền tảng thương mại điện tử", 12, SOFT, "start", 600))

    # Buyer -> 5 use cases: fanned ports, outermost branch turns first
    bx, by, bw, bh = BUYER
    ports = [bx + bw * (k + 1) / 6 for k in range(5)]
    turns = [156, 168, None, 168, 156]
    targets = [UCX[0], UCX[1] - 16, UCX[2], UCX[3] - 16, UCX[4]]
    for k in range(5):
        if turns[k] is None:
            o.append(line([(ports[k], by + bh), (targets[k], UY)]))
        else:
            o.append(line([(ports[k], by + bh), (ports[k], turns[k]), (targets[k], turns[k]), (targets[k], UY)]))
    # external systems -> their use case (bottom edge)
    o.append(line([(AI[0] + AI[2] / 2, AI[1]), (UCX[1], UY + UH)]))
    o.append(line([(PAY[0] + PAY[2] / 2, PAY[1]), (UCX[3], UY + UH)]))

    # nodes
    o.append(rect_node(*BUYER, "Người mua", "actor", INPUT_FILL, SOFT))
    for x, cx, name in zip(UX, UCX, USE_CASES):
        o.append(f'<rect x="{x}" y="{UY}" width="{UW}" height="{UH}" rx="28" fill="{WHITE}" stroke="{INK}" stroke-width="1.2"/>')
        o.append(text(cx, UY + UH / 2 + 5, name, 12, INK, "middle", 500))
    o.append(rect_node(*AI, "ChatBot", "external", EXT_FILL, EXT_STROKE, ' stroke-dasharray="4,3"'))
    o.append(rect_node(*PAY, "Hệ thống thanh toán bên ngoài", "external", EXT_FILL, EXT_STROKE, ' stroke-dasharray="4,3"'))

    leg_items = [
        (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="30" height="16" rx="3" fill="{INPUT_FILL}" stroke="{SOFT}"/>', "Người dùng"),
        (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="30" height="16" rx="8" fill="{WHITE}" stroke="{INK}"/>', "Chức năng (use case)"),
        (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="30" height="16" rx="3" fill="{EXT_FILL}" stroke="{EXT_STROKE}" stroke-dasharray="4,3"/>', "Hệ thống bên ngoài"),
        (lambda x, y: f'<line x1="{x}" y1="{y}" x2="{x + 30}" y2="{y}" stroke="{MUTED}" stroke-width="1.2"/>', "Liên kết"),
        (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="30" height="16" rx="3" fill="rgba(45,49,66,0.025)" stroke="rgba(45,49,66,0.30)" stroke-dasharray="5,4"/>', "Phạm vi nền tảng"),
    ]
    leg, lh = legend(leg_items, 32, 544, W - 64)
    o.append(leg)
    return W, 544 + lh + 8, "\n".join(o)


def main():
    w, h, body = build()
    html = page("usecase-nguoi-mua-flowchart", "Flowchart · Người mua",
                "Chức năng của Người mua",
                "Người mua dùng năm chức năng của nền tảng; ChatBot hỗ trợ tìm sản phẩm, "
                "hệ thống thanh toán bên ngoài hỗ trợ đặt hàng.", w, h, body)
    html = html.replace('<p class="nav"><a href="index.html">← Mục lục</a></p>', "")
    (HERE / "usecase-nguoi-mua-flowchart.html").write_text(html, encoding="utf-8")
    print("usecase-nguoi-mua-flowchart.html")


if __name__ == "__main__":
    main()
