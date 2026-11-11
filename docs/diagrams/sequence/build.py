"""Sequence diagrams for use cases 4.3.1 – 4.3.15 (PNG output).

    python docs/diagrams/sequence/build.py
    node docs/diagrams/uml/render_png.cjs --dir sequence

Kafka events are drawn as asynchronous messages straight between the producing and
consuming services (label = topic), so the bus itself is not a lifeline.
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uml"))

from engine import build_sequence, page  # noqa: E402

BUYER = dict(id="u", label="Người mua", kind="actor")
GUEST = dict(id="u", label="Khách", kind="actor")
SELLER = dict(id="s", label="Người bán", kind="actor")
ADMIN = dict(id="a", label="Quản trị viên", kind="actor")
WEB = dict(id="fe", label=":Web App", sub="frontend (React)")
GW = dict(id="gw", label=":API Gateway", sub="JWT · định tuyến")
AUTH = dict(id="auth", label=":Auth Service", sub="auth-service")
USR = dict(id="usr", label=":User Service", sub="user-service")
SHOP = dict(id="shop", label=":Shop Service", sub="shop-service")
PROD = dict(id="prod", label=":Product Service", sub="product-service")
REV = dict(id="rev", label=":Review Service", sub="review-service")
CART = dict(id="cart", label=":Cart Service", sub="cart-service")
ORD = dict(id="ord", label=":Order Service", sub="order-service")
INV = dict(id="inv", label=":Inventory Service", sub="inventory-service")
VOU = dict(id="vou", label=":Voucher Service", sub="voucher-service")
IV = dict(id="iv", label=":Inventory · Voucher", sub="inventory / voucher-service")
PAY = dict(id="pay", label=":Payment Service", sub="payment-service (saga)")
PG = dict(id="pg", label=":Payment Gateway", sub="payment-gateway")
WAL = dict(id="wal", label=":Wallet Service", sub="wallet-service")
SEPAY = dict(id="sp", label=":SePay", sub="ngân hàng · webhook", kind="ext")
CARRIER = dict(id="car", label=":Đơn vị vận chuyển", sub="shipping (giả lập)", kind="ext")
LLM = dict(id="llm", label=":LLM Provider", sub="external API", kind="ext")
QDRANT = dict(id="vec", label=":Qdrant", sub="vector store")


def F(d, **kw):
    return dict(d, **kw)


DIAGRAMS = [
    ("4-3-1-dang-ky-tai-khoan", "4.3.1 Đăng ký tài khoản", dict(
        parts=[GUEST, WEB, GW, F(AUTH, focal=True), USR, SHOP],
        steps=[
            ("m", "u", "fe", "Nhập email, mật khẩu, vai trò (+ tên gian hàng)"),
            ("m", "fe", "gw", "$POST /auth/register"),
            ("m", "gw", "auth", "register(email, password, role, ...)"),
            ("alt", "[email đã tồn tại / thiếu dữ liệu / role = admin]"),
            ("m", "auth", "gw", "$409 / 400 / 403", "ret"),
            ("m", "gw", "fe", "Thông báo lỗi", "ret"),
            ("else", "[dữ liệu hợp lệ]"),
            ("m", "auth", "auth", "bcrypt.hash, tạo User (isActive = true)"),
            ("alt", "[role = buyer]"),
            ("m", "auth", "usr", "$POST /users {userId, name}"),
            ("m", "usr", "auth", "$201 UserProfile", "ret"),
            ("else", "[role = seller]"),
            ("m", "auth", "shop", "$POST /shops {name, ownerId, taxCode}"),
            ("m", "shop", "auth", "$201 Shop", "ret"),
            ("m", "auth", "auth", "Lưu shopId vào User"),
            ("end",),
            ("m", "auth", "gw", "$201 {id, email, role, shopId}", "ret-ok"),
            ("m", "gw", "fe", "$201 Created", "ret"),
            ("end",),
            ("m", "fe", "u", "Chuyển sang trang đăng nhập / báo lỗi", "ret"),
        ])),
    ("4-3-2-dang-nhap", "4.3.2 Đăng nhập", dict(
        parts=[F(GUEST, label="Người dùng"), WEB, GW, F(AUTH, focal=True)],
        steps=[
            ("m", "u", "fe", "Nhập email, mật khẩu"),
            ("m", "fe", "gw", "$POST /auth/login"),
            ("m", "gw", "auth", "login(email, password, role)"),
            ("m", "auth", "auth", "Tìm User theo email, bcrypt.compare"),
            ("alt", "[không tìm thấy / sai mật khẩu]"),
            ("m", "auth", "gw", "$401 Invalid credentials", "ret"),
            ("m", "gw", "fe", "$401", "ret"),
            ("else", "[isActive = false / sai vai trò]"),
            ("m", "auth", "gw", "$403 Account is locked", "ret"),
            ("m", "gw", "fe", "$403", "ret"),
            ("else", "[hợp lệ]"),
            ("m", "auth", "auth", "Ký JWT {userId, role, shopId, tokenVersion}"),
            ("m", "auth", "gw", "$200 {token, user}", "ret-ok"),
            ("m", "gw", "fe", "$200 {token, user}", "ret"),
            ("m", "fe", "fe", "Lưu token, gắn Bearer cho request sau"),
            ("end",),
            ("m", "fe", "u", "Vào trang theo vai trò / báo lỗi", "ret"),
        ])),
    ("4-3-3-duyet-tim-kiem-san-pham", "4.3.3 Duyệt và tìm kiếm sản phẩm", dict(
        parts=[BUYER, WEB, GW, F(PROD, focal=True), REV],
        steps=[
            ("m", "u", "fe", "Mở trang chủ, nhập từ khóa / chọn danh mục"),
            ("m", "fe", "gw", "$GET /categories"),
            ("m", "gw", "prod", "getCategories()"),
            ("m", "prod", "gw", "Danh mục", "ret"),
            ("m", "gw", "fe", "$200 categories[]", "ret"),
            ("m", "fe", "gw", "$GET /products?q=&categoryId=&sort=&page="),
            ("m", "gw", "prod", "getProducts(filter, sort, page)"),
            ("m", "prod", "prod", "Lọc approved, sắp xếp, phân trang"),
            ("m", "prod", "gw", "$200 {items, total, page}", "ret"),
            ("m", "gw", "fe", "$200", "ret"),
            ("m", "fe", "u", "Hiển thị lưới sản phẩm", "ret"),
            ("opt", "[người mua xem chi tiết]"),
            ("m", "u", "fe", "Chọn sản phẩm"),
            ("m", "fe", "gw", "$GET /products/{id}"),
            ("m", "gw", "prod", "getProductById(id)"),
            ("m", "prod", "gw", "Sản phẩm + biến thể + thông số", "ret"),
            ("m", "gw", "fe", "$200 product", "ret"),
            ("m", "fe", "gw", "$GET /reviews/product/{id}"),
            ("m", "gw", "rev", "getReviewsByProduct(id)"),
            ("m", "rev", "gw", "Đánh giá", "ret"),
            ("m", "gw", "fe", "$200 reviews[]", "ret"),
            ("m", "fe", "u", "Trang chi tiết, biến thể, đánh giá", "ret-ok"),
            ("end",),
        ])),
    ("4-3-4-tro-ly-mua-sam", "4.3.4 Tương tác với trợ lý mua sắm", dict(
        parts=[BUYER, F(WEB, sub="ShoppingAssistant"), GW,
               dict(id="bot", label=":Trợ lý mua sắm", sub="chatbot-service", focal=True),
               QDRANT, dict(id="svc", label=":Marketplace", sub="product / cart / order"), LLM],
        steps=[
            ("m", "u", "fe", "Nhập câu hỏi / gửi ảnh / giọng nói"),
            ("m", "fe", "gw", "$POST /assistant/chat"),
            ("m", "gw", "bot", "chat(message, image, userId đã xác thực)"),
            ("m", "bot", "llm", "Hiểu ý định, trích ràng buộc"),
            ("m", "llm", "bot", "intent, slots", "ret"),
            ("alt", "[tìm sản phẩm / hỏi chính sách]"),
            ("m", "bot", "vec", "Hybrid search sản phẩm / chính sách"),
            ("m", "vec", "bot", "Ứng viên + nguồn", "ret"),
            ("m", "bot", "svc", "$GET /products/batch?ids="),
            ("m", "svc", "bot", "Giá, tồn kho thực tế", "ret"),
            ("m", "bot", "llm", "Sinh câu trả lời có trích dẫn"),
            ("m", "llm", "bot", "Câu trả lời", "ret"),
            ("m", "bot", "gw", "$200 {text, products[]}", "ret"),
            ("else", "[thêm vào giỏ / đặt hàng]"),
            ("m", "bot", "bot", "Tạo pendingAction (chưa ghi dữ liệu)"),
            ("m", "bot", "gw", "$200 {text, pendingAction}", "ret"),
            ("m", "gw", "fe", "Thẻ xác nhận", "ret"),
            ("m", "u", "fe", "Bấm Xác nhận"),
            ("m", "fe", "gw", "$POST /assistant/chat {confirmActionId}"),
            ("m", "gw", "bot", "chat(confirmActionId)"),
            ("m", "bot", "svc", "$PUT /cart/items · POST /orders"),
            ("m", "svc", "bot", "Kết quả ghi", "ret"),
            ("m", "bot", "gw", "$200 {text, actionResult}", "ret"),
            ("end",),
            ("m", "gw", "fe", "$200", "ret"),
            ("m", "fe", "u", "Câu trả lời, thẻ sản phẩm, kết quả", "ret-ok"),
        ])),
    ("4-3-5-quan-ly-gio-hang", "4.3.5 Quản lý giỏ hàng", dict(
        parts=[BUYER, WEB, GW, F(CART, focal=True), PROD, INV],
        steps=[
            ("m", "u", "fe", "Chọn biến thể, số lượng, bấm Thêm vào giỏ"),
            ("m", "fe", "gw", "$POST /cart/add"),
            ("m", "gw", "cart", "addToCart(userId, productId, variantId, qty)"),
            ("par", ""),
            ("m", "cart", "prod", "$GET /products/{id}"),
            ("m", "prod", "cart", "Sản phẩm, giá, biến thể", "ret"),
            ("else", " "),
            ("m", "cart", "inv", "$GET /inventory/products/{id}"),
            ("m", "inv", "cart", "Tồn kho khả dụng", "ret"),
            ("end",),
            ("alt", "[sản phẩm hợp lệ và đủ tồn kho]"),
            ("m", "cart", "cart", "Gộp dòng trùng, cập nhật số lượng"),
            ("m", "cart", "gw", "$200 Cart", "ret-ok"),
            ("m", "gw", "fe", "$200 Cart", "ret"),
            ("else", "[hết hàng / vượt tồn kho]"),
            ("m", "cart", "gw", "$409 Không đủ hàng", "ret"),
            ("m", "gw", "fe", "$409", "ret"),
            ("end",),
            ("opt", "[đổi số lượng hoặc xóa dòng]"),
            ("m", "u", "fe", "Sửa số lượng / xóa sản phẩm"),
            ("m", "fe", "gw", "$POST /cart/update · /cart/remove"),
            ("m", "gw", "cart", "updateQuantity() / removeFromCart()"),
            ("m", "cart", "gw", "$200 Cart (tính lại tạm tính)", "ret"),
            ("m", "gw", "fe", "$200 Cart", "ret"),
            ("end",),
            ("m", "fe", "u", "Cập nhật giỏ hàng / báo lỗi", "ret"),
        ])),
    ("4-3-6-dat-hang", "4.3.6 Đặt hàng", dict(
        parts=[BUYER, WEB, GW, F(ORD, focal=True), INV, VOU, PAY],
        steps=[
            ("m", "u", "fe", "Chọn địa chỉ, voucher, phương thức, bấm Đặt hàng"),
            ("m", "fe", "gw", "$POST /orders {items, address, voucherCode, paymentMethod}"),
            ("m", "gw", "ord", "createOrder(items, idempotencyKey)"),
            ("m", "ord", "ord", "Kiểm tra idempotencyKey, tính tổng tiền"),
            ("m", "ord", "inv", "$POST /inventory/reserve"),
            ("m", "inv", "ord", "Đã giữ hàng / 409 hết hàng", "ret"),
            ("opt", "[có voucherCode]"),
            ("m", "ord", "vou", "$POST /vouchers/reserve"),
            ("m", "vou", "ord", "Mức giảm / không hợp lệ", "ret"),
            ("end",),
            ("alt", "[giữ hàng hoặc voucher thất bại]"),
            ("m", "ord", "inv", "$POST /inventory/release (bù trừ)"),
            ("m", "ord", "gw", "$409 Không thể đặt hàng", "ret"),
            ("m", "gw", "fe", "$409", "ret"),
            ("else", "[thành công]"),
            ("m", "ord", "ord", "Lưu Order (status = pending_payment)"),
            ("m", "ord", "pay", "$order.created", "async"),
            ("m", "ord", "gw", "$201 Order", "ret-ok"),
            ("m", "gw", "fe", "$201 Order", "ret"),
            ("m", "fe", "gw", "$POST /cart/remove (dọn giỏ)"),
            ("end",),
            ("m", "fe", "u", "Chuyển sang bước thanh toán / báo lỗi", "ret"),
        ])),
    ("4-3-7-thanh-toan-don-hang", "4.3.7 Thanh toán đơn hàng", dict(
        parts=[BUYER, WEB, PG, SEPAY, F(PAY, focal=True), WAL, ORD],
        steps=[
            ("m", "ord", "pay", "$order.created {orderId, paymentMethod}", "async"),
            ("alt", "[paymentMethod = wallet]"),
            ("m", "pay", "wal", "$wallet.debit.requested", "async"),
            ("m", "wal", "wal", "Trừ số dư, ghi sổ cái kép"),
            ("m", "wal", "pay", "$wallet.debited / debit_failed", "async"),
            ("m", "pay", "ord", "$payment.succeeded / failed", "async"),
            ("else", "[paymentMethod = bank_transfer]"),
            ("m", "fe", "pg", "$POST /payments/sepay/orders/{id}/qr"),
            ("m", "pg", "fe", "Mã QR + nội dung chuyển khoản", "ret"),
            ("m", "u", "sp", "Quét QR, chuyển khoản", "async"),
            ("m", "sp", "pg", "$POST /payments/sepay/webhook", "async"),
            ("m", "pg", "pg", "Đối soát số tiền, ghi webhook log"),
            ("m", "pg", "pay", "$qr.payment.succeeded", "async"),
            ("m", "pay", "ord", "$payment.succeeded", "async"),
            ("else", "[paymentMethod = cod]"),
            ("m", "pay", "ord", "$payment.pending (thu khi giao)", "async"),
            ("end",),
            ("m", "ord", "ord", "status = paid / chờ COD, commit tồn kho + voucher"),
            ("m", "fe", "ord", "$GET /orders/user"),
            ("m", "ord", "fe", "Trạng thái thanh toán mới", "ret-ok"),
            ("m", "fe", "u", "Hiển thị đơn đã thanh toán", "ret"),
        ])),
    ("4-3-8-quan-ly-san-pham-ton-kho", "4.3.8 Quản lý sản phẩm và tồn kho", dict(
        parts=[SELLER, F(WEB, sub="Seller Center"), GW, F(PROD, focal=True), INV],
        steps=[
            ("m", "s", "fe", "Nhập tên, mô tả, giá, biến thể, ảnh"),
            ("m", "fe", "gw", "$POST /products (multipart)"),
            ("m", "gw", "prod", "createProduct(data, files)"),
            ("m", "prod", "prod", "Lưu ảnh (MinIO), kiểm duyệt từ khóa"),
            ("alt", "[phát hiện từ khóa vi phạm]"),
            ("m", "prod", "prod", "moderationStatus = pending"),
            ("else", "[hợp lệ]"),
            ("m", "prod", "prod", "moderationStatus = approved"),
            ("end",),
            ("m", "prod", "inv", "$product.created", "async"),
            ("m", "inv", "inv", "Khởi tạo tồn kho từng biến thể"),
            ("m", "prod", "gw", "$201 {product, flagged}", "ret"),
            ("m", "gw", "fe", "$201", "ret"),
            ("m", "fe", "s", "Sản phẩm và trạng thái duyệt", "ret-ok"),
            ("opt", "[cập nhật tồn kho]"),
            ("m", "s", "fe", "Sửa số lượng tồn của biến thể"),
            ("m", "fe", "gw", "$PATCH /inventory/products/{id}/variants/{vid}"),
            ("m", "gw", "inv", "updateInventory(stockOnHand)"),
            ("m", "inv", "gw", "$200 Tồn kho mới", "ret"),
            ("m", "gw", "fe", "$200", "ret"),
            ("end",),
            ("opt", "[sửa / xóa sản phẩm]"),
            ("m", "fe", "gw", "$PUT · DELETE /products/{id}"),
            ("m", "gw", "prod", "updateProduct() / deleteProduct()"),
            ("m", "prod", "inv", "$product.updated / deleted", "async"),
            ("m", "prod", "gw", "$200", "ret"),
            ("m", "gw", "fe", "$200", "ret"),
            ("end",),
        ])),
    ("4-3-9-kiem-duyet-san-pham", "4.3.9 Kiểm duyệt sản phẩm", dict(
        parts=[ADMIN, F(WEB, sub="Admin Console"), GW, F(PROD, focal=True),
               dict(id="idx", label=":Chỉ mục tìm kiếm", sub="chatbot indexer · Qdrant")],
        steps=[
            ("m", "a", "fe", "Mở hàng chờ kiểm duyệt"),
            ("m", "fe", "gw", "$GET /products/admin/pending"),
            ("m", "gw", "prod", "getPendingProducts()"),
            ("m", "prod", "gw", "Sản phẩm pending + lý do gắn cờ", "ret"),
            ("m", "gw", "fe", "$200 products[]", "ret"),
            ("m", "a", "fe", "Xem chi tiết, chọn Duyệt / Từ chối"),
            ("m", "fe", "gw", "$PATCH /products/admin/{id}/moderate"),
            ("m", "gw", "prod", "moderateProduct(id, action, reason)"),
            ("alt", "[action = approve]"),
            ("m", "prod", "prod", "moderationStatus = approved"),
            ("m", "prod", "idx", "$product.updated", "async"),
            ("m", "idx", "idx", "Đưa vào chỉ mục tìm kiếm"),
            ("else", "[action = reject / remove]"),
            ("m", "prod", "prod", "status = rejected, lưu lý do"),
            ("m", "prod", "idx", "$product.updated (gỡ khỏi tìm kiếm)", "async"),
            ("end",),
            ("m", "prod", "gw", "$200 Product", "ret"),
            ("m", "gw", "fe", "$200", "ret"),
            ("m", "fe", "a", "Cập nhật hàng chờ", "ret-ok"),
        ])),
    ("4-3-10-xu-ly-don-cua-cua-hang", "4.3.10 Xem và xử lý đơn hàng của cửa hàng", dict(
        parts=[SELLER, F(WEB, sub="Seller Center"), GW, F(ORD, focal=True), CARRIER, WAL],
        steps=[
            ("m", "s", "fe", "Mở Đơn hàng của shop"),
            ("m", "fe", "gw", "$GET /orders/seller/{shopId}"),
            ("m", "gw", "ord", "getSellerOrders(shopId)"),
            ("m", "ord", "gw", "Đơn paid / chờ COD", "ret"),
            ("m", "gw", "fe", "$200 orders[]", "ret"),
            ("alt", "[người bán nhận đơn]"),
            ("m", "fe", "gw", "$POST /orders/{id}/confirm"),
            ("m", "gw", "ord", "confirmOrder(id)"),
            ("m", "ord", "gw", "$200 confirmed", "ret"),
            ("m", "fe", "gw", "$POST /orders/{id}/shipments"),
            ("m", "gw", "ord", "createShipment(id)"),
            ("m", "ord", "car", "Tạo vận đơn (requested)"),
            ("m", "car", "ord", "Mã vận đơn", "ret"),
            ("m", "ord", "gw", "$201 Shipment", "ret"),
            ("else", "[từ chối / hết hàng]"),
            ("m", "fe", "gw", "$POST /orders/{id}/cancel"),
            ("m", "gw", "ord", "cancelOrder(id)"),
            ("m", "ord", "gw", "Đã hủy, nhả hàng, hoàn tiền nếu cần", "ret"),
            ("end",),
            ("loop", "[mỗi lần đổi trạng thái vận chuyển]"),
            ("m", "car", "ord", "$POST /orders/shipping/callback", "async"),
            ("m", "ord", "ord", "picked_up → in_transit → delivered"),
            ("end",),
            ("m", "ord", "wal", "$order.delivered", "async"),
            ("m", "wal", "wal", "Tạo quyết toán, cộng doanh thu shop"),
            ("m", "gw", "fe", "Trạng thái đơn mới", "ret-ok"),
        ])),
    ("4-3-11-xem-don-theo-doi-giao-hang", "4.3.11 Xem đơn hàng và theo dõi giao hàng", dict(
        parts=[BUYER, WEB, GW, F(ORD, focal=True)],
        steps=[
            ("m", "u", "fe", "Mở Đơn hàng của tôi"),
            ("m", "fe", "gw", "$GET /orders/user"),
            ("m", "gw", "ord", "getUserOrders(userId)"),
            ("m", "ord", "gw", "Đơn hàng + trạng thái", "ret"),
            ("m", "gw", "fe", "$200 orders[]", "ret"),
            ("m", "fe", "u", "Danh sách đơn theo trạng thái", "ret"),
            ("m", "u", "fe", "Chọn đơn, bấm Theo dõi"),
            ("m", "fe", "gw", "$GET /orders/shipments/order/{id}"),
            ("m", "gw", "ord", "getOrderShipment(orderId)"),
            ("m", "ord", "ord", "Kiểm tra người mua sở hữu đơn"),
            ("alt", "[đã có vận đơn]"),
            ("m", "ord", "gw", "$200 {trackingCode, carrier, status, mốc thời gian}", "ret-ok"),
            ("else", "[chưa tạo vận đơn]"),
            ("m", "ord", "gw", "$404 Chưa có vận đơn", "ret"),
            ("end",),
            ("m", "gw", "fe", "Thông tin vận chuyển", "ret"),
            ("m", "fe", "u", "Hành trình: requested → picked_up → in_transit → delivered", "ret"),
        ])),
    ("4-3-12-huy-don-hang", "4.3.12 Hủy đơn hàng", dict(
        parts=[BUYER, WEB, GW, F(ORD, focal=True), IV, PAY, WAL],
        steps=[
            ("m", "u", "fe", "Bấm Hủy đơn"),
            ("m", "fe", "gw", "$POST /orders/{id}/cancel"),
            ("m", "gw", "ord", "cancelOrder(id)"),
            ("alt", "[status = delivered]"),
            ("m", "ord", "gw", "$400 Hãy tạo yêu cầu trả hàng", "ret"),
            ("m", "gw", "fe", "$400", "ret"),
            ("else", "[chưa giao]"),
            ("m", "ord", "ord", "status = cancelled"),
            ("m", "ord", "iv", "Nhả tồn kho + voucher (release)"),
            ("m", "iv", "ord", "Đã nhả", "ret"),
            ("m", "ord", "pay", "$order.cancelled", "async"),
            ("m", "ord", "gw", "$200 Order (cancelled)", "ret"),
            ("m", "gw", "fe", "$200", "ret"),
            ("opt", "[đơn đã được thanh toán]"),
            ("m", "pay", "wal", "$wallet.refund.requested", "async"),
            ("m", "wal", "wal", "Cộng lại tiền vào ví người mua"),
            ("m", "wal", "pay", "$wallet.refunded", "async"),
            ("m", "pay", "ord", "$payment.refunded", "async"),
            ("end",),
            ("end",),
            ("m", "fe", "u", "Đơn đã hủy (và đã hoàn tiền nếu có)", "ret-ok"),
        ])),
    ("4-3-13-yeu-cau-tra-hang-hoan-tien", "4.3.13 Yêu cầu trả hàng hoặc hoàn tiền", dict(
        parts=[BUYER, WEB, GW, F(ORD, focal=True)],
        steps=[
            ("m", "u", "fe", "Chọn đơn đã giao, bấm Trả hàng / hoàn tiền"),
            ("m", "u", "fe", "Nhập lý do, ghi chú, bằng chứng"),
            ("m", "fe", "gw", "$POST /orders/{id}/disputes {reason, note, evidenceText}"),
            ("m", "gw", "ord", "createDispute(orderId, reason)"),
            ("m", "ord", "ord", "Kiểm tra người mua sở hữu đơn"),
            ("alt", "[status ≠ delivered]"),
            ("m", "ord", "gw", "$400 Chỉ áp dụng cho đơn đã giao", "ret"),
            ("else", "[thiếu lý do]"),
            ("m", "ord", "gw", "$400 reason is required", "ret"),
            ("else", "[hợp lệ]"),
            ("m", "ord", "ord", "Tạo Dispute (status = open)"),
            ("m", "ord", "gw", "$201 Dispute", "ret-ok"),
            ("end",),
            ("m", "gw", "fe", "Kết quả", "ret"),
            ("m", "fe", "u", "Đã gửi yêu cầu, chờ quản trị viên xử lý", "ret"),
        ])),
    ("4-3-14-giai-quyet-tra-hang-hoan-tien", "4.3.14 Giải quyết yêu cầu trả hàng và hoàn tiền", dict(
        parts=[ADMIN, F(WEB, sub="Admin Console"), GW, F(ORD, focal=True), PAY, WAL],
        steps=[
            ("m", "a", "fe", "Mở danh sách khiếu nại"),
            ("m", "fe", "gw", "$GET /orders/admin/disputes"),
            ("m", "gw", "ord", "getAdminDisputes()"),
            ("m", "ord", "gw", "Khiếu nại + đơn liên quan", "ret"),
            ("m", "gw", "fe", "$200 disputes[]", "ret"),
            ("m", "a", "fe", "Xem bằng chứng, chọn Chấp nhận / Từ chối"),
            ("m", "fe", "gw", "$PATCH /orders/admin/disputes/{id} {status, note}"),
            ("m", "gw", "ord", "updateAdminDispute(status, note)"),
            ("alt", "[status = resolved]"),
            ("m", "ord", "ord", "order.status = refund_processing"),
            ("m", "ord", "pay", "$order.refund_requested", "async"),
            ("m", "pay", "wal", "$wallet.refund.requested", "async"),
            ("m", "wal", "wal", "Cộng tiền vào ví người mua"),
            ("m", "wal", "pay", "$wallet.refunded", "async"),
            ("m", "pay", "ord", "$payment.refunded", "async"),
            ("m", "ord", "ord", "order.status = refunded"),
            ("else", "[status = rejected]"),
            ("m", "ord", "ord", "Lưu ghi chú, đóng khiếu nại"),
            ("end",),
            ("m", "ord", "gw", "$200 {dispute, refundQueued}", "ret"),
            ("m", "gw", "fe", "$200", "ret"),
            ("m", "fe", "a", "Cập nhật trạng thái khiếu nại", "ret-ok"),
        ])),
    ("4-3-15-vi-giao-dich-nap-tien", "4.3.15 Xem ví, lịch sử giao dịch và nạp tiền", dict(
        parts=[BUYER, WEB, GW, F(WAL, focal=True), PG, SEPAY],
        steps=[
            ("m", "u", "fe", "Mở Ví của tôi"),
            ("m", "fe", "gw", "$GET /payments/wallet/{userId}"),
            ("m", "gw", "wal", "getWalletByUser(userId)"),
            ("m", "wal", "gw", "Số dư khả dụng, tạm giữ", "ret"),
            ("m", "gw", "fe", "$200 wallet", "ret"),
            ("m", "fe", "gw", "$GET /payments/wallet/{userId}/transactions"),
            ("m", "gw", "wal", "getWalletTransactions(userId)"),
            ("m", "wal", "gw", "Lịch sử giao dịch", "ret"),
            ("m", "gw", "fe", "$200 transactions[]", "ret"),
            ("m", "fe", "u", "Số dư và lịch sử giao dịch", "ret"),
            ("opt", "[nạp tiền]"),
            ("m", "u", "fe", "Nhập số tiền cần nạp"),
            ("m", "fe", "gw", "$POST /payments/wallet/{userId}/topup/sepay-qr"),
            ("m", "gw", "pg", "createSepayTopupQr(userId, amount)"),
            ("m", "pg", "gw", "Mã QR + requestId", "ret"),
            ("m", "gw", "fe", "$201 QR", "ret"),
            ("m", "u", "sp", "Quét QR, chuyển khoản", "async"),
            ("m", "sp", "pg", "$POST /payments/sepay/webhook", "async"),
            ("m", "pg", "wal", "$qr.payment.succeeded (purpose = topup)", "async"),
            ("m", "wal", "wal", "Cộng số dư, ghi sổ cái"),
            ("m", "fe", "gw", "$GET /payments/sepay/requests/{id}"),
            ("m", "gw", "pg", "getSepayRequestStatus(id)"),
            ("m", "pg", "gw", "status = paid", "ret"),
            ("m", "gw", "fe", "$200", "ret"),
            ("end",),
            ("m", "fe", "u", "Số dư mới", "ret-ok"),
        ])),
]


def main():
    for slug, title, spec in DIAGRAMS:
        spec["title"] = title.split(" ", 1)[1]
        w, h, body = build_sequence(spec)
        html = page(f"seq-{slug}", f"UML 2.5 · Sequence diagram · {title.split(' ')[0]}", title,
                    f"Sequence diagram cho use case {title}.", w, h, body)
        html = html.replace('<p class="nav"><a href="index.html">← Mục lục</a></p>', "")
        (HERE / f"{slug}.html").write_text(html, encoding="utf-8")
        print(slug)


if __name__ == "__main__":
    main()
