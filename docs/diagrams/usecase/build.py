"""UML use case diagram for the buyer (redrawn from the Mermaid source).

    python docs/diagrams/usecase/build.py
    node docs/diagrams/uml/render_png.cjs --dir usecase
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uml"))

from engine import INK, MUTED, PAPER, SOFT, WHITE, legend, page, text  # noqa: E402

W, H = 1040, 660
SYS = (276, 72, 488, 512)          # system boundary x, y, w, h
UC_CX, UC_RX, UC_RY = 520, 176, 32
USE_CASES = [
    "Quản lý tài khoản và địa chỉ",
    "Tìm sản phẩm và hỏi chính sách",
    "Quản lý giỏ hàng",
    "Đặt hàng và thanh toán",
    "Tra cứu đơn và hỗ trợ sau mua",
]
UC_Y = [168, 256, 344, 432, 520]


def actor(cx, cy, name, sub=None):
    """Stick figure centred on (cx, cy); name below."""
    top = cy - 34
    o = [f'<g stroke="{INK}" stroke-width="1.5" fill="none">'
         f'<circle cx="{cx}" cy="{top + 8}" r="8" fill="{WHITE}"/>'
         f'<line x1="{cx}" y1="{top + 16}" x2="{cx}" y2="{top + 40}"/>'
         f'<line x1="{cx - 16}" y1="{top + 24}" x2="{cx + 16}" y2="{top + 24}"/>'
         f'<line x1="{cx}" y1="{top + 40}" x2="{cx - 13}" y2="{top + 58}"/>'
         f'<line x1="{cx}" y1="{top + 40}" x2="{cx + 13}" y2="{top + 58}"/></g>',
         text(cx, top + 78, name, 12.5, INK, "middle", 600)]
    if sub:
        o.append(text(cx, top + 94, sub, 11, MUTED, "middle"))
    return "\n".join(o)


def build():
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    x, y, w, h = SYS
    # associations first (straight lines, UML use case convention)
    bx, by = 112, 340
    for uy in UC_Y:
        o.append(f'<line x1="{bx + 22}" y1="{by - 12}" x2="{UC_CX - UC_RX}" y2="{uy}" stroke="{MUTED}" stroke-width="1.2"/>')
    ax, ay = 928, UC_Y[1]
    px, py = 928, UC_Y[3]
    o.append(f'<line x1="{UC_CX + UC_RX}" y1="{ay}" x2="{ax - 24}" y2="{ay}" stroke="{MUTED}" stroke-width="1.2"/>')
    o.append(f'<line x1="{UC_CX + UC_RX}" y1="{py}" x2="{px - 24}" y2="{py}" stroke="{MUTED}" stroke-width="1.2"/>')
    # system boundary
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="rgba(45,49,66,0.025)" stroke="{INK}" stroke-width="1.2"/>')
    o.append(text(x + w / 2, y + 34, "Nền tảng thương mại điện tử", 14, INK, "middle", 600))
    o.append(f'<line x1="{x + 24}" y1="{y + 52}" x2="{x + w - 24}" y2="{y + 52}" stroke="rgba(45,49,66,0.14)" stroke-width="1"/>')
    # use cases
    for name, uy in zip(USE_CASES, UC_Y):
        o.append(f'<ellipse cx="{UC_CX}" cy="{uy}" rx="{UC_RX}" ry="{UC_RY}" fill="{WHITE}" stroke="{INK}" stroke-width="1.2"/>')
        o.append(text(UC_CX, uy + 5, name, 13, INK, "middle", 500))
    # actors
    o.append(actor(bx, by, "Người mua"))
    o.append(actor(ax, ay, "Dịch vụ mô hình AI", "«system»"))
    o.append(actor(px, py, "Hệ thống thanh toán", "bên ngoài · «system»"))
    leg_items = [
        (lambda lx, ly: f'<g stroke="{INK}" stroke-width="1.1" fill="none"><circle cx="{lx + 15}" cy="{ly - 6}" r="4" fill="{WHITE}"/><line x1="{lx + 15}" y1="{ly - 2}" x2="{lx + 15}" y2="{ly + 6}"/><line x1="{lx + 9}" y1="{ly + 1}" x2="{lx + 21}" y2="{ly + 1}"/><line x1="{lx + 15}" y1="{ly + 6}" x2="{lx + 10}" y2="{ly + 12}"/><line x1="{lx + 15}" y1="{ly + 6}" x2="{lx + 20}" y2="{ly + 12}"/></g>', "Tác nhân"),
        (lambda lx, ly: f'<ellipse cx="{lx + 15}" cy="{ly}" rx="15" ry="8" fill="{WHITE}" stroke="{INK}"/>', "Use case"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 30}" y2="{ly}" stroke="{MUTED}" stroke-width="1.2"/>', "Liên kết (association)"),
        (lambda lx, ly: f'<rect x="{lx}" y="{ly - 8}" width="30" height="16" rx="2" fill="rgba(45,49,66,0.025)" stroke="{INK}"/>', "Ranh giới hệ thống"),
    ]
    leg, lh = legend(leg_items, 32, 608, W - 64)
    o.append(leg)
    return W, 608 + lh + 8, "\n".join(o)


def main():
    w, h, body = build()
    html = page("usecase-nguoi-mua", "UML 2.5 · Use case diagram · Người mua",
                "Use case của Người mua", "Năm use case của người mua trong nền tảng thương mại điện tử, "
                "với dịch vụ mô hình AI hỗ trợ tìm sản phẩm và hệ thống thanh toán bên ngoài hỗ trợ đặt hàng.",
                w, h, body)
    html = html.replace('<p class="nav"><a href="index.html">← Mục lục</a></p>', "")
    (HERE / "usecase-nguoi-mua.html").write_text(html, encoding="utf-8")
    print("usecase-nguoi-mua.html")


if __name__ == "__main__":
    main()
