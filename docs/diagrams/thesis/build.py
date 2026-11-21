"""Hình 3.2 – 4.4 của tài liệu khóa luận (phân hệ AI Chatbot / Agentic RAG).

    python docs/diagrams/thesis/build.py
    node docs/diagrams/uml/render_png.cjs --dir thesis

Redrawn from the Mermaid figures in the thesis Google Doc; participant names come
from the code (agentic rag/app, order-service checkoutController).
"""
from __future__ import annotations

import copy
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uml"))

from engine import (ACCENT, ACCENT_TINT, INK, MUTED, PAPER, SOFT, WHITE,  # noqa: E402
                    build_activity, build_sequence, label, legend, page, rpath, text)
from specs import E, act, dec, fin, ini, mrg  # noqa: E402

STORE_FILL = "rgba(45,49,66,0.05)"
INPUT_FILL = "rgba(79,93,117,0.10)"


def ff(lane, row, **kw):
    return dict(k="flowfinal", lane=lane, row=row, **kw)


def fork(lane, row, **kw):
    return dict(k="fork", lane=lane, row=row, **kw)


def join(lane, row, **kw):
    return dict(k="join", lane=lane, row=row, **kw)


# ---------------------------------------------------------------- participants
BUYER = dict(id="u", label="Người mua", kind="actor")
USER = dict(id="u", label="Người dùng", kind="actor")
WEB = dict(id="fe", label=":Web App", sub="React · chatbot UI")
AGENT = dict(id="ai", label=":Agentic RAG", sub="OrderAgent · LangGraph")
QUOTE = dict(id="chk", label=":Checkout Quote", sub="order-service")
CATINV = dict(id="ci", label=":Catalog · Inventory", sub="product / inventory-service")
ORDER = dict(id="ord", label=":Order Service", sub="POST /orders")
INDEXER = dict(id="idx", label=":Catalog Indexer", sub="agentic-indexer")
CATALOG = dict(id="cat", label=":Catalog Service", sub="product-service")
DOCS = dict(id="doc", label=":Bộ xử lý văn bản", sub="indexer/documents.py")
EMBED = dict(id="emb", label=":Embedding Model", sub="gemini-embedding-001", kind="ext")
QDRANT = dict(id="vec", label=":Qdrant", sub="vector store")
ROUTER = dict(id="gr", label=":LangGraph Router", sub="agentic-rag")
PRODUCT = dict(id="pa", label=":ProductAgent", sub="tool: search")
RETR = dict(id="rt", label=":Hybrid Retrieval", sub="BM25 + dense · Qdrant")
LLM = dict(id="llm", label=":LLM Provider", sub="Gemini API", kind="ext")

SEQUENCES = [
    ("hinh-3-6-tuan-tu-dat-hang", "Hình 3.6", "Xác nhận và thực hiện đặt hàng qua AI Chatbot", dict(
        parts=[BUYER, WEB, dict(AGENT, focal=True), QUOTE, CATINV, ORDER],
        steps=[
            ("m", "u", "fe", "Yêu cầu đặt sản phẩm"),
            ("m", "fe", "ai", "Gửi yêu cầu và ngữ cảnh"),
            ("m", "ai", "chk", "Đọc giỏ hàng và tạo báo giá"),
            ("m", "chk", "ai", "Quote và thông tin cần xác nhận", "ret"),
            ("m", "ai", "fe", "Hiển thị tóm tắt đơn hàng", "ret"),
            ("m", "fe", "u", "Yêu cầu xác nhận", "ret"),
            ("m", "u", "fe", "Xác nhận đặt hàng"),
            ("m", "fe", "ai", "Gửi xác nhận"),
            ("m", "ai", "chk", "Yêu cầu thực thi với quote"),
            ("m", "chk", "chk", "Xác thực và nhận quyền xử lý một lần"),
            ("m", "chk", "ci", "Kiểm tra lại giá và tồn kho"),
            ("m", "ci", "chk", "Kết quả kiểm tra", "ret"),
            ("m", "chk", "ord", "Tạo đơn với idempotency key"),
            ("m", "ord", "chk", "Kết quả tạo đơn", "ret"),
            ("m", "chk", "ai", "Trạng thái xử lý", "ret"),
            ("m", "ai", "fe", "Trả kết quả", "ret"),
            ("m", "fe", "u", "Thông báo trạng thái đơn hàng", "ret"),
        ])),
    ("hinh-4-2-tuan-tu-indexing", "Hình 4.2", "Tiền xử lý, Chunking, embedding và lập chỉ mục", dict(
        parts=[CATALOG, dict(INDEXER, focal=True), DOCS, EMBED, QDRANT],
        steps=[
            ("m", "idx", "cat", "Đọc dữ liệu sản phẩm"),
            ("m", "cat", "idx", "Dữ liệu sản phẩm", "ret"),
            ("m", "idx", "doc", "Kiểm tra và chuẩn hóa"),
            ("m", "doc", "idx", "Văn bản đã xử lý", "ret"),
            ("m", "idx", "idx", "Tạo các đơn vị truy xuất (chunk)"),
            ("m", "idx", "emb", "Gửi nội dung cần vector hóa"),
            ("m", "emb", "idx", "Embedding vectors", "ret"),
            ("m", "idx", "vec", "Upsert vector và metadata"),
            ("m", "vec", "idx", "Kết quả lập chỉ mục", "ret"),
        ])),
    ("hinh-4-3-tuan-tu-tu-van", "Hình 4.3", "Tư vấn sản phẩm thông qua Agentic RAG", dict(
        parts=[USER, WEB, ROUTER, dict(PRODUCT, focal=True), RETR, CATINV, LLM],
        steps=[
            ("m", "u", "fe", "“Tìm loa Bluetooth dưới 2 triệu, pin lâu”"),
            ("m", "fe", "gr", "Gửi tin nhắn và session context"),
            ("m", "gr", "pa", "Điều phối yêu cầu sản phẩm"),
            ("m", "pa", "rt", "Tìm kiếm theo tiêu chí"),
            ("m", "rt", "rt", "BM25 + Dense Retrieval"),
            ("m", "rt", "rt", "RRF / Reranking"),
            ("m", "rt", "pa", "Danh sách ứng viên", "ret"),
            ("m", "pa", "ci", "Đọc thông tin sản phẩm hiện tại"),
            ("m", "ci", "pa", "Giá và thông tin sản phẩm", "ret"),
            ("m", "pa", "llm", "Truy vấn + ngữ cảnh đã xác minh"),
            ("m", "llm", "pa", "Nội dung tư vấn", "ret"),
            ("m", "pa", "gr", "Kết quả xử lý", "ret"),
            ("m", "gr", "fe", "Câu trả lời và dữ liệu liên quan", "ret"),
            ("m", "fe", "u", "Hiển thị kết quả", "ret"),
        ])),
]

ACTIVITIES = [
    ("hinh-3-2-dieu-phoi-langgraph", "Hình 3.2", "Điều phối các nhánh xử lý trong LangGraph", dict(
        lanes=["ProductAgent", "LangGraph (Router · Policy)", "OrderAgent"], lws=[280, 320, 460],
        nodes=dict(
            i=ini(1, 0),
            a1=act(1, 1, "Nhận tin nhắn và State"),
            a2=act(1, 2, "Router / Supervisor", focal=True),
            d1=dec(1, 3, "Ý định?", tside="t"),
            p1=act(0, 4.4, "Retrieval + kiểm tra sản phẩm"),
            q1=act(1, 4.4, "Truy xuất thông tin chính sách"),
            o0=dec(2, 4.4, "Loại thao tác?", tside="r"),
            o1=act(2, 5.6, "Đọc dữ liệu nghiệp vụ", dx=-116, w=180),
            o2=act(2, 5.6, "Kiểm tra quyền và xác nhận", dx=116, w=180),
            o3=act(2, 6.8, "Thực thi qua Service", dx=116, w=180),
            m2=mrg(2, 8),
            m1=mrg(1, 8),
            a3=act(1, 9, "Tổng hợp kết quả"),
            a4=act(1, 10, "Cập nhật State / Checkpoint"),
            a5=act(1, 11, "Trả lời người dùng"),
            f=fin(1, 12)),
        edges=[
            E("i", "a1"), E("a1", "a2"), E("a2", "d1"),
            E("d1", "p1", "sản phẩm", fp="l", tp="t", gpos="end-l"),
            E("d1", "q1", "chính sách", gpos="left"),
            E("d1", "o0", "giỏ hàng / đơn hàng", fp="r", tp="t", gpos="end-l"),
            E("o0", "o1", "tra cứu", fp="l", tp="t", gpos="end-l"),
            E("o0", "o2", "thay đổi trạng thái", fp="r", tp="t", gpos="end-l"),
            E("o2", "o3"),
            E("o1", "m2", fp="b", tp="l"), E("o3", "m2", fp="b", tp="r"),
            E("p1", "m1", fp="b", tp="l"), E("q1", "m1"), E("m2", "m1", fp="l", tp="r"),
            E("m1", "a3"), E("a3", "a4"), E("a4", "a5"), E("a5", "f"),
        ])),
    ("hinh-3-3-hybrid-retrieval", "Hình 3.3", "Hybrid Retrieval và tạo câu trả lời", dict(
        lanes=["ProductAgent", "Hybrid Retrieval"], lws=[320, 480],
        nodes=dict(
            i=ini(0, 0),
            a1=act(0, 1, "Nhận truy vấn tiếng Việt"),
            a2=act(0, 2, "Chuẩn hóa truy vấn"),
            fk=fork(1, 3, w=300),
            b1=act(1, 4, "BM25 Retrieval", dx=-112, w=170),
            e1=act(1, 4, "Embedding Query", dx=112, w=170),
            e2=act(1, 5, "Dense Retrieval", dx=112, w=170),
            jn=join(1, 6, w=300),
            r1=act(1, 7, "Product-Level RRF", focal=True),
            r2=act(1, 8, "Danh sách ứng viên"),
            d1=dec(1, 9, "Bật Reranker?", tside="l"),
            ce=act(1, 10.2, "Cross-Encoder rerank", dx=112, w=170),
            m1=mrg(1, 11.4),
            g1=act(1, 12.4, "Nhóm theo Product ID"),
            s1=act(0, 13.4, "Lấy thông tin sản phẩm hiện tại"),
            s2=act(0, 14.4, "Xây dựng ngữ cảnh"),
            s3=act(0, 15.4, "LLM tạo câu trả lời"),
            s4=act(0, 16.4, "Trả kết quả cho Chatbot"),
            f=fin(0, 17.4)),
        edges=[
            E("i", "a1"), E("a1", "a2"), E("a2", "fk", fp="r", tp="t"),
            E("fk", "b1", fp="b:-112", tp="t"), E("fk", "e1", fp="b:112", tp="t"),
            E("e1", "e2"),
            E("b1", "jn", fp="b", tp="t:-112"), E("e2", "jn", fp="b", tp="t:112"),
            E("jn", "r1"), E("r1", "r2"), E("r2", "d1"),
            E("d1", "ce", "có", fp="r", tp="t", gpos="end"),
            E("d1", "m1", "không", gpos="left"),
            E("ce", "m1", fp="b", tp="r"),
            E("m1", "g1"), E("g1", "s1", fp="l", tp="t"),
            E("s1", "s2"), E("s2", "s3"), E("s3", "s4"), E("s4", "f"),
        ])),
    ("hinh-4-4-kiem-soat-dat-hang", "Hình 4.4", "Kiểm soát xác nhận và thực thi đặt hàng an toàn", dict(
        lanes=["Người mua", "AI Chatbot · OrderAgent", "Order Service"], lws=[300, 340, 440],
        nodes=dict(
            i=ini(0, 0),
            a1=act(0, 1, "Yêu cầu đặt hàng"),
            s1=act(1, 2, "Chuẩn bị thông tin giao dịch"),
            o1=act(2, 3, "Tạo Quote có thời hạn", dx=70, w=200),
            s2=act(1, 4, "Hiển thị tóm tắt đơn hàng"),
            d1=dec(0, 5, "Người dùng xác nhận?", tside="l"),
            x1=act(0, 6.2, "Hủy hoặc tiếp tục hội thoại"),
            xf=ff(0, 7.2),
            s3=act(1, 6.2, "Kiểm tra xác thực / quyền"),
            d2=dec(2, 7.2, "Quote còn hiệu lực?", tside="r", dx=70),
            o2=act(2, 8.4, "Atomic Claim một lần", dx=70, w=200),
            d3=dec(2, 9.6, "Claim hợp lệ?", tside="r", dx=70),
            r1=act(2, 9.6, "Từ chối thực thi lại", dx=-124, w=150),
            rf=ff(2, 10.6, dx=-124),
            o3=act(2, 10.8, "Kiểm tra lại giá và tồn kho", dx=70, w=200),
            d4=dec(2, 12, "Thông tin hợp lệ?", tside="r", dx=70),
            n1=act(1, 12, "Yêu cầu lập báo giá mới"),
            nf=ff(1, 13),
            o4=act(2, 13.2, "Checkout với Idempotency Key", dx=70, w=200),
            o5=act(2, 14.2, "Order Service tạo đơn", dx=70, w=200, focal=True),
            s4=act(1, 15.4, "Trả trạng thái đơn hàng"),
            f=fin(1, 16.4)),
        edges=[
            E("i", "a1"), E("a1", "s1", fp="r", tp="t"), E("s1", "o1", fp="r", tp="t"),
            E("o1", "s2", fp="l", tp="t"), E("s2", "d1", fp="l", tp="t"),
            E("d1", "x1", "không", gpos="left"), E("x1", "xf"),
            E("d1", "s3", "có", fp="r", tp="t", gpos="end"),
            E("s3", "d2", fp="r", tp="t"),
            E("d2", "n1", "không", fp="l", tp="t", gpos="end-l"),
            E("d2", "o2", "có", gpos="left"),
            E("o2", "d3"),
            E("d3", "r1", "không", fp="l", tp="r"), E("r1", "rf"),
            E("d3", "o3", "có", gpos="left"),
            E("o3", "d4"),
            E("d4", "n1", "không", fp="l", tp="r"), E("n1", "nf"),
            E("d4", "o4", "có", gpos="left"),
            E("o4", "o5"), E("o5", "s4", fp="l", tp="t", focal=True), E("s4", "f"),
        ])),
]


# ---------------------------------------------------------------- hand-laid pipelines
def box(x, y, w, h, name, sub=None, kind="backend"):
    fill, stroke = {"focal": (ACCENT_TINT, ACCENT), "backend": (WHITE, INK),
                    "store": (STORE_FILL, MUTED), "input": (INPUT_FILL, SOFT)}[kind]
    o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>',
         f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>']
    cx, cy = x + w / 2, y + h / 2
    lines = name.split("\n")
    total = len(lines) + (1 if sub else 0)
    y0 = cy - (total - 1) * 8 + 4
    for i, ln in enumerate(lines):
        o.append(text(cx, y0 + i * 16, ln, 12, INK, "middle", 600))
    if sub:
        o.append(text(cx, y0 + len(lines) * 16, "$" + sub, 9, MUTED, "middle"))
    return "\n".join(o)


def arrow(pts, dash=False, accent=False):
    d, _ = rpath(pts, 8)
    col = ACCENT if accent else MUTED
    mk = "m-fill-accent" if accent else "m-fill"
    ds = ' stroke-dasharray="5,4"' if dash else ""
    return f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.2"{ds} marker-end="url(#{mk})"/>'


def leg_items(extra=()):
    items = [
        (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="32" height="16" rx="4" fill="{ACCENT_TINT}" stroke="{ACCENT}"/>', "Bước trọng tâm"),
        (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="32" height="16" rx="4" fill="{WHITE}" stroke="{INK}"/>', "Bước xử lý"),
        (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="32" height="16" rx="4" fill="{STORE_FILL}" stroke="{MUTED}"/>', "Lưu trữ"),
    ]
    return items + list(extra)


def chunking():
    W = 1264
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    cy = 196
    # arrows first
    for x1, x2 in [(202, 238), (374, 410), (562, 598), (722, 758), (898, 934), (1050, 1086)]:
        o.append(arrow([(x1, cy), (x2, cy)]))
    # Product Record card
    x, y, w, h = 32, 96, 170, 200
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{INPUT_FILL}" stroke="{SOFT}" stroke-width="1.2"/>')
    o.append(text(x + w / 2, y + 26, "Product Record", 12, INK, "middle", 600))
    for i, f in enumerate(["Tên sản phẩm", "Mô tả sản phẩm", "Thuộc tính kỹ thuật", "Thông tin biến thể"]):
        ry = y + 44 + i * 38
        o.append(f'<rect x="{x + 12}" y="{ry}" width="{w - 24}" height="30" rx="4" fill="{WHITE}" stroke="rgba(45,49,66,0.22)"/>')
        o.append(text(x + w / 2, ry + 19.5, f, 11, INK, "middle", 500))
    o.append(box(238, cy - 28, 136, 56, "Chuẩn hóa\ndữ liệu"))
    o.append(box(410, cy - 36, 152, 72, "Chunking theo\ncấu hình hệ thống", "max_chars · overlap", "focal"))
    # chunk group
    gx, gy, gw, gh = 598, 96, 124, 200
    o.append(f'<rect x="{gx}" y="{gy}" width="{gw}" height="{gh}" rx="8" fill="rgba(45,49,66,0.02)" stroke="rgba(45,49,66,0.22)" stroke-dasharray="4,3"/>')
    o.append(label(gx + gw / 2, gy + 14, "$CÁC CHUNK", 8, SOFT))
    for yy, nm in [(124, "Chunk 1"), (172, "Chunk 2"), (248, "Chunk N")]:
        o.append(box(gx + 12, yy, gw - 24, 36, nm))
    o.append(text(gx + gw / 2, 232, "⋮", 16, MUTED, "middle", 600))
    o.append(box(758, cy - 36, 140, 72, "Gắn Product ID\n/ Metadata", "payload"))
    o.append(box(934, cy - 36, 116, 72, "Tạo\nEmbedding", "gemini-embedding"))
    o.append(box(1086, cy - 36, 146, 72, "Vector\nCollection", "Qdrant", "store"))
    leg, lh = legend(leg_items([(lambda x, y: f'<rect x="{x}" y="{y - 8}" width="32" height="16" rx="4" fill="{INPUT_FILL}" stroke="{SOFT}"/>', "Dữ liệu đầu vào")]), 32, 336, W - 64)
    o.append(leg)
    return W, 336 + lh, "\n".join(o)


def conversation():
    W = 1296
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    r1, r2 = 72, 248   # row tops, h=56
    cy1, cy2 = r1 + 28, r2 + 28
    # arrows first
    o.append(arrow([(182, cy1), (232, cy1)]))
    o.append(arrow([(392, cy1), (442, cy1)]))
    o.append(arrow([(642, cy1), (692, cy1)]))
    o.append(arrow([(862, cy1), (912, cy1)]))
    o.append(arrow([(997, r1 + 56), (997, r2)]))
    o.append(arrow([(912, cy2), (392, cy2)], dash=True))
    o.append(label(652, cy2 - 8, "$GHI CHECKPOINT", 8, SOFT))
    o.append(arrow([(312, r2), (312, r1 + 56)], dash=True))
    o.append(label(322, (r1 + 56 + r2) / 2 + 3, "$ĐỌC THEO SESSION", 8, SOFT, "start"))
    o.append(arrow([(1082, cy2), (1132, cy2)]))
    o.append(box(32, r1, 150, 56, "Tin nhắn mới", kind="input"))
    o.append(box(232, r1, 160, 56, "Khôi phục State"))
    o.append(box(442, r1, 200, 56, "Kết hợp ngữ cảnh cũ\nvà thông tin mới"))
    o.append(box(692, r1, 170, 56, "Router / Agent", "LangGraph", "focal"))
    o.append(box(912, r1, 170, 56, "Cập nhật trạng thái"))
    o.append(box(232, r2, 160, 56, "Checkpoint Store", "AsyncSqliteSaver", "store"))
    o.append(box(912, r2, 170, 56, "Lưu Checkpoint"))
    o.append(box(1132, r2, 132, 56, "Phản hồi", kind="input"))
    leg, lh = legend(leg_items([
        (lambda x, y: f'<line x1="{x}" y1="{y}" x2="{x + 30}" y2="{y}" stroke="{MUTED}" stroke-width="1.2" stroke-dasharray="5,4"/>', "Đọc / ghi trạng thái")]), 32, 344, W - 64)
    o.append(leg)
    return W, 344 + lh, "\n".join(o)


HAND = [
    ("hinh-3-4-chunking", "Hình 3.4", "Chunking và tạo dữ liệu vector sản phẩm", chunking),
    ("hinh-3-5-ngu-canh-hoi-thoai", "Hình 3.5", "Quản lý ngữ cảnh hội thoại bằng LangGraph State và Checkpoint", conversation),
]


def write(slug, fig, title, kind, w, h, body):
    html = page(slug, f"{fig} · {kind}", f"{fig}. {title}", f"{fig}: {title}.", w, h, body)
    html = html.replace('<p class="nav"><a href="index.html">← Mục lục</a></p>', "")
    (HERE / f"{slug}.html").write_text(html, encoding="utf-8")
    print(slug)


def main():
    for slug, fig, title, spec in SEQUENCES:
        spec = copy.deepcopy(spec)
        spec["title"] = title
        write(slug, fig, title, "Sequence diagram", *build_sequence(spec))
    for slug, fig, title, spec in ACTIVITIES:
        spec = copy.deepcopy(spec)
        spec["title"] = title
        write(slug, fig, title, "Activity diagram", *build_activity(spec))
    for slug, fig, title, fn in HAND:
        write(slug, fig, title, "Data flow", *fn())


if __name__ == "__main__":
    main()
