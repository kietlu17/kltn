"""Domain model (conceptual class diagram) of the marketplace, in Vietnamese business terms.

Unlike the ERD / class diagram it ignores service boundaries: associations follow the
business meaning (who places, owns, reviews, pays what). Roles are generalizations of
Tài khoản because auth-service stores one account with role buyer | seller | admin.

    python docs/diagrams/domain/build.py
    node docs/diagrams/uml/render_png.cjs --dir domain
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uml"))

from engine import ACCENT, ACCENT_TINT, INK, MUTED, PAPER, SOFT, WHITE, label, legend, page, text, tw  # noqa: E402

BW, PX, PY = 214, 320, 196


def cx(c):
    return 150 + PX * c


def cy(r):
    return 132 + PY * (r + 1)


# name: (col, row, attributes, kind)
CONCEPTS = {
    "Tài khoản": (3, -1, ["email", "vai trò", "trạng thái hoạt động"], "abstract"),
    "Địa chỉ": (0, 0, ["người nhận, số điện thoại", "địa chỉ chi tiết", "mặc định?"], ""),
    "Người mua": (1, 0, ["họ tên", "số điện thoại"], ""),
    "Quản trị viên": (3, 0, [], ""),
    "Hội thoại": (5, 0, ["sản phẩm đang hỏi", "tin nhắn cuối"], ""),
    "Tin nhắn": (6, 0, ["người gửi", "nội dung", "thời điểm"], ""),
    "Người bán": (7, 0, [], ""),
    "Ví": (0, 1, ["số dư khả dụng", "số dư tạm giữ"], ""),
    "Giỏ hàng": (1, 1, ["các dòng: biến thể × số lượng"], ""),
    "Gian hàng": (7, 1, ["tên, mô tả", "mã số thuế", "chế độ xuất hóa đơn"], ""),
    "Quyết toán": (8, 1, ["số tiền", "ngày đủ điều kiện", "trạng thái chi trả"], ""),
    "Giao dịch ví": (0, 2, ["loại (nạp, thanh toán, hoàn)", "số tiền", "số dư sau"], ""),
    "Đơn hàng": (4, 2, ["dòng hàng (sản phẩm, giá, SL)", "tổng tiền, giảm giá", "trạng thái", "địa chỉ giao"], "focal"),
    "Voucher": (5, 2, ["mã", "mức giảm", "điều kiện, hạn dùng"], ""),
    "Đánh giá": (6, 2, ["số sao (1–5)", "nhận xét"], ""),
    "Sản phẩm": (7, 2, ["tên, mô tả, giá", "thông số", "trạng thái kiểm duyệt"], "focal"),
    "Danh mục": (8, 2, ["tên", "mô tả"], ""),
    "Khiếu nại": (3, 3, ["lý do, bằng chứng", "trạng thái xử lý"], ""),
    "Vận đơn": (5, 3, ["mã vận đơn", "đơn vị vận chuyển", "trạng thái giao"], ""),
    "Biến thể": (7, 3, ["tên (màu, size)", "SKU", "giá"], ""),
    "Tồn kho": (8, 3, ["tồn thực tế", "đang giữ chỗ"], ""),
    "Thanh toán": (4, 4, ["phương thức (COD, QR)", "số tiền", "trạng thái"], ""),
}


def h_of(name):
    n = len(CONCEPTS[name][2])
    return 34 + (8 + 15 * n + 4 if n else 0)


def box(name):
    c, r, _, _ = CONCEPTS[name]
    h = h_of(name)
    return cx(c) - BW / 2, cy(r) - h / 2, BW, h


def P(name, side, off=0.0):
    x, y, w, h = box(name)
    return {"t": (x + w / 2 + off, y), "b": (x + w / 2 + off, y + h),
            "l": (x, y + h / 2 + off), "r": (x + w, y + h / 2 + off)}[side]


def gap_below(r):
    """y in the empty band between row r and row r+1."""
    tallest_r = max(h_of(n) for n, v in CONCEPTS.items() if v[1] == r)
    tallest_n = max(h_of(n) for n, v in CONCEPTS.items() if v[1] == r + 1)
    return (cy(r) + tallest_r / 2 + cy(r + 1) - tallest_n / 2) / 2


G05, G15 = gap_below(0), gap_below(1)

# (A, B, association name, mult at A, mult at B, points from A to B, kind)
EDGES = [
    ("Quản trị viên", "Khiếu nại", "xử lý", "1", "0..*", [P("Quản trị viên", "b"), P("Khiếu nại", "t")], "assoc"),
    ("Đơn hàng", "Gian hàng", "thuộc về", "0..*", "1",
     [P("Đơn hàng", "t", 70), (P("Đơn hàng", "t", 70)[0], P("Gian hàng", "l", 12)[1]), P("Gian hàng", "l", 12)], "assoc"),
    ("Quản trị viên", "Sản phẩm", "kiểm duyệt", "1", "0..*",
     [P("Quản trị viên", "b", 60), (P("Quản trị viên", "b", 60)[0], G15), (P("Sản phẩm", "t", -60)[0], G15),
      P("Sản phẩm", "t", -60)], "assoc"),
    ("Người mua", "Địa chỉ", "có", "1", "0..*", [P("Người mua", "l", -12), (P("Địa chỉ", "r")[0], P("Người mua", "l", -12)[1])], "comp"),
    ("Người mua", "Giỏ hàng", "sở hữu", "1", "1", [P("Người mua", "b"), P("Giỏ hàng", "t")], "assoc"),
    ("Người mua", "Ví", "có", "1", "1",
     [P("Người mua", "l", 14), ((cx(0) + cx(1)) / 2, P("Người mua", "l", 14)[1]), ((cx(0) + cx(1)) / 2, P("Ví", "r")[1]),
      P("Ví", "r")], "assoc"),
    ("Người mua", "Đơn hàng", "đặt", "1", "0..*",
     [P("Người mua", "r", 12), (cx(2) - 24, P("Người mua", "r", 12)[1]), (cx(2) - 24, P("Đơn hàng", "l")[1]),
      P("Đơn hàng", "l")], "assoc"),
    ("Người mua", "Hội thoại", "mở", "1", "0..*",
     [P("Người mua", "r", -12), (cx(2) + 12, P("Người mua", "r", -12)[1]), (cx(2) + 12, G05),
      (P("Hội thoại", "b", -60)[0], G05), P("Hội thoại", "b", -60)], "assoc"),
    ("Hội thoại", "Tin nhắn", "gồm", "1", "0..*", [P("Hội thoại", "r"), P("Tin nhắn", "l")], "comp"),
    ("Gian hàng", "Hội thoại", "trả lời", "1", "0..*",
     [P("Gian hàng", "l", -12), (P("Hội thoại", "b", 60)[0], P("Gian hàng", "l", -12)[1]), P("Hội thoại", "b", 60)], "assoc"),
    ("Người bán", "Gian hàng", "quản lý", "1", "1", [P("Người bán", "b"), P("Gian hàng", "t")], "assoc"),
    ("Gian hàng", "Quyết toán", "nhận", "1", "0..*", [P("Gian hàng", "r"), P("Quyết toán", "l")], "assoc"),
    ("Gian hàng", "Sản phẩm", "đăng bán", "1", "0..*", [P("Gian hàng", "b"), P("Sản phẩm", "t")], "assoc"),
    ("Ví", "Giao dịch ví", "ghi nhận", "1", "0..*", [P("Ví", "b"), P("Giao dịch ví", "t")], "comp"),
    ("Đơn hàng", "Voucher", "áp dụng", "0..*", "0..1", [P("Đơn hàng", "r"), P("Voucher", "l")], "assoc"),
    ("Đơn hàng", "Thanh toán", "thanh toán qua", "1", "1..*", [P("Đơn hàng", "b"), P("Thanh toán", "t")], "assoc-left"),
    ("Đơn hàng", "Khiếu nại", "phát sinh", "1", "0..*",
     [P("Đơn hàng", "b", -70), (P("Đơn hàng", "b", -70)[0], P("Khiếu nại", "r")[1]), P("Khiếu nại", "r")], "assoc"),
    ("Đơn hàng", "Vận đơn", "giao bằng", "1", "0..*",
     [P("Đơn hàng", "b", 70), (P("Đơn hàng", "b", 70)[0], P("Vận đơn", "l")[1]), P("Vận đơn", "l")], "assoc"),
    ("Sản phẩm", "Đánh giá", "được đánh giá", "1", "0..*", [P("Sản phẩm", "l"), P("Đánh giá", "r")], "assoc"),
    ("Sản phẩm", "Danh mục", "thuộc", "0..*", "0..1", [P("Sản phẩm", "r"), P("Danh mục", "l")], "assoc"),
    ("Sản phẩm", "Biến thể", "có", "1", "1..*", [P("Sản phẩm", "b"), P("Biến thể", "t")], "comp"),
    ("Biến thể", "Tồn kho", "được theo dõi", "1", "1", [P("Biến thể", "r"), P("Tồn kho", "l")], "assoc"),
]

DEFS = f"""<defs>
  <marker id="d-comp" markerWidth="18" markerHeight="10" refX="1" refY="5" orient="auto"><polygon points="1 5, 9 1, 17 5, 9 9" fill="{INK}" stroke="{INK}"/></marker>
  <marker id="d-tri" markerWidth="16" markerHeight="14" refX="15" refY="7" orient="auto"><polygon points="1 1, 15 7, 1 13" fill="{PAPER}" stroke="{INK}" stroke-width="1.1"/></marker>
</defs>"""


def path_with_hops(pts, verticals, r=8, hop=6):
    """Rounded orthogonal path; horizontal runs hop over earlier vertical segments."""
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    n = len(pts)
    starts, ends = [pts[0]], []
    for i in range(1, n - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        lin = abs(b[0] - a[0]) + abs(b[1] - a[1])
        lout = abs(c[0] - b[0]) + abs(c[1] - b[1])
        rr = min(r, lin / 2, lout / 2)
        ux, uy = ((b[0] - a[0]) / lin, (b[1] - a[1]) / lin)
        vx, vy = ((c[0] - b[0]) / lout, (c[1] - b[1]) / lout)
        ends.append((b[0] - ux * rr, b[1] - uy * rr))
        starts.append((b[0] + vx * rr, b[1] + vy * rr))
    ends.append(pts[-1])
    for i in range(n - 1):
        s, e = starts[i], ends[i]
        if abs(s[1] - e[1]) < 0.5:  # horizontal: add hops
            sgn = 1 if e[0] > s[0] else -1
            xs = sorted((vx for (vx, y0, y1) in verticals
                         if min(s[0], e[0]) + 10 < vx < max(s[0], e[0]) - 10 and min(y0, y1) + 2 < s[1] < max(y0, y1) - 2),
                        reverse=(sgn < 0))
            for vx in xs:
                d += f" L{vx - sgn * hop:.1f},{s[1]:.1f} a{hop},{hop} 0 0,{1 if sgn > 0 else 0} {sgn * 2 * hop},0"
        d += f" L{e[0]:.1f},{e[1]:.1f}"
        if i < n - 2:
            b = pts[i + 1]
            d += f" Q{b[0]:.1f},{b[1]:.1f} {starts[i + 1][0]:.1f},{starts[i + 1][1]:.1f}"
    return d


def build():
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>', DEFS]
    verticals = []
    labels = []
    # generalization tree: roles -> Tài khoản (shared hollow triangle)
    acc = P("Tài khoản", "b")
    bus = (acc[1] + min(box(n)[1] for n in ("Người mua", "Quản trị viên", "Người bán"))) / 2
    for role in ("Người mua", "Người bán"):
        t = P(role, "t")
        d = path_with_hops([t, (t[0], bus), (acc[0], bus)], [])
        o.append(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="1.1"/>')
        verticals.append((t[0], t[1], bus))
    qt = P("Quản trị viên", "t")
    o.append(f'<line x1="{qt[0]}" y1="{qt[1]}" x2="{acc[0]}" y2="{acc[1] + 1}" stroke="{INK}" stroke-width="1.1" marker-end="url(#d-tri)"/>')
    for (a, b, name, ma, mb, pts, kind) in EDGES:
        d = path_with_hops(pts, verticals)
        start = ' marker-start="url(#d-comp)"' if kind == "comp" else ""
        o.append(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="1.1"{start}/>')
        for i in range(len(pts) - 1):
            if abs(pts[i][0] - pts[i + 1][0]) < 0.5:
                verticals.append((pts[i][0], pts[i][1], pts[i + 1][1]))
        # multiplicities near both ends
        for (p0, p1, m, far) in ((pts[0], pts[1], ma, kind == "comp"), (pts[-1], pts[-2], mb, False)):
            if abs(p0[1] - p1[1]) < 0.5:  # horizontal end
                sgn = 1 if p1[0] > p0[0] else -1
                off = 26 if far else 12
                labels.append(label(p0[0] + sgn * off, p0[1] - 7, "$" + m, 9, INK, "start" if sgn > 0 else "end", 600, 2))
            else:
                sgn = 1 if p1[1] > p0[1] else -1
                off = 28 if far else 16
                labels.append(label(p0[0] - 8, p0[1] + sgn * off + 4, "$" + m, 9, INK, "end", 600, 2))
        # association name on the longest segment
        k = max(range(len(pts) - 1), key=lambda i: abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1]))
        (x0, y0), (x1, y1) = pts[k], pts[k + 1]
        if abs(y0 - y1) < 0.5:
            labels.append(label((x0 + x1) / 2, y0 + 16, name, 10.5, SOFT, "middle", 500, 3))
        elif kind == "assoc-left":
            labels.append(label(x0 - 8, y0 + (y1 - y0) * 0.8 + 4, name, 10.5, SOFT, "end", 500, 3))
        else:
            labels.append(label(x0 + 8, (y0 + y1) / 2 + 4, name, 10.5, SOFT, "start", 500, 3))
    o += labels
    for name, (c, r, attrs, kind) in CONCEPTS.items():
        x, y, w, h = box(name)
        stroke = ACCENT if kind == "focal" else INK
        fill = ACCENT_TINT if kind == "focal" else WHITE
        o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>')
        o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.1"/>')
        style = ' font-style="italic"' if kind == "abstract" else ""
        o.append(text(x + w / 2, y + 22, name, 13, INK, "middle", 600).replace("<text ", f"<text{style} ", 1))
        if attrs:
            o.append(f'<line x1="{x}" y1="{y + 34}" x2="{x + w}" y2="{y + 34}" stroke="{stroke}" stroke-width="0.8"/>')
            for i, a in enumerate(attrs):
                o.append(text(x + 12, y + 34 + 8 + 11 + 15 * i, a, 11, MUTED, "start"))
    width = cx(8) + BW / 2 + 48
    bottom = max(box(n)[1] + box(n)[3] for n in CONCEPTS) + 36
    items = [
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 34}" y2="{ly}" stroke="{INK}" stroke-width="1.1" marker-end="url(#d-tri)"/>', "Tổng quát hóa (vai trò của tài khoản)"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 34}" y2="{ly}" stroke="{INK}" stroke-width="1.1" marker-start="url(#d-comp)"/>', "Hợp thành (phần thuộc về toàn thể)"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 34}" y2="{ly}" stroke="{INK}" stroke-width="1.1"/>', "Liên kết · tên quan hệ · bội số"),
        (lambda lx, ly: f'<rect x="{lx}" y="{ly - 8}" width="34" height="16" rx="3" fill="{ACCENT_TINT}" stroke="{ACCENT}"/>', "Khái niệm trung tâm"),
        (lambda lx, ly: text(lx + 6, ly + 4, "Aa", 11, INK, "start", 600).replace("<text ", '<text font-style="italic" ', 1), "Khái niệm trừu tượng"),
    ]
    leg, lh = legend(items, 32, bottom, width - 64)
    o.append(leg)
    return width, bottom + lh + 8, "\n".join(o)


def main():
    w, h, body = build()
    html = page("domain-model", "Domain model · UML 2.5 conceptual class diagram", "Mô hình miền (domain model)",
                f"{len(CONCEPTS)} khái niệm nghiệp vụ của sàn thương mại điện tử và quan hệ giữa chúng, "
                "không phân theo service.", w, h, body,
                "Mô hình khái niệm: không có kiểu dữ liệu hay thao tác, quan hệ đi theo nghĩa nghiệp vụ nên được vẽ xuyên service "
                "(trong hệ thống thật chúng là tham chiếu qua ID). Người mua, Người bán, Quản trị viên là vai trò của cùng một Tài khoản "
                "trong auth-service. Mỗi đơn hàng thuộc một gian hàng; giỏ hàng và đơn hàng lưu dòng hàng theo biến thể sản phẩm.")
    html = html.replace('<p class="nav"><a href="index.html">← Mục lục</a></p>', "")
    (HERE / "domain-model.html").write_text(html, encoding="utf-8")
    print("domain-model.html")


if __name__ == "__main__":
    main()
