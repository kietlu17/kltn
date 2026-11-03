"""Render a research figure for the current chatbot-service architecture."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).with_name("chatbot-architecture-current.png")
W, H = 2200, 1320
NAVY = "#102D55"
TEAL = "#087F8C"
BLUE = "#377BE5"
PURPLE = "#7654A3"
MUTED = "#4F657A"
BG = "#F8FBFE"
PALE = "#EAF7F7"
LIGHT = "#EFF5FF"
WHITE = "#FFFFFF"

im = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(im)
font_path = r"C:\Windows\Fonts\segoeui.ttf"
bold_path = r"C:\Windows\Fonts\segoeuib.ttf"


def font(size, bold=False):
    return ImageFont.truetype(bold_path if bold else font_path, size)


def center(x0, y0, x1, y1, lines, size=27, bold=False, color=NAVY, gap=3):
    if isinstance(lines, str):
        lines = [lines]
    f = font(size, bold)
    heights = [d.textbbox((0, 0), line, font=f)[3] - d.textbbox((0, 0), line, font=f)[1] for line in lines]
    total = sum(heights) + gap * (len(lines) - 1)
    y = (y0 + y1 - total) / 2
    for line, height in zip(lines, heights):
        width = d.textbbox((0, 0), line, font=f)[2]
        d.text(((x0 + x1 - width) / 2, y), line, font=f, fill=color)
        y += height + gap


def box(rect, lines, *, fill=WHITE, outline=TEAL, size=27, bold=False, radius=20, width=3):
    d.rounded_rectangle(rect, radius=radius, fill=fill, outline=outline, width=width)
    center(*rect, lines, size=size, bold=bold)


def arrow(points, color=TEAL, width=5, dashed=False, head=17):
    for a, b in zip(points, points[1:]):
        if dashed:
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = (dx * dx + dy * dy) ** 0.5
            if not length:
                continue
            ux, uy = dx / length, dy / length
            t = 0
            while t < length:
                e = min(length, t + 17)
                d.line([(a[0] + ux * t, a[1] + uy * t),
                        (a[0] + ux * e, a[1] + uy * e)], fill=color, width=width)
                t += 28
        else:
            d.line([a, b], fill=color, width=width, joint="curve")
    a, b = points[-2], points[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length:
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        d.polygon([b, (b[0] - ux * head + px * head * .48,
                       b[1] - uy * head + py * head * .48),
                    (b[0] - ux * head - px * head * .48,
                       b[1] - uy * head - py * head * .48)], fill=color)


# Title and model layer.
center(80, 24, 2120, 100, "KIẾN TRÚC CHATBOT SERVICE HIỆN TẠI", 61, True)
d.line((80, 108, 2120, 108), fill="#C8DCE9", width=3)
box((1080, 140, 1515, 248),
    ["Gemini", "LLM, embedding văn bản", "và mô tả ảnh"],
    fill=LIGHT, outline=BLUE, size=22, bold=True)
box((1610, 140, 2110, 248),
    ["Dịch vụ CLIP", "Embedding ảnh catalog", "và ảnh truy vấn"],
    fill=LIGHT, outline=BLUE, size=22, bold=True)

# Entry and rule-based router.
box((55, 505, 250, 650), ["NGƯỜI MUA", "Văn bản / ảnh"], fill=PALE, size=27, bold=True)
box((310, 505, 500, 650), ["Frontend"], fill=PALE, size=31, bold=True)
box((560, 505, 760, 650), ["API Gateway"], fill=PALE, size=30, bold=True)
box((825, 445, 1070, 710),
    ["Router Agent", "LangGraph", "Phân tuyến", "bằng quy tắc"],
    fill=PALE, size=24, bold=True)
arrow([(250, 578), (310, 578)])
arrow([(500, 578), (560, 578)])
arrow([(760, 578), (825, 578)])

# Domain branches.
box((1160, 292, 1525, 720), [""], fill="#EAF8F8", outline=TEAL)
center(1180, 306, 1505, 355, "PRODUCT AGENT", 31, True)
box((1190, 370, 1495, 438), "Product RAG", fill=WHITE, size=29, bold=True)
box((1190, 455, 1495, 523), "Kiểm tra & xếp hạng", fill=WHITE, size=26, bold=True)
box((1190, 540, 1495, 608), "Commerce tools", fill=WHITE, size=27, bold=True)
box((1190, 625, 1495, 693), "Trả lời / hỏi lại", fill=WHITE, size=26, bold=True)
box((1160, 790, 1525, 910), ["CUSTOMER SERVICE", "AGENT · Policy RAG"], fill="#EAF8F8", size=25, bold=True)
box((1160, 965, 1525, 1085), ["ORDER AGENT", "Tra cứu đơn (chỉ đọc)"], fill="#EAF8F8", size=27, bold=True)

arrow([(1070, 520), (1120, 520), (1120, 500), (1160, 500)])
arrow([(1070, 595), (1110, 595), (1110, 850), (1160, 850)])
arrow([(1070, 630), (1095, 630), (1095, 1025), (1160, 1025)])

# Data sources and service calls. Dashed blue is Qdrant retrieval.
box((1680, 295, 2145, 356), "Qdrant: văn bản + mô tả ảnh", fill=LIGHT, outline=BLUE, size=25)
box((1680, 375, 2145, 436), "Qdrant: vector ảnh CLIP", fill=LIGHT, outline=BLUE, size=25)
box((1680, 467, 2145, 545), ["Product Service", "Inventory Service · Review Service"], fill=WHITE, size=25)
box((1680, 568, 2145, 646), ["Cart Service · Voucher Service", "Thao tác giỏ sau xác nhận"], fill=WHITE, size=25)
box((1680, 815, 2145, 885), "Qdrant: chính sách Shopee Help PDF", fill=LIGHT, outline=BLUE, size=24)
box((1680, 990, 2145, 1060), "Order Service (tài khoản xác thực)", fill=WHITE, size=24)

arrow([(1495, 399), (1570, 399), (1570, 325), (1680, 325)], BLUE, dashed=True)
arrow([(1495, 416), (1595, 416), (1595, 405), (1680, 405)], BLUE, dashed=True)
arrow([(1495, 488), (1680, 488)])
arrow([(1495, 574), (1680, 574)])
arrow([(1525, 850), (1680, 850)], BLUE, dashed=True)
arrow([(1525, 1025), (1680, 1025)])
arrow([(2110, 195), (2170, 195), (2170, 405), (2145, 405)], PURPLE)
center(1605, 255, 2115, 287, "Vector ảnh được lưu riêng", 20, False, PURPLE)

# Model use labels, intentionally no Gemini-to-router arrow.
center(1075, 258, 1535, 285, "Dùng tại Product Agent và Policy Agent", 22, False, PURPLE)
arrow([(1297, 248), (1297, 292)], PURPLE)

# Handoff and legend.
box((515, 1165, 2080, 1260),
    ["BÀN GIAO THANH TOÁN: Chatbot chọn dòng giỏ → Frontend mở trang thanh toán",
     "Người mua kiểm tra, xác nhận đặt hàng và tự thanh toán"],
    fill="#E4F5EE", outline="#279B75", size=27, bold=True)
arrow([(95, 1190), (165, 1190)], BLUE, dashed=True)
d.text((184, 1173), "Truy xuất vector", font=font(23), fill=NAVY)
arrow([(95, 1240), (165, 1240)], TEAL)
d.text((184, 1223), "Gọi API nghiệp vụ", font=font(23), fill=NAVY)

OUT.parent.mkdir(parents=True, exist_ok=True)
im.save(OUT, optimize=True)
print(OUT)
