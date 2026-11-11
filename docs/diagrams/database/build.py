"""ERD of the whole system + one physical schema page per database.

    python docs/diagrams/database/build.py
    node docs/diagrams/uml/render_png.cjs --dir database
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uml"))
sys.path.insert(0, str(HERE))

from engine import (ACCENT, ACCENT_TINT, FONT_LINK, INK, LINK, MONO, MUTED, PAPER, RULE, SANS, SERIF, SOFT,  # noqa: E402
                    WHITE, esc, label, legend, page, rpath, text, tw)
from schema import DATABASES  # noqa: E402

ZONE_FILL = "rgba(45,49,66,0.02)"
ZONE_STROKE = "rgba(45,49,66,0.22)"
MONGO_TINT = "rgba(79,93,117,0.10)"
PG_TINT = "rgba(46,90,168,0.08)"


def chip(x, y, s, color=MUTED, dashed=False):
    w = tw(s, 7.5, True) + 8
    dash = ' stroke-dasharray="2,2"' if dashed else ""
    return (f'<rect x="{x:.1f}" y="{y - 8}" width="{w:.1f}" height="11" rx="2" fill="{PAPER}" stroke="{color}" stroke-width="0.7"{dash}/>'
            + text(x + w / 2, y + 0.5, "$" + s, 7.5, color, "middle", 600, ls="0.04em")), w


def edge_path(pts, solid=True, color=INK):
    d, _ = rpath(pts, 6)
    dash = "" if solid else ' stroke-dasharray="5,4"'
    mk = "m-fill-ink" if color == INK else "m-fill"
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{1.2 if solid else 1}"{dash} marker-end="url(#{mk})"/>'


# ===================================================================== PHYSICAL SCHEMA
TW_, HDR, ROW, EMB_H = 384, 32, 22, 22


def table_rows(t):
    """Flatten columns: list of (kind, payload)."""
    rows = []
    for c in t["cols"]:
        if c[0] == "embed":
            rows.append(("emb", c[1]))
            for sub in c[2]:
                rows.append(("sub", sub))
        else:
            rows.append(("col", c))
    return rows


def table_height(t):
    h = HDR + ROW * len(table_rows(t)) + 6
    if t.get("idx"):
        h += 22 + 15 * len(t["idx"])
    return h


def render_table(x, y, name, t, engine):
    rows = table_rows(t)
    h = table_height(t)
    tint = MONGO_TINT if engine == "MongoDB" else PG_TINT
    o = [f'<rect x="{x}" y="{y}" width="{TW_}" height="{h}" rx="6" fill="{WHITE}" stroke="{INK}" stroke-width="1.1"/>',
         f'<path d="M{x},{y + HDR} V{y + 6} Q{x},{y} {x + 6},{y} H{x + TW_ - 6} Q{x + TW_},{y} {x + TW_},{y + 6} V{y + HDR} Z" fill="{tint}"/>',
         f'<line x1="{x}" y1="{y + HDR}" x2="{x + TW_}" y2="{y + HDR}" stroke="{INK}" stroke-width="0.8"/>']
    tag = "COLLECTION" if engine == "MongoDB" else "TABLE"
    c_svg, cw = chip(x + 10, y + 20, tag, MUTED)
    o.append(c_svg)
    o.append(text(x + 18 + cw, y + 21, name, 12.5, INK, "start", 600))
    anchors = {}
    yy = y + HDR
    for i, (kind, p) in enumerate(rows):
        cy = yy + ROW / 2
        if i % 2 == 1:
            o.append(f'<rect x="{x + 1}" y="{yy}" width="{TW_ - 2}" height="{ROW}" fill="rgba(45,49,66,0.025)"/>')
        if kind == "emb":
            o.append(f'<line x1="{x + 10}" y1="{yy + 2}" x2="{x + TW_ - 10}" y2="{yy + 2}" stroke="{RULE}" stroke-width="0.8"/>')
            o.append(text(x + 12, cy + 4, "$" + p, 9.5, MUTED, "start", 600))
            o.append(text(x + TW_ - 12, cy + 4, "$embedded", 8, SOFT, "end", 500, ls="0.08em"))
        else:
            cname, ctype, flags, ref = p
            indent = 26 if kind == "sub" else 12
            if kind == "sub":
                o.append(text(x + 14, cy + 4, "$↳", 9, SOFT, "start"))
            weight = 600 if "PK" in flags.split() else 400
            o.append(text(x + indent, cy + 4, cname, 11.5, INK, "start", weight))
            o.append(text(x + TW_ - 12, cy + 4, "$" + ctype, 9, MUTED, "end"))
            # chips right-to-left before the type
            cx = x + TW_ - 18 - tw(ctype, 9, True)
            chips = [f for f in ["PK", "FK", "UQ", "NN", "IDX"] if f in flags.split()]
            if ref and "FK" not in chips:
                chips.append("REF")
            for f in reversed(chips):
                col = {"PK": INK, "FK": INK, "UQ": LINK, "REF": SOFT}.get(f, MUTED)
                w = tw(f, 7.5, True) + 8
                cx -= w + 4
                s, _ = chip(cx, cy + 4, f, col, dashed=(f == "REF"))
                o.append(s)
            anchors[cname] = cy
        yy += ROW
    if t.get("idx"):
        yy += 6
        o.append(f'<line x1="{x + 10}" y1="{yy}" x2="{x + TW_ - 10}" y2="{yy}" stroke="{RULE}" stroke-width="0.8"/>')
        o.append(text(x + 12, yy + 15, "$INDEXES", 7.5, SOFT, "start", 600, ls="0.16em"))
        for j, ix in enumerate(t["idx"]):
            o.append(text(x + 80, yy + 15 + 15 * j, "$" + ix, 9, MUTED, "start"))
    return "\n".join(o), anchors, h


def build_db(db, compact=False):
    cols = db["layout"]
    gap = 168
    x0 = 96
    xs = [x0 + i * (TW_ + gap) for i in range(len(cols))]
    pos, anchors = {}, {}
    top = 20 if compact else 64
    body = []
    max_y = 0
    for ci, col in enumerate(cols):
        y = top
        for name in col:
            t = db["tables"][name]
            s, a, h = render_table(xs[ci], y, name, t, db["engine"])
            body.append(s)
            pos[name] = (ci, xs[ci], y, h)
            anchors[name] = a
            y += h + 40
        max_y = max(max_y, y - 40)
    # edges inside this database
    edges, external = [], []
    for tname, t in db["tables"].items():
        for c in t["cols"]:
            items = c[2] if c[0] == "embed" else [c]
            for (cname, _, flags, ref) in items:
                if not ref:
                    continue
                if ref.startswith("@"):
                    external.append((tname, cname, ref[1:]))
                else:
                    rt, rc = ref.split(".")
                    edges.append((tname, cname, rt, rc, "FK" in flags.split()))
    # attach-point fan per (table, column, side)
    attach = {}

    def key_side(e):
        s, sc, t, tc, _ = e
        cs, ct = pos[s][0], pos[t][0]
        if cs == ct:
            return (s, sc, "l"), (t, tc, "l")
        return ((s, sc, "l" if cs > ct else "r"), (t, tc, "r" if cs > ct else "l"))

    for e in edges:
        for k in key_side(e):
            attach.setdefault(k, []).append(e)
    channels = {}
    for e in edges:
        s, sc, t, tc, _ = e
        cs, ct = pos[s][0], pos[t][0]
        ch = ("same", cs) if cs == ct else ("gap", min(cs, ct))
        channels.setdefault(ch, []).append(e)

    def span(e):  # signed vertical distance target - source (negative: source below)
        s, sc, t, tc, _ = e
        return anchors[t][tc] - anchors[s][sc]

    # Ordering that keeps nested connectors from crossing:
    #  same-column loops: short edge hugs the table and lands lower; long edge goes outside and lands on top.
    #  edges across a gap: long edge runs nearest the target and lands lower; short edge lands on top.
    for k, lst in attach.items():
        same = all(pos[e[0]][0] == pos[e[2]][0] for e in lst)
        lst.sort(key=span if same else (lambda e: -span(e)))
    for ch, lst in channels.items():
        lst.sort(key=lambda e: abs(span(e)), reverse=(ch[0] == "gap"))
    ed_svg = []
    for e in edges:
        s, sc, t, tc, enforced = e
        ks, kt = key_side(e)

        def ay(k, ee):
            lst = attach[k]
            n = len(lst)
            off = (lst.index(ee) - (n - 1) / 2) * 12 if n > 1 else 0
            return anchors[k[0]][k[1]] + max(-8, min(8, off))

        sy, ty = ay(ks, e), ay(kt, e)
        sx = pos[s][1] + (0 if ks[2] == "l" else TW_)
        tx = pos[t][1] + (0 if kt[2] == "l" else TW_)
        cs, ct = pos[s][0], pos[t][0]
        if cs == ct:
            lst = channels[("same", cs)]
            cxx = pos[s][1] - 24 - 14 * lst.index(e)
        else:
            lst = channels[("gap", min(cs, ct))]
            mid = xs[min(cs, ct)] + TW_ + gap / 2
            step = (lst.index(e) - (len(lst) - 1) / 2) * 16
            cxx = mid + step if ct < cs else mid - step  # index 0 sits nearest the target
        ed_svg.append(edge_path([(sx, sy), (cxx, sy), (cxx, ty), (tx + (2 if kt[2] == "r" else -2), ty)],
                                enforced, INK if enforced else MUTED))
        if (s, sc) in db.get("cascade", set()):
            if cs == ct:
                ed_svg.append(label(cxx - 6, (sy + ty) / 2 + 3, "$CASCADE", 7.5, INK, "end", 600, 3))
            else:
                ed_svg.append(label(cxx + 6, (sy + ty) / 2 + 3, "$CASCADE", 7.5, INK, "start", 600, 3))
    if compact:
        return xs[-1] + TW_ + 28, max_y + 24, "\n".join(ed_svg + body), external
    width = xs[-1] + TW_ + 64
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    o.append(text(40, 36, f"${db['engine']} · {db['db']}", 9, SOFT, "start", 600, ls="0.14em"))
    o += ed_svg + body
    y = max_y + 40
    if external:
        o.append(f'<line x1="40" y1="{y}" x2="{width - 40}" y2="{y}" stroke="{RULE}" stroke-width="1"/>')
        o.append(text(40, y + 22, "$THAM CHIẾU LOGIC SANG SERVICE KHÁC (không có khóa ngoại)", 8, SOFT, "start", 600, ls="0.14em"))
        ncol = 2 if width > 1000 else 1
        per = (len(external) + ncol - 1) // ncol
        colw = (width - 80) / ncol
        for i, (tn, cn, ref) in enumerate(external):
            cx_, cy_ = 40 + (i // per) * colw, y + 44 + (i % per) * 17
            o.append(text(cx_, cy_, f"${tn}.{cn}  →  {ref}", 9.5, MUTED, "start"))
        y += 44 + per * 17
    items = [
        (lambda lx, ly: chip(lx, ly + 4, "PK", INK)[0], "Khóa chính"),
        (lambda lx, ly: chip(lx, ly + 4, "FK", INK)[0], "Khóa ngoại (ràng buộc thật)"),
        (lambda lx, ly: chip(lx, ly + 4, "REF", SOFT, True)[0], "Tham chiếu logic qua ID"),
        (lambda lx, ly: chip(lx, ly + 4, "UQ", LINK)[0], "Duy nhất"),
        (lambda lx, ly: chip(lx, ly + 4, "NN", MUTED)[0], "Not null"),
    ]
    if edges:
        items += [(lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 30}" y2="{ly}" stroke="{INK}" stroke-width="1.2" marker-end="url(#m-fill-ink)"/>', "FK → cột được tham chiếu"),
                  (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 30}" y2="{ly}" stroke="{MUTED}" stroke-width="1" stroke-dasharray="5,4" marker-end="url(#m-fill)"/>', "Liên kết logic trong cùng DB")]
    leg, lh = legend(items, 32, y + 16, width - 64)
    o.append(leg)
    return width, y + 16 + lh + 8, "\n".join(o)


# ===================================================================== ALL DATABASES IN ONE IMAGE
# Shelf layout: each row lists database slugs left to right.
ALL_ROWS = [
    ["wallet-service", "order-service", "payment-gateway"],
    ["product-service", "voucher-service", "inventory-service", "payment-service"],
    ["user-service", "shop-service", "cart-service", "auth-service", "review-service", "chat-service"],
]


def build_all():
    by_slug = {d["slug"]: d for d in DATABASES}
    parts = {k: build_db(v, compact=True) for k, v in by_slug.items()}
    HEAD, ZG, M = 40, 40, 40
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    zones, y, width = [], M + 8, 0
    for row in ALL_ROWS:
        x = M
        rh = max(parts[s][1] for s in row) + HEAD
        for slug in row:
            w, h, body, _ = parts[slug]
            zones.append((slug, x, y, w, rh, body))
            x += w + ZG
        width = max(width, x - ZG + M)
        y += rh + ZG
    total_tables = 0
    for slug, x, zy, w, h, body in zones:
        db = by_slug[slug]
        total_tables += len(db["tables"])
        tint = MONGO_TINT if db["engine"] == "MongoDB" else PG_TINT
        o.append(f'<rect x="{x}" y="{zy}" width="{w}" height="{h}" rx="10" fill="{ZONE_FILL}" stroke="{ZONE_STROKE}" stroke-width="1" stroke-dasharray="6,4"/>')
        o.append(f'<path d="M{x},{zy + HEAD - 6} V{zy + 10} Q{x},{zy} {x + 10},{zy} H{x + w - 10} Q{x + w},{zy} {x + w},{zy + 10} V{zy + HEAD - 6} Z" fill="{tint}"/>')
        o.append(text(x + 20, zy + 23, db["slug"], 15, INK, "start", 600))
        o.append(text(x + 36 + tw(db["slug"], 15) * 1.15, zy + 23, db["title"], 12, MUTED, "start"))
        o.append(text(x + w - 20, zy + 23, f"${db['engine']} · {db['db']}", 10, SOFT, "end", 600, ls="0.1em"))
        o.append(f'<g transform="translate({x - 52},{zy + HEAD - 8})">{body}</g>')
    items = [
        (lambda lx, ly: f'<rect x="{lx}" y="{ly - 8}" width="30" height="16" rx="3" fill="{MONGO_TINT}" stroke="{INK}" stroke-width="0.8"/>', "Collection MongoDB"),
        (lambda lx, ly: f'<rect x="{lx}" y="{ly - 8}" width="30" height="16" rx="3" fill="{PG_TINT}" stroke="{INK}" stroke-width="0.8"/>', "Bảng PostgreSQL"),
        (lambda lx, ly: chip(lx, ly + 4, "PK", INK)[0], "Khóa chính"),
        (lambda lx, ly: chip(lx, ly + 4, "FK", INK)[0], "Khóa ngoại (ràng buộc thật)"),
        (lambda lx, ly: chip(lx, ly + 4, "REF", SOFT, True)[0], "Tham chiếu logic qua ID (trong DB hoặc sang service khác)"),
        (lambda lx, ly: chip(lx, ly + 4, "UQ", LINK)[0], "Duy nhất"),
        (lambda lx, ly: chip(lx, ly + 4, "NN", MUTED)[0], "Not null"),
        (lambda lx, ly: chip(lx, ly + 4, "IDX", MUTED)[0], "Có chỉ mục"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 30}" y2="{ly}" stroke="{INK}" stroke-width="1.2" marker-end="url(#m-fill-ink)"/>', "FK → cột được tham chiếu"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 30}" y2="{ly}" stroke="{MUTED}" stroke-width="1" stroke-dasharray="5,4" marker-end="url(#m-fill)"/>', "Liên kết logic trong cùng DB"),
    ]
    leg, lh = legend(items, M, y, width - 2 * M)
    o.append(leg)
    return width, y + lh + 8, "\n".join(o), total_tables


# ===================================================================== LOGICAL ERD
EW = 212
E = lambda name, fields, kind="entity": dict(name=name, fields=fields, kind=kind)  # noqa: E731

ZONES = {
    "auth": dict(label="auth-service · MongoDB", grid=[[E("User", ["# _id", "email (UQ)", "role", "isActive · tokenVersion", "↗ shopId (Shop)"], "root")]]),
    "user": dict(label="user-service · MongoDB", grid=[[E("UserProfile", ["# _id", "↗ userId (User, UQ)", "name · phone"]),
                                                      E("Address", ["fullName · phone", "line1 · city", "isDefault"], "embed")]]),
    "shop": dict(label="shop-service · MongoDB", grid=[[E("Shop", ["# _id", "↗ ownerId (User)", "name", "invoiceRequestMode", "invoiceFeatureStatus"], "root"),
                                                      E("InvoiceFeatureRequest", ["requestedMode", "status", "reviewedBy"], "embed")]]),
    "chat": dict(label="chat-service · MongoDB", grid=[[E("Conversation", ["# _id", "↗ shopId (Shop)", "↗ buyerId (User)", "lastMessage"]),
                                                      E("Message", ["# _id", "→ conversationId", "senderRole · text"])]]),
    "review": dict(label="review-service · MongoDB", grid=[[E("Review", ["# _id", "↗ productId (Product)", "↗ userId (User)", "rating · comment"])]]),
    "product": dict(label="product-service · MongoDB", grid=[
        [E("Category", ["# _id", "name", "↗ shopId (Shop)"]),
         E("Product", ["# _id", "→ categoryId", "↗ shopId (Shop)", "name · price · sold", "moderationStatus"], "root"),
         E("Variant", ["# _id", "name · sku", "price · quantity"], "embed")],
        [E("ProductSalesEvent", ["# _id", "↗ orderId (Order, UQ)", "status", "totalQuantity"]), None, None]]),
    "cart": dict(label="cart-service · MongoDB", grid=[[E("Cart", ["# _id", "↗ userId (User, UQ)"]),
                                                      E("CartItem", ["↗ productId (Product)", "variantId", "quantity"], "embed")]]),
    "inventory": dict(label="inventory-service · PostgreSQL", grid=[[E("Inventory", ["# id", "↗ product_id + variant_id", "↗ shop_id (Shop)", "stock_on_hand", "reserved_stock"]),
                                                                   E("InventoryReservation", ["# id", "↗ order_id (Order)", "product_id + variant_id", "quantity · status"])]]),
    "order": dict(label="order-service · PostgreSQL", grid=[
        [E("CheckoutQuote", ["# id (uuid)", "↗ user_id (User)", "payment_method", "total_price · status", "order_ids[]"]),
         E("Order", ["# id", "↗ user_id (User)", "products (jsonb)", "total_price · status", "voucher_code", "settlement_status"], "root"),
         E("Shipment", ["# id", "→ order_id", "↗ shop_id (Shop)", "tracking_code (UQ)", "status"])],
        [None, E("Dispute", ["# id", "→ order_id", "↗ user_id (User)", "reason · status"]), None]]),
    "voucher": dict(label="voucher-service · PostgreSQL", grid=[[E("Voucher", ["# id", "code (UQ)", "↗ shop_id (Shop)", "discount_type · value", "quantity · used_count"]),
                                                               E("VoucherReservation", ["# id", "→ voucher_id", "↗ order_id (Order)", "↗ user_id (User)", "status"])]]),
    "gateway": dict(label="payment-gateway · PostgreSQL", grid=[[E("SepayPaymentRequest", ["# id", "request_code (UQ)", "↗ user_id (User)", "↗ order_id (Order)", "amount · status"]),
                                                               E("SepayWebhookLog", ["# id", "sepay_transaction_id (UQ)", "→ request_code", "transfer_amount"])]]),
    "wallet": dict(label="wallet-service · PostgreSQL", grid=[
        [E("Wallet", ["# id", "↗ user_id (User)", "currency · status"]),
         E("WalletBalance", ["# → wallet_id", "available · locked"]), None],
        [E("WalletLedgerEntry", ["# id", "→ wallet_id", "↗ order_id (Order)", "type · amount"]),
         E("UserWithdrawalRequest", ["# id", "↗ user_id (User)", "→ account_id", "amount · status"]),
         E("SettlementJob", ["# id", "↗ order_id (Order)", "↗ shop_id (Shop)", "amount · status"])],
        [E("AccountBalance", ["# → account_id", "available · locked"]),
         E("Account", ["# id", "owner_type · owner_id", "account_type"], "root"),
         E("PayoutRequest", ["# id", "↗ shop_id (Shop)", "→ account_id", "amount · status"])],
        [E("LedgerTransaction", ["# id", "reference_id (UQ)", "type · amount", "status"]),
         E("LedgerEntry", ["# id", "→ transaction_id", "→ account_id", "direction · amount"]), None]]),
}

# (zone, entityA, entityB, card at A, card at B, label)
RELS = [
    ("user", "UserProfile", "Address", "1", "0..N", "nhúng"),
    ("shop", "Shop", "InvoiceFeatureRequest", "1", "0..N", "nhúng"),
    ("chat", "Conversation", "Message", "1", "0..N", None),
    ("product", "Category", "Product", "0..1", "0..N", None),
    ("product", "Product", "Variant", "1", "0..N", "nhúng"),
    ("cart", "Cart", "CartItem", "1", "0..N", "nhúng"),
    ("inventory", "Inventory", "InventoryReservation", "1", "0..N", None),
    ("order", "CheckoutQuote", "Order", "1", "1..N", None),
    ("order", "Order", "Shipment", "1", "0..N", None),
    ("order", "Order", "Dispute", "1", "0..N", None),
    ("voucher", "Voucher", "VoucherReservation", "1", "0..N", None),
    ("gateway", "SepayPaymentRequest", "SepayWebhookLog", "1", "0..N", None),
    ("wallet", "Wallet", "WalletBalance", "1", "1", None),
    ("wallet", "Wallet", "WalletLedgerEntry", "1", "0..N", None),
    ("wallet", "Account", "AccountBalance", "1", "1", None),
    ("wallet", "Account", "UserWithdrawalRequest", "1", "0..N", None),
    ("wallet", "Account", "PayoutRequest", "1", "0..N", None),
    ("wallet", "Account", "LedgerEntry", "1", "0..N", None),
    ("wallet", "LedgerTransaction", "LedgerEntry", "1", "2..N", None),
]

HG, VG, ZP, ZH = 88, 40, 20, 30


def ent_h(e):
    return 30 + 8 + 15 * len(e["fields"]) + 6


def zone_size(z):
    g = z["grid"]
    ncol = max(len(r) for r in g)
    rh = [max(ent_h(e) for e in r if e) for r in g]
    w = ncol * EW + (ncol - 1) * HG + 2 * ZP
    h = ZH + sum(rh) + (len(g) - 1) * VG + ZP
    return w, h, rh


def render_entity(x, y, e):
    h = ent_h(e)
    kind = e["kind"]
    stroke = ACCENT if kind == "root" else INK
    fill = ACCENT_TINT if kind == "root" else WHITE
    dash = ' stroke-dasharray="5,3"' if kind == "embed" else ""
    o = [f'<rect x="{x}" y="{y}" width="{EW}" height="{h}" rx="6" fill="{PAPER}"/>',
         f'<rect x="{x}" y="{y}" width="{EW}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.1"{dash}/>',
         f'<line x1="{x}" y1="{y + 30}" x2="{x + EW}" y2="{y + 30}" stroke="{stroke}" stroke-width="0.7"/>']
    o.append(text(x + 12, y + 20, e["name"], 12, INK, "start", 600))
    tag = "EMBED" if kind == "embed" else "ENTITY"
    s, cw = chip(x + EW - tw(tag, 7.5, True) - 18, y + 19, tag, ACCENT if kind == "root" else MUTED)
    o.append(s)
    for i, f in enumerate(e["fields"]):
        col = INK if f.startswith("#") else (LINK if f.startswith("↗") else MUTED)
        o.append(text(x + 12, y + 30 + 18 + 15 * i, "$" + f, 9.5, col, "start", 600 if f.startswith("#") else 400))
    return "\n".join(o)


def build_erd():
    rows = [["auth", "user", "shop", "chat", "review"],
            ["product", "cart", "inventory"],
            ["order", "voucher", "gateway"]]
    right = "wallet"
    sizes = {k: zone_size(z) for k, z in ZONES.items()}
    zpos = {}
    y = 64
    row_right = 0
    row_tops = []
    for r in rows:
        x = 40
        row_tops.append(y)
        for k in r:
            zpos[k] = (x, y)
            x += sizes[k][0] + 32
        row_right = max(row_right, x)
        y += max(sizes[k][1] for k in r) + 40
    # wallet to the right of rows 2-3
    wx = max(zpos["inventory"][0] + sizes["inventory"][0], zpos["gateway"][0] + sizes["gateway"][0]) + 32
    zpos[right] = (wx, row_tops[1])
    width = max(row_right - 32, wx + sizes[right][0]) + 40
    bottom = max(y - 40, row_tops[1] + sizes[right][1])
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>']
    boxes = {}
    ents = []
    for k, z in ZONES.items():
        zx, zy = zpos[k]
        w, h, rh = sizes[k]
        lw = tw(z["label"], 8, True) + 16
        o.append(f'<rect x="{zx}" y="{zy}" width="{w}" height="{h}" rx="8" fill="{ZONE_FILL}" stroke="{ZONE_STROKE}" stroke-width="0.9" stroke-dasharray="5,4"/>')
        o.append(f'<rect x="{zx + 12}" y="{zy - 7}" width="{lw:.1f}" height="14" rx="2" fill="{PAPER}"/>')
        o.append(text(zx + 20, zy + 4, "$" + z["label"].upper(), 8, SOFT, "start", 600, ls="0.12em"))
        yy = zy + ZH
        for ri, r in enumerate(z["grid"]):
            for ci, e in enumerate(r):
                if not e:
                    continue
                ex = zx + ZP + ci * (EW + HG)
                boxes[e["name"]] = (ex, yy, EW, ent_h(e))
                ents.append((ex, yy, e))
            yy += rh[ri] + VG
    # relationships (drawn before entities)
    for (_, a, b, ca, cb, lab) in RELS:
        ax, ay, aw, ah = boxes[a]
        bx, by, bw, bh = boxes[b]
        if abs(ay - by) < 1:  # same row
            yline = ay + 46
            if bx > ax:
                x1, x2 = ax + aw, bx
            else:
                x1, x2 = ax, bx + bw
            o.append(f'<line x1="{x1}" y1="{yline}" x2="{x2}" y2="{yline}" stroke="{MUTED}" stroke-width="1.2"/>')
            s = 1 if x2 > x1 else -1
            o.append(label(x1 + s * 12, yline - 6, "$" + ca, 8.5, INK, "start" if s > 0 else "end", 600, 2))
            o.append(label(x2 - s * 12, yline - 6, "$" + cb, 8.5, INK, "end" if s > 0 else "start", 600, 2))
            if lab:
                o.append(label((x1 + x2) / 2, yline + 14, lab, 9.5, SOFT, "middle", 400, 2))
        else:  # same column
            xline = ax + aw / 2
            if by > ay:
                y1, y2 = ay + ah, by
            else:
                y1, y2 = ay, by + bh
            o.append(f'<line x1="{xline}" y1="{y1}" x2="{xline}" y2="{y2}" stroke="{MUTED}" stroke-width="1.2"/>')
            s = 1 if y2 > y1 else -1
            o.append(label(xline + 8, y1 + s * 14 + (4 if s > 0 else 0), "$" + ca, 8.5, INK, "start", 600, 2))
            o.append(label(xline + 8, y2 - s * 10 + (4 if s < 0 else 0), "$" + cb, 8.5, INK, "start", 600, 2))
    for (ex, ey, e) in ents:
        o.append(render_entity(ex, ey, e))
    items = [
        (lambda lx, ly: f'<rect x="{lx}" y="{ly - 8}" width="30" height="16" rx="3" fill="{ACCENT_TINT}" stroke="{ACCENT}"/>', "Thực thể gốc (aggregate root)"),
        (lambda lx, ly: f'<rect x="{lx}" y="{ly - 8}" width="30" height="16" rx="3" fill="{WHITE}" stroke="{INK}"/>', "Thực thể"),
        (lambda lx, ly: f'<rect x="{lx}" y="{ly - 8}" width="30" height="16" rx="3" fill="{WHITE}" stroke="{INK}" stroke-dasharray="5,3"/>', "Tài liệu nhúng (Mongo)"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 30}" y2="{ly}" stroke="{MUTED}" stroke-width="1.2"/>', "Quan hệ trong cùng DB · bội số"),
        (lambda lx, ly: text(lx + 10, ly + 4, "$#", 10, INK, "start", 600), "Khóa chính"),
        (lambda lx, ly: text(lx + 10, ly + 4, "$→", 10, MUTED, "start"), "Khóa ngoại trong DB"),
        (lambda lx, ly: text(lx + 10, ly + 4, "$↗", 10, LINK, "start"), "Tham chiếu sang service khác qua ID"),
    ]
    leg, lh = legend(items, 32, bottom + 32, width - 64)
    o.append(leg)
    return width, bottom + 32 + lh + 8, "\n".join(o)


# ===================================================================== pages
def strip_nav(html):
    return html.replace('<p class="nav"><a href="index.html">← Mục lục</a></p>',
                        '<p class="nav"><a href="index.html">← Mục lục</a></p>')


def main():
    out = []
    w, h, body = build_erd()
    html = page("erd-toan-he-thong", "ER diagram · logical · toàn hệ thống", "ERD toàn hệ thống",
                "34 thực thể nghiệp vụ của 12 database, gom theo service; quan hệ trong cùng database có bội số, "
                "tham chiếu giữa các service là tham chiếu logic qua ID.", w, h, body,
                "Kiến trúc database-per-service: giữa các service không có khóa ngoại, chỉ lưu ID (ký hiệu ↗) và đồng bộ qua HTTP/Kafka. "
                "payment-service không có bảng nghiệp vụ, chỉ có inbox_events/outbox_events cho saga; các bảng inbox/outbox của mọi service xem ở trang database chi tiết.")
    (HERE / "erd-toan-he-thong.html").write_text(html, encoding="utf-8")
    out.append(("erd-toan-he-thong", "ERD toàn hệ thống", "34 thực thể · 12 database"))
    w, h, body, ntot = build_all()
    html = page("database-toan-he-thong", "Database schema · toàn hệ thống", "Database toàn hệ thống",
                f"Lược đồ vật lý của 13 database (7 MongoDB, 6 PostgreSQL) với {ntot} bảng/collection trong một hình.",
                w, h, body,
                "Mỗi khung là một database riêng của một service. Giữa các database không có khóa ngoại; cột gắn REF lưu ID của "
                "service khác. Danh sách tham chiếu chi tiết xem ở trang database của từng service.")
    (HERE / "database-toan-he-thong.html").write_text(html, encoding="utf-8")
    out.append(("database-toan-he-thong", "Database toàn hệ thống (một hình)", f"13 database · {ntot} bảng/collection"))
    for db in DATABASES:
        w, h, body = build_db(db)
        slug = f"db-{db['slug']}"
        ntab = len(db["tables"])
        html = page(slug, f"Database schema · {db['engine']} · {db['db']}", f"{db['slug']} · {db['title']}",
                    f"Lược đồ vật lý của database {db['db']} ({db['engine']}) với {ntab} "
                    f"{'collection' if db['engine'] == 'MongoDB' else 'bảng'}, đủ cột, kiểu dữ liệu, ràng buộc và chỉ mục.",
                    w, h, body)
        (HERE / f"{slug}.html").write_text(html, encoding="utf-8")
        out.append((slug, f"{db['slug']} · {db['title']}", f"{db['engine']} · {ntab} {'collection' if db['engine'] == 'MongoDB' else 'bảng'}"))
    rows = "".join(f'<tr><td><a href="{s}.html">{esc(t)}</a></td><td class="m">{esc(m)}</td>'
                   f'<td class="r"><a class="png" href="png/{s}.png">png</a></td></tr>' for s, t, m in out)
    (HERE / "index.html").write_text(f"""<!DOCTYPE html><html lang="vi"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ERD &amp; Database</title>
<link href="{FONT_LINK}" rel="stylesheet"><style>
*{{box-sizing:border-box;margin:0;padding:0}} body{{font-family:{SANS};background:{PAPER};color:{INK};padding:3rem 2rem;display:flex;justify-content:center}}
.frame{{max-width:900px;width:100%}} .eyebrow{{font-family:{MONO};font-size:.66rem;letter-spacing:.18em;text-transform:uppercase;color:{MUTED};margin-bottom:.5rem}}
h1{{font-family:{SERIF};font-weight:400;font-size:2rem;margin-bottom:1rem}} p{{color:{MUTED};font-size:.9rem;line-height:1.6;margin-bottom:1.5rem}}
table{{width:100%;border-collapse:collapse}} td{{padding:.55rem .4rem;border-top:1px solid rgba(45,49,66,.12);font-size:.9rem}}
a{{color:{LINK};text-decoration:none}} td.m{{font-family:{MONO};font-size:.72rem;color:{MUTED}}} td.r{{text-align:right}} a.png{{font-family:{MONO};font-size:.72rem;color:{MUTED}}}
</style></head><body><div class="frame"><p class="eyebrow">ecommerce-microservices · data model</p>
<h1>ERD và lược đồ database</h1><p>ERD mức logic cho toàn hệ thống và lược đồ vật lý cho từng database
(7 MongoDB, 6 PostgreSQL), lấy trực tiếp từ model Mongoose/Sequelize trong mã nguồn.</p>
<table>{rows}</table></div></body></html>""", encoding="utf-8")
    for s, _, _ in out:
        print(s)


if __name__ == "__main__":
    main()
