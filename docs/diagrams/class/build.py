"""UML class diagram of the whole system in one image (packages = services).

Attributes come from the Mongoose/Sequelize models, operations from the controller
functions that act on each class. There is no class inheritance in the codebase, so
relationships are composition, aggregation, association and «enumeration» types.

    python docs/diagrams/class/build.py
    node docs/diagrams/uml/render_png.cjs --dir class
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uml"))

from engine import (ACCENT, ACCENT_TINT, INK, LINK, MUTED, PAPER, RULE, SOFT, WHITE,  # noqa: E402
                    label, legend, page, text, tw)

CW = 248          # class box width
LINE = 15         # member line height
HG, VG, ZP, ZH = 96, 44, 22, 34

ZONE_FILL = "rgba(45,49,66,0.02)"
ZONE_STROKE = "rgba(45,49,66,0.30)"


def K(name, attrs=(), ops=(), kind="class"):
    return dict(name=name, attrs=list(attrs), ops=list(ops), kind=kind)


def ENUM(name, values):
    return dict(name=name, attrs=list(values), ops=[], kind="enum")


PACKAGES = {
    "auth": dict(label="auth-service", grid=[[
        K("User", ["+ email: String {unique}", "- password: String", "+ role: Role", "+ shopId: String",
                   "+ isActive: Boolean", "+ tokenVersion: Number"],
          ["+ register(email, password, role)", "+ login(email, password): JWT", "+ validateSession(token)",
           "+ lock(id)", "+ unlock(id)"], "focal"),
        ENUM("Role", ["buyer", "seller", "admin"])]]),
    "user": dict(label="user-service", grid=[[
        K("UserProfile", ["+ userId: String {unique}", "+ name: String", "+ phone: String"],
          ["+ addAddress(addr)", "+ updateAddress(id, addr)", "+ deleteAddress(id)", "+ setDefaultAddress(id)"]),
        K("Address", ["+ fullName: String", "+ phone: String", "+ line1: String", "+ city: String", "+ isDefault: Boolean"])]]),
    "shop": dict(label="shop-service", grid=[[
        K("Shop", ["+ name: String", "+ ownerId: String", "+ invoiceRequestMode: String", "+ invoiceFeatureStatus: String",
                   "+ taxCode: String"],
          ["+ create(name, ownerId)", "+ getInvoiceFeature()", "+ requestInvoiceFeature(mode)"]),
        K("InvoiceFeatureRequest", ["+ requestedMode: String", "+ status: String", "+ reason: String", "+ reviewedBy: String"],
          ["+ review(decision, note)"])]]),
    "chat": dict(label="chat-service", grid=[[
        K("Conversation", ["+ shopId: String", "+ buyerId: String", "+ product: Object", "+ lastMessage: String"],
          ["+ open(shopId, buyerId)", "+ listByShop(shopId)", "+ listByBuyer(buyerId)"]),
        K("Message", ["+ senderRole: String", "+ senderId: String", "+ text: String", "+ createdAt: Date"],
          ["+ send(conversationId, text)"])]]),
    "review": dict(label="review-service", grid=[[
        K("Review", ["+ productId: String", "+ userId: String", "+ rating: Number [1..5]", "+ comment: String"],
          ["+ create(productId, rating)", "+ getByProduct(productId)", "+ getSummaries(ids)"])]]),
    "product": dict(label="product-service", grid=[
        [K("Category", ["+ name: String", "+ description: String", "+ shopId: String"],
           ["+ create(name)", "+ update(id, data)", "+ delete(id)"]),
         K("Product", ["+ name: String", "+ price: Number", "+ quantity: Number", "+ sold: Number", "+ shopId: String",
                       "+ moderationStatus: ModerationStatus"],
           ["+ create(data, files)", "+ update(id, data)", "+ moderate(action, note)", "+ getByIds(ids)",
            "- buildModerationFields()"], "focal"),
         K("Variant", ["+ name: String", "+ sku: String", "+ price: Number", "+ quantity: Number"])],
        [ENUM("ModerationStatus", ["pending", "approved", "rejected", "removed"]),
         K("Specification", ["+ name: String", "+ value: String"]), None]]),
    "cart": dict(label="cart-service", grid=[[
        K("Cart", ["+ userId: String {unique}"],
          ["+ addToCart(productId, variantId, qty)", "+ upsertLine(line)", "+ updateQuantity(line, qty)",
           "+ removeFromCart(line)", "- validateCartLine(line)"]),
        K("CartLine", ["+ productId: String", "+ variantId: String", "+ quantity: Number"])]]),
    "inventory": dict(label="inventory-service", grid=[[
        K("InventoryItem", ["+ productId: String", "+ variantId: String", "+ stockOnHand: Integer", "+ reservedStock: Integer"],
          ["+ reserve(orderId, items)", "+ release(orderId)", "+ commit(orderId)", "+ syncProduct(product)"]),
        K("InventoryReservation", ["+ orderId: String", "+ quantity: Integer", "+ status: String"])]]),
    "voucher": dict(label="voucher-service", grid=[[
        K("Voucher", ["+ code: String {unique}", "+ type: String", "+ discountType: String", "+ discountValue: Decimal",
                      "+ quantity: Integer", "+ usedCount: Integer"],
          ["+ listCheckout(items)", "+ reserve(orderId)", "+ release(orderId)", "+ commit(orderId)",
           "- calculateDiscount(items): Decimal"]),
        K("VoucherReservation", ["+ orderId: Integer", "+ userId: String", "+ discountAmount: Decimal", "+ status: String"])]]),
    "order": dict(label="order-service", grid=[
        [K("CheckoutQuote", ["+ userId: String", "+ paymentMethod: String", "+ totalPrice: Decimal", "+ status: String",
                             "+ expiresAt: Date"],
           ["+ create(cart, address, method)", "+ confirm(quoteId): Order[]"]),
         K("Order", ["+ userId: String", "+ products: JSON", "+ totalPrice: Decimal", "+ status: OrderStatus",
                     "+ voucherCode: String", "+ settlementStatus: String"],
           ["+ create(items, idempotencyKey)", "+ confirm(id)", "+ cancel(id)", "+ forceCancel(id)",
            "- cancelWithCompensation()"], "focal"),
         K("Shipment", ["+ shopId: String", "+ trackingCode: String {unique}", "+ carrier: String", "+ status: String"],
           ["+ create(orderId)", "+ applyStatus(status)", "+ receiveCallback(payload)"])],
        [ENUM("OrderStatus", ["pending_payment", "payment_processing", "paid", "confirmed", "shipped", "delivered",
                              "cancelled", "payment_failed", "refund_processing", "refunded"]),
         K("Dispute", ["+ userId: String", "+ reason: String", "+ status: String", "+ handledBy: String"],
           ["+ create(orderId, reason)", "+ resolve(status, note)"]), None]]),
    "gateway": dict(label="payment-gateway", grid=[[
        K("SepayPaymentRequest", ["+ requestCode: String {unique}", "+ purpose: String", "+ amount: Decimal",
                                  "+ status: String", "+ expiresAt: Date"],
          ["+ createOrderQr(orderId)", "+ createTopupQr(userId, amount)", "+ getStatus(id)"]),
        K("SepayWebhookLog", ["+ sepayTransactionId: String {unique}", "+ transferAmount: Decimal", "+ payload: JSON"],
          ["+ receiveWebhook(payload)"])]]),
    "messaging": dict(label="saga · order / payment / wallet / gateway", grid=[[
        K("InboxEvent", ["+ messageId: String {unique}", "+ topic: String", "+ status: String", "+ attempts: Integer"],
          ["+ process(handler)"]),
        K("OutboxEvent", ["+ topic: String", "+ eventKey: String", "+ status: String", "+ nextAttemptAt: Date"],
          ["+ publish()"])]]),
    "wallet": dict(label="wallet-service", grid=[
        [K("Wallet", ["+ userId: String", "+ currency: String", "+ status: String"],
           ["+ topup(amount)", "+ withdraw(amount)", "+ getTransactions()"]),
         K("WalletBalance", ["+ available: Decimal", "+ locked: Decimal", "+ version: Integer"]), None],
        [K("WalletLedgerEntry", ["+ type: String", "+ direction: String", "+ amount: Decimal", "+ referenceId: String {unique}"]),
         K("UserWithdrawalRequest", ["+ userId: String", "+ amount: Decimal", "+ status: String"],
           ["+ complete()", "+ fail(reason)"]),
         K("SettlementJob", ["+ orderId: Integer", "+ shopId: String", "+ amount: Decimal", "+ eligibleAt: Date"],
           ["+ run()"])],
        [K("AccountBalance", ["+ available: Decimal", "+ locked: Decimal", "+ version: Integer"]),
         K("Account", ["+ ownerType: String", "+ ownerId: String", "+ accountType: String", "+ allowNegative: Boolean"],
           ["+ getBalance()", "+ getLedger()"], "focal"),
         K("PayoutRequest", ["+ shopId: String", "+ amount: Decimal", "+ status: String"],
           ["+ complete()", "+ fail(reason)"])],
        [K("LedgerTransaction", ["+ referenceId: String {unique}", "+ type: String", "+ amount: Decimal", "+ status: String"],
           ["+ post(entries)"]),
         K("LedgerEntry", ["+ direction: String", "+ amount: Decimal", "+ availableAfter: Decimal"]), None]]),
}

# (package, A, B, kind, mult at A, mult at B)  kind: comp | aggr | assoc
RELS = [
    ("user", "UserProfile", "Address", "comp", "1", "0..*"),
    ("shop", "Shop", "InvoiceFeatureRequest", "comp", "1", "0..*"),
    ("chat", "Conversation", "Message", "assoc", "1", "0..*"),
    ("product", "Category", "Product", "aggr", "0..1", "0..*"),
    ("product", "Product", "Variant", "comp", "1", "0..*"),
    ("product", "Product", "Specification", "comp", "1", "0..*"),
    ("cart", "Cart", "CartLine", "comp", "1", "0..*"),
    ("inventory", "InventoryItem", "InventoryReservation", "assoc", "1", "0..*"),
    ("voucher", "Voucher", "VoucherReservation", "assoc", "1", "0..*"),
    ("order", "CheckoutQuote", "Order", "assoc", "1", "1..*"),
    ("order", "Order", "Shipment", "assoc", "1", "0..*"),
    ("order", "Order", "Dispute", "assoc", "1", "0..*"),
    ("gateway", "SepayPaymentRequest", "SepayWebhookLog", "assoc", "1", "0..*"),
    ("wallet", "Wallet", "WalletBalance", "comp", "1", "1"),
    ("wallet", "Wallet", "WalletLedgerEntry", "assoc", "1", "0..*"),
    ("wallet", "Account", "AccountBalance", "comp", "1", "1"),
    ("wallet", "Account", "UserWithdrawalRequest", "assoc", "1", "0..*"),
    ("wallet", "Account", "PayoutRequest", "assoc", "1", "0..*"),
    ("wallet", "Account", "LedgerEntry", "assoc", "1", "0..*"),
    ("wallet", "LedgerTransaction", "LedgerEntry", "comp", "1", "2..*"),
]

DEFS = f"""<defs>
  <marker id="u-comp" markerWidth="18" markerHeight="10" refX="1" refY="5" orient="auto"><polygon points="1 5, 9 1, 17 5, 9 9" fill="{INK}" stroke="{INK}" stroke-width="1"/></marker>
  <marker id="u-aggr" markerWidth="18" markerHeight="10" refX="1" refY="5" orient="auto"><polygon points="1 5, 9 1, 17 5, 9 9" fill="{WHITE}" stroke="{INK}" stroke-width="1"/></marker>
  <marker id="u-open" markerWidth="11" markerHeight="10" refX="10" refY="5" orient="auto"><polyline points="1 1, 10 5, 1 9" fill="none" stroke="{INK}" stroke-width="1.2"/></marker>
  <marker id="u-tri" markerWidth="16" markerHeight="14" refX="15" refY="7" orient="auto"><polygon points="1 1, 15 7, 1 13" fill="{PAPER}" stroke="{INK}" stroke-width="1.1"/></marker>
</defs>"""


def head_h(c):
    return 42 if c["kind"] == "enum" else 30


def class_h(c):
    h = head_h(c) + 8 + LINE * len(c["attrs"]) + 6
    if c["ops"]:
        h += 8 + LINE * len(c["ops"]) + 6
    return h


def render_class(x, y, c):
    h = class_h(c)
    focal = c["kind"] == "focal"
    stroke = ACCENT if focal else INK
    fill = ACCENT_TINT if focal else WHITE
    o = [f'<rect x="{x}" y="{y}" width="{CW}" height="{h}" rx="6" fill="{PAPER}"/>',
         f'<rect x="{x}" y="{y}" width="{CW}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.1"/>']
    hh = head_h(c)
    if c["kind"] == "enum":
        o.append(text(x + CW / 2, y + 16, "$«enumeration»", 8.5, MUTED, "middle", 500))
        o.append(text(x + CW / 2, y + 33, c["name"], 12.5, INK, "middle", 600))
    else:
        o.append(text(x + CW / 2, y + 20, c["name"], 12.5, INK, "middle", 600))
    yy = y + hh
    o.append(f'<line x1="{x}" y1="{yy}" x2="{x + CW}" y2="{yy}" stroke="{stroke}" stroke-width="0.8"/>')
    for i, a in enumerate(c["attrs"]):
        o.append(text(x + 12, yy + 8 + 11 + LINE * i, "$" + a, 9.5, INK if c["kind"] != "enum" else MUTED, "start"))
    yy += 8 + LINE * len(c["attrs"]) + 6
    if c["ops"]:
        o.append(f'<line x1="{x}" y1="{yy}" x2="{x + CW}" y2="{yy}" stroke="{stroke}" stroke-width="0.8"/>')
        for i, op in enumerate(c["ops"]):
            o.append(text(x + 12, yy + 8 + 11 + LINE * i, "$" + op, 9.5, LINK if op.startswith("+") else MUTED, "start"))
    return "\n".join(o)


def zone_size(z):
    g = z["grid"]
    ncol = max(len(r) for r in g)
    rh = [max(class_h(c) for c in r if c) for r in g]
    return ncol * CW + (ncol - 1) * HG + 2 * ZP, ZH + sum(rh) + (len(g) - 1) * VG + ZP, rh


def package_frame(x, y, w, h, name):
    tab_w = tw(name, 9.5, True) + 28
    return (f'<path d="M{x},{y + 22} V{y} H{x + tab_w} V{y + 22}" fill="{PAPER}" stroke="{INK}" stroke-width="0.9"/>'
            f'<rect x="{x}" y="{y + 22}" width="{w}" height="{h - 22}" fill="{ZONE_FILL}" stroke="{INK}" stroke-width="0.9"/>'
            + text(x + 12, y + 15, "$" + name, 9.5, INK, "start", 600))


def build():
    rows = [["auth", "user", "shop", "chat", "review"],
            ["product", "cart", "inventory", "voucher"],
            ["order", "gateway", "messaging"]]
    sizes = {k: zone_size(z) for k, z in PACKAGES.items()}
    zpos, row_tops, y, right = {}, [], 64, 0
    for r in rows:
        x = 40
        row_tops.append(y)
        for k in r:
            zpos[k] = (x, y)
            x += sizes[k][0] + 36
        right = max(right, x)
        y += max(sizes[k][1] for k in r) + 48
    wx = max(zpos[r[-1]][0] + sizes[r[-1]][0] for r in rows[1:]) + 36
    zpos["wallet"] = (wx, row_tops[1])
    width = max(right - 36, wx + sizes["wallet"][0]) + 40
    bottom = max(y - 48, row_tops[1] + sizes["wallet"][1] + 22)
    o = [f'<rect width="100%" height="100%" fill="{PAPER}"/>', DEFS]
    boxes, classes = {}, []
    for k, z in PACKAGES.items():
        zx, zy = zpos[k]
        w, h, rh = sizes[k]
        o.append(package_frame(zx, zy - 22, w, h + 22, z["label"]))
        yy = zy + ZH
        for ri, r in enumerate(z["grid"]):
            for ci, c in enumerate(r):
                if c:
                    cx = zx + ZP + ci * (CW + HG)
                    boxes[c["name"]] = (cx, yy, CW, class_h(c))
                    classes.append((cx, yy, c))
            yy += rh[ri] + VG
    for (_, a, b, kind, ma, mb) in RELS:
        ax, ay, aw, ah = boxes[a]
        bx, by, bw, bh = boxes[b]
        if abs(ay - by) < 1:
            yl = ay + 52
            x1, x2 = (ax + aw, bx) if bx > ax else (ax, bx + bw)
            p1, p2 = (x1, yl), (x2, yl)
            s = 1 if x2 > x1 else -1
            l1 = label(x1 + s * (26 if kind != "assoc" else 12), yl - 7, "$" + ma, 9, INK, "start" if s > 0 else "end", 600, 2)
            l2 = label(x2 - s * 16, yl - 7, "$" + mb, 9, INK, "end" if s > 0 else "start", 600, 2)
        else:
            xl = ax + aw / 2
            y1, y2 = (ay + ah, by) if by > ay else (ay, by + bh)
            p1, p2 = (xl, y1), (xl, y2)
            s = 1 if y2 > y1 else -1
            l1 = label(xl - 10, y1 + s * (22 if kind != "assoc" else 12) + 4, "$" + ma, 9, INK, "end", 600, 2)
            l2 = label(xl + 10, y2 - s * 14 + 4, "$" + mb, 9, INK, "start", 600, 2)
        start = {"comp": ' marker-start="url(#u-comp)"', "aggr": ' marker-start="url(#u-aggr)"', "assoc": ""}[kind]
        end = ' marker-end="url(#u-open)"' if kind == "assoc" else ""
        o.append(f'<line x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}" stroke="{INK}" stroke-width="1.1"{start}{end}/>')
        o += [l1, l2]
    for cx, cy, c in classes:
        o.append(render_class(cx, cy, c))
    items = [
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 34}" y2="{ly}" stroke="{INK}" stroke-width="1.1" marker-end="url(#u-tri)"/>', "Kế thừa"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 34}" y2="{ly}" stroke="{INK}" stroke-width="1.1" stroke-dasharray="5,4" marker-end="url(#u-tri)"/>', "Hiện thực"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 34}" y2="{ly}" stroke="{INK}" stroke-width="1.1" marker-start="url(#u-comp)"/>', "Hợp thành (composition)"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 34}" y2="{ly}" stroke="{INK}" stroke-width="1.1" marker-start="url(#u-aggr)"/>', "Kết tập (aggregation)"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 34}" y2="{ly}" stroke="{INK}" stroke-width="1.1" marker-end="url(#u-open)"/>', "Kết hợp (association)"),
        (lambda lx, ly: f'<line x1="{lx}" y1="{ly}" x2="{lx + 34}" y2="{ly}" stroke="{INK}" stroke-width="1.1" stroke-dasharray="4,3" marker-end="url(#u-open)"/>', "Phụ thuộc"),
        (lambda lx, ly: f'<rect x="{lx}" y="{ly - 8}" width="34" height="16" rx="3" fill="{ACCENT_TINT}" stroke="{ACCENT}"/>', "Class trung tâm"),
        (lambda lx, ly: text(lx + 4, ly + 4, "$+ / -", 10, INK, "start", 600), "public / private"),
    ]
    leg, lh = legend(items, 32, bottom + 24, width - 64)
    o.append(leg)
    note_y = bottom + 24 + lh + 6
    o.append(text(32, note_y + 14, "Giữa các package không vẽ quan hệ: mỗi service có database riêng và chỉ lưu ID của service khác "
                  "(userId, shopId, productId, orderId). Không có quan hệ kế thừa nào trong mã nguồn.", 11, MUTED, "start"))
    return width, note_y + 28, "\n".join(o)


def main():
    w, h, body = build()
    n = sum(1 for z in PACKAGES.values() for r in z["grid"] for c in r if c)
    html = page("uml-class-toan-he-thong", "UML 2.5 · Class diagram · toàn hệ thống", "Class diagram toàn hệ thống",
                f"{n} class và enumeration trong 13 package theo service, với thuộc tính, thao tác và quan hệ "
                "hợp thành, kết tập, kết hợp.", w, h, body,
                "Thuộc tính lấy từ model Mongoose/Sequelize; thao tác là các hàm controller thao tác trên class đó "
                "(đổi tên ngắn gọn, ví dụ moderateProduct → Product.moderate). Hợp thành dùng cho tài liệu nhúng của Mongo "
                "và quan hệ có ON DELETE CASCADE; còn lại là kết hợp.")
    html = html.replace('<p class="nav"><a href="index.html">← Mục lục</a></p>', "")
    (HERE / "uml-class-toan-he-thong.html").write_text(html, encoding="utf-8")
    print("uml-class-toan-he-thong.html", n)


if __name__ == "__main__":
    main()
