"""Physical schema of every database, transcribed from the service models.

Column tuple: (name, type, flags, ref)
  flags: space-separated subset of PK FK UQ NN IDX
  ref:   "table.column"  -> reference inside the same database (drawn as an edge)
         "@svc.coll.col"  -> logical reference to another service (listed under the diagram)
Embedded Mongo sub-documents: ("embed", "field[]", [columns...])
"""

C = lambda name, typ, flags="", ref=None: (name, typ, flags, ref)  # noqa: E731
TS_MONGO = [C("createdAt", "Date"), C("updatedAt", "Date")]


def EMB(field, cols):
    return ("embed", field, cols)


INBOX = [
    C("id", "serial", "PK"), C("message_id", "varchar(160)", "UQ NN"), C("topic", "varchar(120)", "NN"),
    C("payload", "jsonb", "NN"), C("status", "varchar(24)", "NN"), C("attempts", "integer", "NN"),
    C("error", "text"), C("processed_at", "timestamptz"),
]
OUTBOX = [
    C("id", "uuid", "PK"), C("aggregate_type", "varchar(80)", "NN"), C("aggregate_id", "varchar(128)", "NN"),
    C("event_type", "varchar(120)", "NN"), C("topic", "varchar(120)", "NN"), C("event_key", "varchar(128)", "NN"),
    C("payload", "jsonb", "NN"), C("headers", "jsonb", "NN"), C("status", "varchar(24)", "NN"),
    C("attempts", "integer", "NN"), C("next_attempt_at", "timestamptz"), C("published_at", "timestamptz"),
    C("error", "text"), C("saga_id", "varchar(128)"), C("correlation_id", "varchar(128)"),
]
SAGA = [C("saga_id", "varchar(128)"), C("correlation_id", "varchar(128)")]

DATABASES = [
    dict(slug="auth-service", engine="MongoDB", db="auth-service", title="Tài khoản đăng nhập",
         tables={"authusers": dict(cols=[
             C("_id", "ObjectId", "PK"), C("email", "String", "UQ NN"), C("password", "String", "NN"),
             C("role", "enum buyer|seller|admin", "NN"), C("shopId", "String", "", "@shop-service.shops._id"),
             C("isActive", "Boolean"), C("tokenVersion", "Number"), *TS_MONGO],
             idx=["unique(email)"])},
         layout=[["authusers"]]),
    dict(slug="user-service", engine="MongoDB", db="user-service", title="Hồ sơ và sổ địa chỉ",
         tables={"userprofiles": dict(cols=[
             C("_id", "ObjectId", "PK"), C("userId", "String", "UQ NN", "@auth-service.authusers._id"),
             C("name", "String"), C("phone", "String"), C("address", "String"), *TS_MONGO,
             EMB("addresses[]", [C("_id", "ObjectId"), C("label", "String"), C("fullName", "String"),
                                 C("phone", "String"), C("line1", "String"), C("line2", "String"),
                                 C("city", "String"), C("state", "String"), C("postalCode", "String"),
                                 C("country", "String"), C("isDefault", "Boolean")])],
             idx=["unique(userId)"])},
         layout=[["userprofiles"]]),
    dict(slug="shop-service", engine="MongoDB", db="shop-service", title="Gian hàng",
         tables={"shops": dict(cols=[
             C("_id", "ObjectId", "PK"), C("name", "String", "NN"), C("ownerId", "String", "NN", "@auth-service.authusers._id"),
             C("description", "String"), C("invoiceEligible", "Boolean"), C("invoiceRequestMode", "enum", ""),
             C("legalEntityType", "enum"), C("taxCode", "String"), C("invoiceProvider", "String"),
             C("invoiceFeatureStatus", "enum"), *TS_MONGO,
             EMB("invoiceFeatureRequests[]", [C("requestedMode", "enum", "NN"), C("reason", "String"),
                                              C("status", "enum pending|approved|rejected"), C("adminNote", "String"),
                                              C("requestedBy", "String"), C("reviewedBy", "String"),
                                              C("requestedAt", "Date"), C("reviewedAt", "Date")])])},
         layout=[["shops"]]),
    dict(slug="product-service", engine="MongoDB", db="product-service", title="Danh mục và sản phẩm",
         tables={
             "categories": dict(cols=[C("_id", "ObjectId", "PK"), C("name", "String", "NN"), C("description", "String"),
                                      C("shopId", "String", "NN", "@shop-service.shops._id"), *TS_MONGO]),
             "productsalesevents": dict(cols=[C("_id", "ObjectId", "PK"), C("orderId", "String", "UQ NN", "@order-service.orders.id"),
                                              C("status", "enum", "IDX"), C("itemCount", "Number"), C("totalQuantity", "Number"),
                                              C("processedAt", "Date"), C("lastError", "String"), C("payload", "Mixed"), *TS_MONGO],
                                        idx=["unique(orderId)", "status"]),
             "products": dict(cols=[
                 C("_id", "ObjectId", "PK"), C("name", "String", "NN"), C("price", "Number", "NN"),
                 C("originalPrice", "Number"), C("description", "String"), C("detail", "String"),
                 C("images", "[String]"), C("quantity", "Number"), C("sold", "Number"),
                 C("categoryId", "String", "", "categories._id"), C("shopId", "String", "NN", "@shop-service.shops._id"),
                 C("moderationStatus", "enum", ""), C("moderatedBy", "String"), C("moderatedAt", "Date"),
                 C("moderationNote", "String"), C("strikeCount", "Number"), C("lastStrikeReason", "String"),
                 C("sourceProvider", "String"), C("sourceProductId", "String"), C("sourceUrl", "String"),
                 C("contentVersion", "String"), *TS_MONGO,
                 EMB("variants[]", [C("_id", "ObjectId"), C("name", "String", "NN"), C("sku", "String"),
                                    C("imageUrl", "String"), C("price", "Number", "NN"), C("originalPrice", "Number"),
                                    C("quantity", "Number")]),
                 EMB("specifications[]", [C("name", "String", "NN"), C("value", "String", "NN")])])},
         layout=[["categories", "productsalesevents"], ["products"]]),
    dict(slug="cart-service", engine="MongoDB", db="cart-service", title="Giỏ hàng",
         tables={"carts": dict(cols=[
             C("_id", "ObjectId", "PK"), C("userId", "String", "UQ NN", "@auth-service.authusers._id"), *TS_MONGO,
             EMB("products[]", [C("productId", "String", "NN", "@product-service.products._id"), C("variantId", "String"),
                                C("quantity", "Number", "NN")]),
             EMB("processedActions[]", [C("key", "String", "NN"), C("productId", "String", "NN"), C("variantId", "String"),
                                        C("quantity", "Number", "NN"), C("processedAt", "Date")])],
             idx=["unique(userId)"])},
         layout=[["carts"]]),
    dict(slug="review-service", engine="MongoDB", db="review-service", title="Đánh giá",
         tables={"reviews": dict(cols=[
             C("_id", "ObjectId", "PK"), C("productId", "String", "NN", "@product-service.products._id"),
             C("userId", "String", "NN", "@auth-service.authusers._id"), C("userName", "String"),
             C("rating", "Number 1..5", "NN"), C("comment", "String"), *TS_MONGO],
             idx=["unique(productId, userId)"])},
         layout=[["reviews"]]),
    dict(slug="chat-service", engine="MongoDB", db="chat-service", title="Trao đổi người mua – người bán",
         tables={
             "conversations": dict(cols=[C("_id", "String", "PK"), C("shopId", "String", "NN IDX", "@shop-service.shops._id"),
                                         C("buyerId", "String", "NN IDX", "@auth-service.authusers._id"),
                                         C("buyerName", "String"), C("product", "Object"), C("lastMessage", "String"),
                                         C("createdAt", "Date"), C("updatedAt", "Date")],
                                   idx=["shopId", "buyerId"]),
             "messages": dict(cols=[C("_id", "String", "PK"), C("conversationId", "String", "NN IDX", "conversations._id"),
                                    C("senderRole", "String", "NN"), C("senderId", "String"), C("text", "String", "NN"),
                                    C("createdAt", "Date")],
                              idx=["conversationId"])},
         layout=[["conversations"], ["messages"]]),
    dict(slug="order-service", engine="PostgreSQL", db="order_service", title="Đơn hàng, vận chuyển, khiếu nại",
         tables={
             "orders": dict(cols=[
                 C("id", "serial", "PK"), C("user_id", "varchar(64)", "NN", "@auth-service.authusers._id"),
                 C("products", "jsonb", "NN"), C("subtotal_price", "numeric(12,2)", "NN"),
                 C("discount_amount", "numeric(12,2)", "NN"), C("total_price", "numeric(12,2)", "NN"),
                 C("voucher_code", "varchar(40)", "", "@voucher-service.vouchers.code"), C("voucher_snapshot", "jsonb"),
                 C("invoice_request", "jsonb"), C("status", "varchar(40)", "NN"),
                 C("idempotency_key", "varchar(128)", "UQ"), C("idempotency_request_hash", "varchar(64)"),
                 C("shipping_address", "jsonb"), C("payment_method", "varchar(40)"),
                 C("shipment_tracking_code", "varchar(64)"), C("delivered_at", "timestamptz"),
                 C("settlement_status", "varchar(32)", "NN"), C("settlement_eligible_at", "timestamptz"),
                 C("settled_at", "timestamptz"), C("created_at", "timestamptz", "NN")]),
             "shipments": dict(cols=[
                 C("id", "serial", "PK"), C("order_id", "integer", "NN IDX", "orders.id"),
                 C("shop_id", "varchar(64)", "NN IDX", "@shop-service.shops._id"), C("tracking_code", "varchar(64)", "UQ NN"),
                 C("carrier", "varchar(80)", "NN"), C("status", "varchar(32)", "NN IDX"), C("callback_url", "varchar(240)"),
                 C("metadata", "jsonb", "NN"), C("handed_over_at", "timestamptz"), C("in_transit_at", "timestamptz"),
                 C("delivered_at", "timestamptz"), C("created_at", "timestamptz", "NN"), C("updated_at", "timestamptz", "NN")]),
             "disputes": dict(cols=[
                 C("id", "serial", "PK"), C("order_id", "integer", "NN", "orders.id"),
                 C("user_id", "varchar(64)", "NN", "@auth-service.authusers._id"), C("reason", "varchar(120)", "NN"),
                 C("note", "text"), C("evidence_text", "text"), C("status", "varchar(20)", "NN"),
                 C("handled_by", "varchar(64)"), C("handled_note", "text"), C("handled_at", "timestamptz"),
                 C("created_at", "timestamptz", "NN")]),
             "checkout_quotes": dict(cols=[
                 C("id", "uuid", "PK"), C("user_id", "varchar(64)", "NN", "@auth-service.authusers._id"),
                 C("session_id", "varchar(128)"), C("products", "jsonb", "NN"), C("shipping_address", "jsonb", "NN"),
                 C("payment_method", "varchar(40)", "NN"), C("voucher_code", "varchar(40)"),
                 C("subtotal_price", "numeric(12,2)", "NN"), C("total_price", "numeric(12,2)", "NN"),
                 C("confirmation_digest", "varchar(64)", "NN"), C("status", "varchar(24)", "NN"),
                 C("order_ids", "jsonb", "NN"), C("expires_at", "timestamptz", "NN"), C("created_at", "timestamptz", "NN")]),
             "inbox_events": dict(cols=INBOX)},
         layout=[["checkout_quotes", "inbox_events"], ["orders"], ["shipments", "disputes"]]),
    dict(slug="inventory-service", engine="PostgreSQL", db="inventory_service", title="Tồn kho",
         tables={
             "inventory": dict(cols=[
                 C("id", "serial", "PK"), C("product_id", "varchar(64)", "NN", "@product-service.products._id"),
                 C("variant_id", "varchar(64)", "NN"), C("shop_id", "varchar(64)", "", "@shop-service.shops._id"),
                 C("sku", "varchar(120)"), C("stock_on_hand", "integer", "NN"), C("reserved_stock", "integer", "NN"),
                 C("created_at", "timestamptz", "NN"), C("updated_at", "timestamptz", "NN")],
                 idx=["unique(product_id, variant_id)"]),
             "inventory_reservations": dict(cols=[
                 C("id", "serial", "PK"), C("order_id", "varchar(64)", "NN", "@order-service.orders.id"),
                 C("product_id", "varchar(64)", "NN", "inventory.product_id"), C("variant_id", "varchar(64)", "NN"),
                 C("quantity", "integer", "NN"), C("status", "varchar(24)", "NN"),
                 C("created_at", "timestamptz", "NN"), C("updated_at", "timestamptz", "NN")],
                 idx=["unique(order_id, product_id, variant_id)", "(order_id, status)"])},
         layout=[["inventory"], ["inventory_reservations"]]),
    dict(slug="voucher-service", engine="PostgreSQL", db="voucher_service", title="Voucher",
         tables={
             "vouchers": dict(cols=[
                 C("id", "serial", "PK"), C("code", "varchar(40)", "UQ NN"), C("name", "varchar(160)", "NN"),
                 C("type", "varchar(20)", "NN IDX"), C("shop_id", "varchar(64)", "IDX", "@shop-service.shops._id"),
                 C("discount_type", "varchar(20)", "NN"), C("discount_value", "numeric(10,2)", "NN"),
                 C("max_discount_amount", "numeric(12,2)"), C("min_order_amount", "numeric(12,2)", "NN"),
                 C("quantity", "integer", "NN"), C("used_count", "integer", "NN"),
                 C("usage_limit_per_user", "integer", "NN"), C("start_at", "timestamptz", "NN"),
                 C("end_at", "timestamptz", "NN"), C("status", "varchar(20)", "NN IDX"),
                 C("created_by", "varchar(64)"), C("created_by_role", "varchar(20)"),
                 C("created_at", "timestamptz", "NN"), C("updated_at", "timestamptz", "NN")]),
             "voucher_reservations": dict(cols=[
                 C("id", "serial", "PK"), C("voucher_id", "integer", "NN", "vouchers.id"),
                 C("order_id", "integer", "NN", "@order-service.orders.id"),
                 C("user_id", "varchar(64)", "NN IDX", "@auth-service.authusers._id"),
                 C("discount_amount", "numeric(12,2)", "NN"), C("status", "varchar(20)", "NN IDX"),
                 C("created_at", "timestamptz", "NN"), C("updated_at", "timestamptz", "NN")],
                 idx=["unique(voucher_id, order_id)"])},
         layout=[["vouchers"], ["voucher_reservations"]]),
    dict(slug="payment-service", engine="PostgreSQL", db="payment_service", title="Điều phối thanh toán (saga)",
         tables={"inbox_events": dict(cols=INBOX), "outbox_events": dict(cols=OUTBOX, idx=["(status, next_attempt_at)"])},
         layout=[["inbox_events"], ["outbox_events"]]),
    dict(slug="payment-gateway", engine="PostgreSQL", db="payment_gateway", title="Cổng SePay",
         tables={
             "sepay_payment_requests": dict(cols=[
                 C("id", "serial", "PK"), C("request_code", "varchar(80)", "UQ NN"), C("purpose", "varchar(32)", "NN"),
                 C("user_id", "varchar(64)", "NN", "@auth-service.authusers._id"),
                 C("order_id", "integer", "", "@order-service.orders.id"), C("amount", "numeric(14,2)", "NN"),
                 C("bank_code", "varchar(64)", "NN"), C("account_number", "varchar(64)", "NN"),
                 C("account_name", "varchar(128)"), C("qr_url", "text", "NN"), C("status", "varchar(20)", "NN"),
                 C("paid_at", "timestamptz"), C("expires_at", "timestamptz"), C("sepay_transaction_id", "varchar(64)"),
                 C("metadata", "jsonb", "NN"), *SAGA],
                 idx=["(purpose, order_id, status)", "(status, expires_at)"]),
             "sepay_webhook_logs": dict(cols=[
                 C("id", "serial", "PK"), C("sepay_transaction_id", "varchar(64)", "UQ NN"),
                 C("request_code", "varchar(80)", "", "sepay_payment_requests.request_code"),
                 C("transfer_type", "varchar(12)"), C("transfer_amount", "numeric(14,2)"), C("payload", "jsonb", "NN")]),
             "inbox_events": dict(cols=INBOX),
             "outbox_events": dict(cols=OUTBOX, idx=["(status, next_attempt_at)"])},
         layout=[["sepay_payment_requests", "inbox_events"], ["sepay_webhook_logs", "outbox_events"]]),
    dict(slug="wallet-service", engine="PostgreSQL", db="wallet_service", title="Ví, sổ cái kép, quyết toán",
         tables={
             "wallets": dict(cols=[C("id", "uuid", "PK"), C("user_id", "varchar(64)", "NN", "@auth-service.authusers._id"),
                                   C("currency", "varchar(8)", "NN"), C("status", "varchar(24)", "NN"),
                                   C("created_at", "timestamptz"), C("updated_at", "timestamptz")],
                             idx=["unique(user_id, currency)"]),
             "wallet_balances": dict(cols=[C("wallet_id", "uuid", "PK FK", "wallets.id"),
                                           C("available_balance", "numeric(14,2)", "NN"), C("locked_balance", "numeric(14,2)", "NN"),
                                           C("version", "integer", "NN"), C("updated_at", "timestamptz")]),
             "wallet_ledger_entries": dict(cols=[
                 C("id", "uuid", "PK"), C("wallet_id", "uuid", "FK NN", "wallets.id"), C("user_id", "varchar(64)", "NN"),
                 C("order_id", "integer", "", "@order-service.orders.id"), C("type", "varchar(40)", "NN"),
                 C("direction", "varchar(12)", "NN"), C("amount", "numeric(14,2)", "NN"), C("status", "varchar(24)", "NN"),
                 C("reason", "varchar(128)"), C("reference_id", "varchar(160)", "UQ NN"),
                 C("available_before", "numeric(14,2)", "NN"), C("available_after", "numeric(14,2)", "NN"),
                 C("locked_before", "numeric(14,2)", "NN"), C("locked_after", "numeric(14,2)", "NN"),
                 C("metadata", "jsonb", "NN"), *SAGA, C("created_at", "timestamptz")]),
             "accounts": dict(cols=[C("id", "uuid", "PK"), C("owner_type", "varchar(24)", "NN"), C("owner_id", "varchar(96)", "NN"),
                                    C("account_type", "varchar(40)", "NN"), C("currency", "varchar(8)", "NN"),
                                    C("status", "varchar(24)", "NN"), C("allow_negative", "boolean", "NN"),
                                    C("metadata", "jsonb", "NN"), C("created_at", "timestamptz"), C("updated_at", "timestamptz")],
                              idx=["unique(owner_type, owner_id, account_type, currency)"]),
             "account_balances": dict(cols=[C("account_id", "uuid", "PK FK", "accounts.id"),
                                            C("available_balance", "numeric(18,2)", "NN"), C("locked_balance", "numeric(18,2)", "NN"),
                                            C("version", "integer", "NN"), C("updated_at", "timestamptz")]),
             "ledger_transactions": dict(cols=[
                 C("id", "uuid", "PK"), C("reference_id", "varchar(180)", "UQ NN"), C("idempotency_key", "varchar(180)", "UQ"),
                 C("type", "varchar(48)", "NN"), C("status", "varchar(24)", "NN"), C("amount", "numeric(18,2)", "NN"),
                 C("debit_amount", "numeric(18,2)", "NN"), C("credit_amount", "numeric(18,2)", "NN"),
                 C("entry_count", "integer", "NN"), C("currency", "varchar(8)", "NN"), C("metadata", "jsonb", "NN"),
                 *SAGA, C("completed_at", "timestamptz"), C("failed_reason", "varchar(180)"),
                 C("created_at", "timestamptz"), C("updated_at", "timestamptz")]),
             "ledger_entries": dict(cols=[
                 C("id", "uuid", "PK"), C("transaction_id", "uuid", "FK NN", "ledger_transactions.id"),
                 C("account_id", "uuid", "FK NN", "accounts.id"), C("direction", "varchar(12)", "NN"),
                 C("amount", "numeric(18,2)", "NN"), C("currency", "varchar(8)", "NN"),
                 C("available_before", "numeric(18,2)", "NN"), C("available_after", "numeric(18,2)", "NN"),
                 C("locked_before", "numeric(18,2)", "NN"), C("locked_after", "numeric(18,2)", "NN"),
                 C("metadata", "jsonb", "NN"), C("created_at", "timestamptz")]),
             "payout_requests": dict(cols=[
                 C("id", "uuid", "PK"), C("shop_id", "varchar(96)", "NN", "@shop-service.shops._id"),
                 C("account_id", "uuid", "FK NN", "accounts.id"), C("amount", "numeric(18,2)", "NN"),
                 C("currency", "varchar(8)", "NN"), C("status", "varchar(24)", "NN"), C("reference_id", "varchar(180)", "UQ NN"),
                 C("bank_account_snapshot", "jsonb", "NN"), C("failure_reason", "varchar(180)"),
                 C("completed_at", "timestamptz"), C("metadata", "jsonb", "NN"), *SAGA,
                 C("created_at", "timestamptz"), C("updated_at", "timestamptz")]),
             "user_withdrawal_requests": dict(cols=[
                 C("id", "uuid", "PK"), C("user_id", "varchar(96)", "NN", "@auth-service.authusers._id"),
                 C("account_id", "uuid", "FK NN", "accounts.id"), C("amount", "numeric(18,2)", "NN"),
                 C("currency", "varchar(8)", "NN"), C("status", "varchar(24)", "NN"), C("reference_id", "varchar(180)", "UQ NN"),
                 C("bank_account_snapshot", "jsonb", "NN"), C("failure_reason", "varchar(180)"),
                 C("completed_at", "timestamptz"), C("metadata", "jsonb", "NN"), *SAGA]),
             "settlement_jobs": dict(cols=[
                 C("id", "uuid", "PK"), C("order_id", "integer", "NN IDX", "@order-service.orders.id"),
                 C("shop_id", "varchar(96)", "NN IDX", "@shop-service.shops._id"), C("amount", "numeric(18,2)", "NN"),
                 C("currency", "varchar(8)", "NN"), C("status", "varchar(24)", "NN"), C("eligible_at", "timestamptz", "NN"),
                 C("settled_at", "timestamptz"), C("reference_id", "varchar(180)", "UQ NN"), C("metadata", "jsonb", "NN"), *SAGA],
                 idx=["(status, eligible_at)"]),
             "inbox_events": dict(cols=INBOX),
             "outbox_events": dict(cols=OUTBOX, idx=["(status, next_attempt_at)"])},
         cascade={("wallet_balances", "wallet_id"), ("account_balances", "account_id"), ("ledger_entries", "transaction_id")},
         layout=[["wallets", "wallet_balances", "wallet_ledger_entries"],
                 ["accounts", "payout_requests", "user_withdrawal_requests"],
                 ["account_balances", "ledger_transactions", "ledger_entries"],
                 ["settlement_jobs", "inbox_events", "outbox_events"]]),
]
