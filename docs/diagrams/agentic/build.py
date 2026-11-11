"""Agentic RAG chatbot: tech stack, deployment architecture and LangGraph flow.

    python docs/diagrams/agentic/build.py
    node docs/diagrams/uml/render_png.cjs --dir agentic
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uml"))

from engine import (ACCENT, ACCENT_TINT, INK, LINK, MONO, MUTED, PAPER, RULE, SANS, SERIF, SOFT,  # noqa: E402
                    WHITE, esc, label, legend, page, rpath, text, tw)

STORE_FILL = "rgba(45,49,66,0.05)"
EXT_FILL = "rgba(45,49,66,0.03)"
INPUT_FILL = "rgba(79,93,117,0.10)"


def box(x, y, w, h, name, subs=(), kind="backend", tag=None, name_size=12.5):
    fill, stroke, dash = {
        "focal": (ACCENT_TINT, ACCENT, ""),
        "backend": (WHITE, INK, ""),
        "store": (STORE_FILL, MUTED, ""),
        "external": (EXT_FILL, "rgba(45,49,66,0.45)", ' stroke-dasharray="4,3"'),
        "input": (INPUT_FILL, SOFT, ""),
    }[kind]
    o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>',
         f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.1"{dash}/>']
    n = len(subs)
    block = 16 + 13 * n
    ty = y + h / 2 - block / 2 + 12
    o.append(text(x + w / 2, ty, name, name_size, INK, "middle", 600))
    for i, s in enumerate(subs):
        o.append(text(x + w / 2, ty + 16 + 13 * i, "$" + s, 9, SOFT, "middle"))
    if tag:
        tw_ = tw(tag, 7, True) + 10
        tc = ACCENT if kind == "focal" else MUTED
        o.append(f'<rect x="{x + w - tw_ - 6}" y="{y + 6}" width="{tw_:.1f}" height="12" rx="2" fill="{PAPER}" stroke="{tc}" stroke-width="0.7"/>')
        o.append(text(x + w - tw_ / 2 - 6, y + 15, "$" + tag, 7, tc, "middle", 500, ls="0.08em"))
    return "\n".join(o)


def arrow(pts, color=MUTED, dashed=False, width=1.2, r=8):
    d, _ = rpath(pts, r)
    mk = {MUTED: "m-fill", ACCENT: "m-fill-accent", LINK: "m-fill-link", INK: "m-fill-ink"}[color]
    dash = ' stroke-dasharray="4,3"' if dashed else ""
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash} marker-end="url(#{mk})"/>'


def tag_label(x, y, s, color=MUTED, anchor="middle"):
    return label(x, y, "$" + s, 8, color, anchor, 500, 3)


def zone(x, y, w, h, name):
    lw = tw(name, 7.5, True) + 14
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="rgba(45,49,66,0.02)" stroke="rgba(45,49,66,0.14)" stroke-width="0.8" stroke-dasharray="5,4"/>'
            f'<rect x="{x + 12}" y="{y - 6}" width="{lw:.1f}" height="12" rx="2" fill="{PAPER}"/>'
            + text(x + 12 + lw / 2, y + 3, "$" + name, 7.5, SOFT, "middle", 500, ls="0.14em"))


def legend_items(kinds):
    items = {
        "focal": (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="30" height="16" rx="3" fill="{ACCENT_TINT}" stroke="{ACCENT}"/>', "Thành phần trọng tâm"),
        "backend": (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="30" height="16" rx="3" fill="{WHITE}" stroke="{INK}"/>', "Service / worker"),
        "store": (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="30" height="16" rx="3" fill="{STORE_FILL}" stroke="{MUTED}"/>', "Kho dữ liệu"),
        "external": (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="30" height="16" rx="3" fill="{EXT_FILL}" stroke="rgba(45,49,66,0.45)" stroke-dasharray="4,3"/>', "Dịch vụ bên ngoài"),
        "input": (lambda x, y: f'<rect x="{x}" y="{y - 8}" width="30" height="16" rx="3" fill="{INPUT_FILL}" stroke="{SOFT}"/>', "Client"),
        "http": (lambda x, y: f'<line x1="{x}" y1="{y}" x2="{x + 30}" y2="{y}" stroke="{LINK}" stroke-width="1.2" marker-end="url(#m-fill-link)"/>', "HTTP / API"),
        "call": (lambda x, y: f'<line x1="{x}" y1="{y}" x2="{x + 30}" y2="{y}" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#m-fill)"/>', "Lời gọi nội bộ"),
        "hot": (lambda x, y: f'<line x1="{x}" y1="{y}" x2="{x + 30}" y2="{y}" stroke="{ACCENT}" stroke-width="1.2" marker-end="url(#m-fill-accent)"/>', "Đường truy xuất chính"),
        "dash": (lambda x, y: f'<line x1="{x}" y1="{y}" x2="{x + 30}" y2="{y}" stroke="{MUTED}" stroke-width="1" stroke-dasharray="4,3" marker-end="url(#m-fill)"/>', "Offline / ghi nền"),
        "edge": (lambda x, y: f'<line x1="{x}" y1="{y}" x2="{x + 30}" y2="{y}" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#m-fill)"/>', "Cạnh của graph"),
        "par": (lambda x, y: f'<line x1="{x}" y1="{y}" x2="{x + 30}" y2="{y}" stroke="{LINK}" stroke-width="1.2" stroke-dasharray="4,3" marker-end="url(#m-fill-link)"/>', "Nhánh song song"),
    }
    return [items[k] for k in kinds]


# ===================================================================== 1. STACK
def build_stack():
    W, X0, X1 = 1160, 136, 1120
    LH = 76
    top = 72
    layers = [
        ("L6", "Giao diện người dùng", "ShoppingAssistant (React): chat, gửi ảnh, giọng nói, thẻ sản phẩm, nút xác nhận",
         "react · axios · SSE", False),
        ("L5", "Gateway & API phục vụ", "API Gateway xác thực JWT, gắn x-user-id; FastAPI nhận /assistant/chat và /chat/stream",
         "express · fastapi 0.141 · uvicorn", False),
        ("L4", "Điều phối agent", "LangGraph StateGraph: understand → plan → route → collect → finalize; TurnBudget, checkpoint theo phiên",
         "langgraph 1.2 · checkpoint-sqlite", True),
        ("L3", "Mô hình", "LLM lập kế hoạch và trả lời; embedding văn bản; model server cục bộ cho CLIP và cross-encoder",
         "gemini-3.5-flash-lite · embedding-001", False),
        ("L2", "Truy xuất & công cụ", "Hybrid search dense + BM25 hợp nhất RRF, rerank, tìm bằng ảnh; tool gọi Product, Cart, Order",
         "qdrant-client 1.19 · httpx · mTLS", False),
        ("L1", "Dữ liệu & chỉ mục", "Qdrant: catalog, policies, images; SQLite: checkpoint và cache embedding; agentic-indexer đồng bộ",
         "qdrant · sqlite · agentic-indexer", False),
    ]
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    bottom = top + LH * len(layers)
    o.append(text(48, top - 8, "$TRỪU TƯỢNG", 8, MUTED, "start", 500, ls="0.18em"))
    o.append(f'<line x1="72" y1="{top + 8}" x2="72" y2="{bottom}" stroke="rgba(45,49,66,0.30)" stroke-width="1"/>')
    o.append(f'<polygon points="68,{top + 8} 76,{top + 8} 72,{top}" fill="{MUTED}"/>')
    o.append(text(48, bottom + 18, "$DỮ LIỆU", 8, MUTED, "start", 500, ls="0.18em"))
    fills = [WHITE, PAPER, None, "#ececec", "#ececec", "#e4e4e4"]
    for i, (idx, name, desc, tech, focal) in enumerate(layers):
        y = top + i * LH
        if focal:
            o.append(f'<rect x="{X0}" y="{y}" width="{X1 - X0}" height="{LH}" fill="{ACCENT_TINT}" stroke="{ACCENT}" stroke-width="1"/>')
        else:
            o.append(f'<rect x="{X0}" y="{y}" width="{X1 - X0}" height="{LH}" fill="{fills[i]}"/>')
            o.append(f'<line x1="{X0}" y1="{y + LH}" x2="{X1}" y2="{y + LH}" stroke="{RULE}" stroke-width="1"/>')
        col = ACCENT if focal else MUTED
        o.append(text(X0 + 20, y + 42, "$" + idx, 9, col, "start", 600, ls="0.14em"))
        o.append(text(X0 + 76, y + 32, name, 15, INK, "start", 600))
        o.append(text(X0 + 76, y + 54, desc, 11, MUTED, "start"))
        o.append(text(X1 - 20, y + 32, "$" + tech, 9.5, col, "end", 500))
    o.append(f'<line x1="{X0}" y1="{top}" x2="{X1}" y2="{top}" stroke="{INK}" stroke-width="1"/>')
    o.append(f'<line x1="{X0}" y1="{bottom}" x2="{X1}" y2="{bottom}" stroke="{INK}" stroke-width="1"/>')
    cy = bottom + 48
    o.append(text(X0, cy, "$TẦNG TRỌNG TÂM", 8, MUTED, "start", 500, ls="0.18em"))
    o.append(text(X0 + 112, cy + 1,
                  "LLM chỉ lập kế hoạch và diễn đạt; graph ở L4 quyết định gọi tool nào, giữ ngân sách và bắt xác nhận trước mọi thao tác ghi.",
                  12, MUTED, "start", font=SERIF, italic=True))
    return W, cy + 32, "\n".join(o)


# ===================================================================== 2. ARCHITECTURE
def build_architecture():
    W = 1296
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    # zones
    o.append(zone(24, 64, 680, 640, "ONLINE · MỖI LƯỢT CHAT"))
    o.append(zone(764, 64, 268, 496, "MÔ HÌNH & DỮ LIỆU"))
    o.append(zone(1072, 296, 200, 152, "OFFLINE · ĐÁNH CHỈ MỤC"))
    # geometry
    web = (40, 276, 132, 72)
    gwb = (236, 276, 152, 72)
    rag = (444, 96, 236, 432)
    mid_x, mid_w, mid_h = 788, 220, 72
    llm = (mid_x, 96, mid_w, mid_h)
    msv = (mid_x, 216, mid_w, mid_h)
    qdr = (mid_x, 336, mid_w, mid_h)
    mkt = (mid_x, 456, mid_w, mid_h)
    ckp = (472, 600, 180, 64)
    idx = (1092, 336, 164, 72)

    def cy(b):
        return b[1] + b[3] / 2

    def rx(b):
        return b[0] + b[2]

    # arrows (drawn before boxes)
    o.append(arrow([(rx(web), cy(web)), (gwb[0], cy(gwb))], LINK))
    o.append(tag_label((rx(web) + gwb[0]) / 2, cy(web) - 10, "SSE · JSON", LINK))
    o.append(arrow([(rx(gwb), cy(gwb)), (rag[0], cy(gwb))], LINK))
    o.append(tag_label((rx(gwb) + rag[0]) / 2, cy(gwb) - 10, "X-USER-ID", LINK))
    for b, lab, colr in ((llm, "PLAN · ANSWER", LINK), (msv, "RERANK · CLIP", MUTED),
                         (qdr, "HYBRID + RRF", ACCENT), (mkt, "TOOLS · MTLS", LINK)):
        o.append(arrow([(rx(rag), cy(b)), (b[0], cy(b))], colr))
        o.append(tag_label((rx(rag) + b[0]) / 2, cy(b) - 10, lab, colr))
    cx_r = rag[0] + rag[2] / 2
    o.append(arrow([(cx_r, rag[1] + rag[3]), (cx_r, ckp[1])], MUTED))
    o.append(tag_label(cx_r + 10, (rag[1] + rag[3] + ckp[1]) / 2 + 4, "CHECKPOINT", MUTED, "start"))
    # indexer (offline, dashed)
    ix_cx = idx[0] + idx[2] / 2
    o.append(arrow([(idx[0], cy(idx)), (rx(qdr), cy(qdr))], MUTED, dashed=True, width=1))
    o.append(tag_label((idx[0] + rx(qdr)) / 2, cy(idx) - 10, "UPSERT", MUTED))
    up_x = idx[0] + idx[2] - 24
    o.append(arrow([(up_x, idx[1]), (up_x, cy(llm)), (rx(llm), cy(llm))], MUTED, dashed=True, width=1))
    o.append(tag_label(up_x - 10, (idx[1] + cy(llm)) / 2 + 30, "EMBED BATCH", MUTED, "end"))
    o.append(arrow([(ix_cx, idx[1] + idx[3]), (ix_cx, cy(mkt)), (rx(mkt), cy(mkt))], MUTED, dashed=True, width=1))
    o.append(tag_label(ix_cx + 10, (idx[1] + idx[3] + cy(mkt)) / 2 + 4, "CATALOG", MUTED, "start"))

    # boxes
    o.append(box(*web, "Web App", ["ShoppingAssistant"], "input"))
    o.append(box(*gwb, "API Gateway", ["express · JWT"], "backend"))
    # focal RAG panel with internals
    x, y, w, h = rag
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>')
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{ACCENT_TINT}" stroke="{ACCENT}" stroke-width="1.3"/>')
    o.append(text(x + w / 2, y + 30, "Agentic RAG API", 14, INK, "middle", 600))
    o.append(text(x + w / 2, y + 47, "$fastapi · langgraph · :3030", 9, ACCENT, "middle", 500))
    rows = [
        ("understand", "hiểu lượt nói (LLM / fast-path)"),
        ("resolve_context", "sản phẩm đang focus, variant"),
        ("plan", "kế hoạch có schema"),
        ("route", "retrieve ⇄ relax · tools · policy"),
        ("clarify_guard", "hỏi lại → handoff"),
        ("pendingAction", "chờ confirmActionId"),
        ("collect → finalize", "template | LLM"),
    ]
    ry = y + 72
    for i, (k, v) in enumerate(rows):
        yy = ry + i * 44
        o.append(f'<line x1="{x + 16}" y1="{yy - 14}" x2="{x + w - 16}" y2="{yy - 14}" stroke="rgba(191,69,32,0.22)" stroke-width="0.8"/>')
        o.append(text(x + 20, yy + 4, "$" + k, 10, INK, "start", 600))
        o.append(text(x + 20, yy + 20, v, 10.5, MUTED, "start"))
    o.append(text(x + w / 2, y + h - 14, "$TurnBudget ≤ 4 LLM · 8 s", 9, ACCENT, "middle", 600))
    o.append(box(*llm, "LLM Provider", ["gemini-3.5-flash-lite", "gemini-embedding-001"], "external"))
    o.append(box(*msv, "Model server", ["image-embedding:3022", "CLIP ViT-B/32 · mMiniLM"], "backend"))
    o.append(box(*qdr, "Qdrant", ["catalog_* (dense + bm25)", "policies_* · images_*"], "store"))
    o.append(box(*mkt, "Marketplace services", ["product · inventory · cart", "order · voucher · review · user"], "backend"))
    o.append(box(*ckp, "Checkpointer", ["agentic_checkpoints.sqlite"], "store"))
    o.append(box(*idx, "agentic-indexer", ["plan · run", "SQLite embed cache"], "backend"))
    leg, lh = legend(legend_items(["focal", "backend", "store", "external", "input", "http", "call", "hot", "dash"]), 32, 728, W - 64)
    o.append(leg)
    return W, 728 + lh + 8, "\n".join(o)


# ===================================================================== 3. LANGGRAPH FLOW
def build_graph():
    W = 1280
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    R1y, R1h = 72, 56
    und = (88, R1y, 164, R1h)
    rcx = (292, R1y, 176, R1h)
    pln = (520, R1y, 240, R1h)
    by, bh, bw = 268, 68, 168
    names = ["retrieve", "tools", "txn", "policy", "clarify", "pside"]
    bx = {n: 76 + i * (bw + 24) for i, n in enumerate(names)}
    bcx = {n: bx[n] + bw / 2 for n in names}
    rlx = (72, 384, 112, 48)
    col = (540, 488, 200, 56)
    fin = (880, 488, 180, 56)

    def cyy(b):
        return b[1] + b[3] / 2

    # START / row 1 edges
    o.append(f'<circle cx="48" cy="{cyy(und)}" r="9" fill="{INK}"/>')
    o.append(arrow([(57, cyy(und)), (und[0], cyy(und))]))
    o.append(arrow([(und[0] + und[2], cyy(und)), (rcx[0], cyy(und))]))
    o.append(arrow([(rcx[0] + rcx[2], cyy(und)), (pln[0], cyy(und))]))
    # plan fan-out (route_after_plan); outermost branch turns first
    ports = [pln[0] + pln[2] * (k + 1) / 7 for k in range(6)]
    turn = {"retrieve": 152, "tools": 164, "txn": 176, "policy": 176, "clarify": 164, "pside": 152}
    pb = pln[1] + pln[3]
    for k, n in enumerate(names):
        colr = ACCENT if n == "retrieve" else (LINK if n == "pside" else MUTED)
        o.append(arrow([(ports[k], pb), (ports[k], turn[n]), (bcx[n], turn[n]), (bcx[n], by)], colr,
                       dashed=(n == "pside")))
    o.append(tag_label(bcx["pside"] + 10, 214, "SONG SONG", LINK, "start"))
    o.append(tag_label(ports[0] - 132, 144, "ROUTE_AFTER_PLAN", MUTED, "start"))
    # relax loop
    r_bot = by + bh
    o.append(arrow([(rlx[0] + 44, r_bot), (rlx[0] + 44, rlx[1])], MUTED))
    o.append(arrow([(rlx[0] + 68, rlx[1]), (rlx[0] + 68, r_bot)], MUTED))
    o.append(tag_label(bx["retrieve"] + 152, 368, "0 KQ · ≤ 2 VÒNG", MUTED, "start"))
    # converge to collect; outermost branch turns lowest
    cports = [col[0] + col[2] * (k + 1) / 6 for k in range(5)]
    cturn = {"retrieve": 456, "tools": 444, "txn": 432, "policy": 432, "clarify": 444}
    for k, n in enumerate(names[:5]):
        sx = bx[n] + 140 if n == "retrieve" else bcx[n]
        colr = ACCENT if n == "retrieve" else MUTED
        o.append(arrow([(sx, r_bot), (sx, cturn[n]), (cports[k], cturn[n]), (cports[k], col[1])], colr))
    # collect -> finalize, policy_side -> finalize
    o.append(arrow([(col[0] + col[2], cyy(col)), (fin[0], cyy(col))]))
    o.append(arrow([(bcx["pside"], r_bot), (bcx["pside"], cyy(fin)), (fin[0] + fin[2], cyy(fin))], LINK, dashed=True))
    o.append(tag_label((col[0] + col[2] + fin[0]) / 2, cyy(col) - 10, "BARRIER", MUTED))
    # END
    ex, ey = fin[0] + fin[2] / 2, 612
    o.append(arrow([(ex, fin[1] + fin[3]), (ex, ey - 13)]))
    o.append(f'<circle cx="{ex}" cy="{ey}" r="11" fill="{PAPER}" stroke="{INK}" stroke-width="1.4"/><circle cx="{ex}" cy="{ey}" r="6.5" fill="{INK}"/>')
    o.append(text(ex + 20, ey + 4, "$END", 8, MUTED, "start", 500, ls="0.14em"))
    o.append(text(40, cyy(und) + 26, "$START", 8, MUTED, "start", 500, ls="0.14em"))

    # nodes
    o.append(box(*und, "understand", ["dialogue_act · slots"], tag="LLM"))
    o.append(box(*rcx, "resolve_context", ["focus · variant"], tag="STATE"))
    o.append(box(*pln, "plan", ["planner có schema"], "focal", tag="LLM"))
    o.append(box(bx["retrieve"], by, bw, bh, "retrieve", ["hybrid search", "rerank · ảnh"], "focal", tag="QDRANT"))
    o.append(box(bx["tools"], by, bw, bh, "Tools tra cứu", ["product_detail · cart_view", "order_status · browse"], tag="HTTP"))
    o.append(box(bx["txn"], by, bw, bh, "Giao dịch", ["prepare_cart · checkout", "resolve_pending"], tag="CONFIRM"))
    o.append(box(bx["policy"], by, bw, bh, "policy", ["RAG chính sách"], tag="RAG"))
    o.append(box(bx["clarify"], by, bw, bh, "clarify / general", ["hỏi lại · handoff"], tag="GUARD"))
    o.append(box(bx["pside"], by, bw, bh, "policy_side", ["task chính sách phụ"], tag="RAG"))
    o.append(box(*rlx, "relax", ["nới ràng buộc"], tag="RULES", name_size=11.5))
    o.append(box(*col, "collect", ["gom kết quả"], tag="JOIN"))
    o.append(box(*fin, "finalize", ["template | LLM"], tag="ANSWER"))
    # editorial callout
    o.append(text(800, 92, "Mỗi lượt có TurnBudget: tối đa 4 lần gọi LLM và hạn 8 giây.", 12.5, MUTED, "start",
                  font=SERIF, italic=True))
    o.append(text(800, 110, "Hết budget, node chuyển sang đường tất định thay vì lỗi.", 12.5, MUTED, "start",
                  font=SERIF, italic=True))
    leg, lh = legend(legend_items(["focal", "backend", "edge", "hot", "par"]), 32, 660, W - 64)
    o.append(leg)
    return W, 660 + lh + 8, "\n".join(o)


DIAGRAMS = [
    ("agentic-rag-stack", "Layer stack · Agentic RAG chatbot", "Stack công nghệ của chatbot Agentic RAG",
     "Sáu tầng từ giao diện chat tới dữ liệu chỉ mục, tầng điều phối LangGraph là trọng tâm.", build_stack,
     "Phiên bản thư viện lấy từ agentic rag/requirements.txt; tên model lấy từ app/config.py (có thể đổi qua biến môi trường)."),
    ("agentic-rag-architecture", "Architecture · Agentic RAG chatbot", "Kiến trúc triển khai Agentic RAG",
     "Luồng online từ Web App qua API Gateway tới Agentic RAG API, các phụ thuộc mô hình và dữ liệu, cùng worker agentic-indexer chạy offline.",
     build_architecture,
     "Collection policies_* do chatbot-policy-indexer (chatbot-service) duy trì; agentic RAG chỉ đọc. Mọi lời gọi tới marketplace services dùng mTLS trong mạng Docker."),
    ("agentic-rag-langgraph", "Flow · LangGraph StateGraph", "Luồng xử lý một lượt chat trong LangGraph",
     "Các node của StateGraph: understand, resolve_context, plan, sáu nhánh định tuyến, vòng relax, collect và finalize.",
     build_graph,
     "Nhóm 'Tools tra cứu' gồm product_detail, cart_view, order_status, browse_categories; 'Giao dịch' gồm prepare_cart, prepare_checkout, resolve_pending (chỉ ghi khi client gửi đúng confirmActionId). policy_side chạy cùng superstep với nhánh chính; finalize chờ cả collect và policy_side."),
]


def main():
    for slug, eyebrow, h1, desc, fn, note in DIAGRAMS:
        w, h, body = fn()
        html = page(slug, eyebrow, h1, desc, w, h, body, note)
        html = html.replace('<p class="nav"><a href="index.html">← Mục lục</a></p>', "")
        (HERE / f"{slug}.html").write_text(html, encoding="utf-8")
        print(slug)


if __name__ == "__main__":
    main()
