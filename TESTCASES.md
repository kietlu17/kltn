# E2E Test Cases - Ecommerce Microservices

Ngay cap nhat: 2026-04-29  
Base URL (qua API Gateway): `http://localhost:3000`

## 1. Muc tieu
Tai lieu nay bao phu test thu cong end-to-end cho toan he thong:
1. Auth, phan quyen, buyer/seller/admin.
2. User profile, dia chi giao hang.
3. Shop, category, product moderation, product variants.
4. Cart, checkout, order lifecycle.
5. Payment mo phong, wallet, refund theo saga.
6. Review, chat, dispute.
7. Admin operations va inventory API.

## 2. Dieu kien truoc khi test
1. Chay `docker compose up -d --build`.
2. Tat ca service `Up` trong `docker compose ps`.
3. Co account admin seed bang env `ADMIN_EMAIL`, `ADMIN_PASSWORD`.
4. Neu dung Postgres volume cu, dam bao co DB `payment_service`.
5. Frontend chi goi API qua gateway port `3000`.

## 3. Du lieu test khuyen nghi
1. Buyer A: test mua hang chinh.
2. Buyer B: test phan quyen va review sai quyen.
3. Seller A: shop chinh, co san pham an toan va san pham bi gan co.
4. Seller B: shop khac de test loc theo shop.
5. Admin A: account quan tri.

## 4. Kich ban tong hop tu tao user den dat hang

### TC-E2E-001: Buyer dang ky va dang nhap
Precondition: chua co email buyer.  
Steps:
1. `POST /auth/register` voi role `buyer`.
2. `POST /auth/login` bang account vua tao.
Expected:
1. Register tra `201`.
2. Login tra `200` co `token` va `user.id`.

### TC-E2E-002: Seller dang ky va dang nhap
Precondition: chua co email seller.  
Steps:
1. `POST /auth/register` role `seller`, co `shopName`.
2. `POST /auth/login`.
Expected:
1. Register `201`.
2. Login `200`, `user.shopId` khac null.

### TC-E2E-003: Buyer them dia chi giao hang
Precondition: buyer da login.  
Steps:
1. `POST /users/:id/addresses`.
2. `PUT /users/:id/addresses/:addressId/default`.
Expected:
1. Them dia chi thanh cong.
2. Dia chi default duoc cap nhat.

### TC-E2E-004: Seller tao category
Precondition: seller da login.  
Steps:
1. `POST /categories` voi `name`, `shopId`.
2. `GET /categories`.
Expected:
1. Tao category thanh cong.
2. Category xuat hien trong danh sach.

### TC-E2E-005: Seller tao product co variants
Precondition: co category hop le cua shop seller.  
Steps:
1. `POST /products` (multipart), gui `variants` dang JSON.
2. `GET /products/:id`.
Expected:
1. Product tao thanh cong.
2. Co mang `variants`, gia tong phan anh min price cua variants.

### TC-E2E-006: Buyer xem product list
Precondition: co product da duoc duyet/auto-approve.  
Steps:
1. `GET /products`.
2. `GET /products/:id`.
Expected:
1. Buyer chi thay san pham `approved`.
2. Product detail hien thi variants dung.

### TC-E2E-007: Buyer them vao cart theo variant
Precondition: buyer login, product co variants.  
Steps:
1. `POST /cart/add` voi `productId`, `variantId`, `quantity`.
2. `GET /cart/:userId`.
Expected:
1. Add cart `201`.
2. Cart line tach theo `productId + variantId`.

### TC-E2E-008: Buyer checkout thanh cong
Precondition: cart co item con hang, co shipping address.  
Steps:
1. `POST /orders` voi `paymentMethod` (`cod` hoac `wallet` du tien).
2. `GET /orders/:userId`.
Expected:
1. Order tao `201`.
2. Order hien thi trong lich su user.

### TC-E2E-009: Buyer huy don va kiem tra hoan tien vi
Precondition: co order da paid hoac dang payment_processing phu hop refund rule.  
Steps:
1. `POST /orders/:id/cancel`.
2. `GET /payments/wallet/:userId`.
3. `GET /payments/wallet/:userId/transactions`.
Expected:
1. Order thanh `cancelled`.
2. Vi tang lai so tien hop le.
3. Co transaction `refund_order`, khong refund trung.

## 5. Auth va phan quyen

### TC-AUTH-001: Register thieu email/password
Expected: `400`.

### TC-AUTH-002: Register email trung
Expected: `409`.

### TC-AUTH-003: Register role admin truc tiep
Expected: `403`.

### TC-AUTH-004: Login sai password
Expected: `401`.

### TC-AUTH-005: Truy cap endpoint private khong token
Steps: `GET /cart/:userId`.  
Expected: `401`.

### TC-AUTH-006: Buyer goi admin endpoint
Steps: `GET /auth/admin/users`.  
Expected: `403`.

### TC-AUTH-007: Buyer truy cap orders cua user khac
Steps: `GET /orders/:otherUserId`.  
Expected: `403`.

### TC-AUTH-008: Buyer goi wallet cua user khac
Steps: `GET /payments/wallet/:otherUserId`.  
Expected: `403`.

## 6. User va dia chi

### TC-USER-001: Tao profile user
Steps: `POST /users`.  
Expected: `201`.

### TC-USER-002: Cap nhat ten user
Steps: `PUT /users/:id`.  
Expected: du lieu cap nhat dung.

### TC-USER-003: Them nhieu dia chi
Expected: list dia chi tra dung so luong.

### TC-USER-004: Doi default address
Expected: chi 1 dia chi `isDefault=true`.

### TC-USER-005: Xoa dia chi
Expected: dia chi bien mat khoi list.

## 7. Shop, category, product, moderation, variants

### TC-PROD-001: Seller tao product thieu `shopId` hoac `name`
Expected: `400`.

### TC-PROD-002: Seller tao product variant thieu truong bat buoc
Expected: `400` voi thong bao variant loi.

### TC-PROD-003: Tao product co keyword cam
Vi du ten chua `vu khi`, `hang gia`.  
Expected: `moderationStatus=pending`.

### TC-PROD-004: Tao product an toan
Expected: auto `approved`.

### TC-PROD-005: Buyer khong xem duoc product pending/rejected
Expected: `404` hoac khong thay trong list.

### TC-PROD-006: Seller cap nhat product co variants
Expected: `price=min(variant.price)`, `quantity=sum(variant.quantity)`.

### TC-PROD-007: Admin duyet product pending
Steps: `PATCH /products/admin/:id/moderate` action `approve`.  
Expected: status `approved`.

### TC-PROD-008: Admin reject/remove product
Expected: `strikeCount` tang, co `lastStrikeReason`.

### TC-PROD-009: Seller tao category sai `shopId`
Expected: loi validation.

### TC-PROD-010: Admin quan ly category toan he thong
Steps: `GET /categories/admin/all`, `PUT /categories/admin/:id`, `DELETE /categories/admin/:id`.  
Expected: thao tac thanh cong.

## 8. Cart va checkout

### TC-CART-001: Add cart cung product nhung khac variant
Expected: tao 2 line item khac nhau.

### TC-CART-002: Update quantity cart
Expected: quantity doi dung.

### TC-CART-003: Remove dung line theo variant
Expected: chi xoa line tuong ung.

### TC-CART-004: Checkout thieu shippingAddress
Expected: `400`.

### TC-CART-005: Checkout items tu nhieu shop trong mot order
Expected: `400` (moi order chi 1 shop).

### TC-CART-006: Checkout out-of-stock
Expected: `409` hoac thong bao het hang.

## 9. Payment, wallet, saga refund

### TC-PAY-001: Xem vi user
Steps: `GET /payments/wallet/:userId`.  
Expected: co object wallet, tu tao neu chua co.

### TC-PAY-002: Topup vi hop le
Steps: `POST /payments/wallet/:userId/topup`.  
Expected: balance tang, co transaction `topup`.

### TC-PAY-003: Topup amount <= 0
Expected: `400`.

### TC-PAY-004: Thanh toan vi du tien
Expected:
1. Order di qua `pending_payment -> paid`.
2. Vi tru tien dung.

### TC-PAY-005: Thanh toan vi khong du tien
Expected:
1. Payment fail `insufficient_wallet_balance`.
2. Order bi cancel theo saga.
3. Vi khong bi cong sai sau cancel.

### TC-PAY-006: Bank transfer pending roi success
Expected: trang thai tu `payment_processing -> paid`.

### TC-PAY-007: Bank transfer fail
Expected: order `payment_failed` roi `cancelled`, stock hoan.

### TC-PAY-008: Bank transfer timeout
Expected: order timeout duoc cancel, stock hoan, refund xu ly dung quy tac.

### TC-PAY-009: Huy tay don da thanh toan wallet
Expected: refund ve vi dung 1 lan.

### TC-PAY-010: Idempotency refund
Steps: goi huy nhieu lan cung order.  
Expected: chi co 1 transaction `refund_order` cho order do.

## 10. Order lifecycle buyer, seller, admin

### TC-ORD-001: Buyer lay list order cua minh
Expected: `GET /orders/:userId` tra dung du lieu.

### TC-ORD-002: Seller xem order theo shop
Expected: `GET /orders/seller/:shopId` chi gom item cua shop do.

### TC-ORD-003: Seller confirm khi order `paid`
Expected: status thanh `confirmed`.

### TC-ORD-004: Seller confirm khi order chua paid
Expected: `400`.

### TC-ORD-005: Buyer tao dispute
Steps: `POST /orders/:id/disputes`.  
Expected: dispute `open`.

### TC-ORD-006: Admin resolve/reject dispute
Steps: `PATCH /orders/admin/disputes/:id`.  
Expected: status doi `resolved` hoac `rejected`.

### TC-ORD-007: Admin force-cancel order
Expected: order `cancelled`, stock compensate, refund theo rule.

### TC-ORD-008: Admin update status thu cong
Steps: `PATCH /orders/admin/orders/:id/status`.  
Expected: chi nhan status hop le trong danh sach cho phep.

### TC-ORD-009: Seller stats theo thang
Steps: `GET /orders/seller/:shopId/stats?month=...&year=...`.  
Expected: tong orders/items/revenue dung.

## 11. Review

### TC-REV-001: Buyer review san pham da mua
Expected: `201`.

### TC-REV-002: Buyer review san pham chua mua
Expected: `403`.

### TC-REV-003: Buyer review trung product
Expected: `409`.

### TC-REV-004: Rating ngoai khoang 1-5
Expected: `400`.

### TC-REV-005: Lay danh sach review theo product
Expected: `GET /reviews/product/:productId` tra dung.

## 12. Chat

### TC-CHAT-001: Tao conversation buyer-shop
Expected: tra ve `conversationId`.

### TC-CHAT-002: Gui tin nhan trong conversation
Expected: `201`, conversation cap nhat `lastMessage`.

### TC-CHAT-003: Buyer xem conversation cua minh
Endpoint: `GET /chat/buyers/:buyerId/conversations`.  
Expected: dung list.

### TC-CHAT-004: Seller xem conversation theo shop
Endpoint: `GET /chat/shops/:shopId/conversations`.  
Expected: dung list.

### TC-CHAT-005: AI respond khi chua cau hinh key
Endpoint: `POST /chat/ai/respond`.  
Expected: `501`.

## 13. Admin quan tri user

### TC-ADM-001: Admin list users
Expected: co buyer/seller/admin accounts.

### TC-ADM-002: Admin lock buyer/seller
Expected: account bi khoa, login fail.

### TC-ADM-003: Admin unlock user
Expected: login hoat dong lai.

### TC-ADM-004: Khong lock duoc admin account
Expected: bi chan theo rule.

## 14. Inventory service (API truc tiep)
Luu y: inventory khong duoc expose qua gateway trong luong buyer/seller, test bang service URL noi bo hoac port map rieng khi can.

### TC-INV-001: Lay ton kho theo product
Endpoint: `GET /inventory/:productId` (service inventory).  
Expected: tra ton kho hien tai.

### TC-INV-002: Cap nhat ton kho
Endpoint: `PUT /inventory/:productId`.  
Expected: cap nhat thanh cong va doc lai dung.

## 15. Kiem tra ha tang va bao mat nhanh

### TC-INF-001: Frontend chi goi gateway
Expected: khong goi truc tiep service ports khac.

### TC-INF-002: mTLS giua services
Expected: service-to-service call OK khi cert dung, fail khi cert sai.

### TC-INF-003: Rate limit o gateway
Expected: spam login hoac request vuot nguong tra `429`.

### TC-INF-004: Restart service giua luong
Expected: he thong recover, khong refund trung, khong tru kho sai.

## 16. Checklist ket qua cuoi phien test
1. Tong so test case da chay.
2. So luong Pass/Fail.
3. Defect theo muc do (Critical/High/Medium/Low).
4. Endpoint/log lien quan moi defect.
5. Quyet dinh release: Go hoac No-Go.

## 17. Postman guide + request body mau

### 17.1 Tao Postman Environment
Tao 1 environment, them cac bien:
1. `baseUrl` = `http://localhost:3000`
2. `buyerEmail` = `buyer_xxx@demo.com`
3. `buyerPassword` = `123456`
4. `sellerEmail` = `seller_xxx@demo.com`
5. `sellerPassword` = `123456`
6. `adminEmail` = `<ADMIN_EMAIL>`
7. `adminPassword` = `<ADMIN_PASSWORD>`
8. `buyerToken` = ``
9. `sellerToken` = ``
10. `adminToken` = ``
11. `buyerId` = ``
12. `sellerShopId` = ``
13. `productId` = ``
14. `variantId` = ``
15. `orderId` = ``
16. `addressId` = ``
17. `categoryId` = ``

### 17.2 Header chung
1. Request can auth: `Authorization: Bearer {{buyerToken}}` hoac `{{sellerToken}}` hoac `{{adminToken}}`
2. JSON request: `Content-Type: application/json`
3. Order idempotency: `Idempotency-Key: order-{{buyerId}}-001`

### 17.3 Auth requests

#### Register buyer
Method: `POST`  
URL: `{{baseUrl}}/auth/register`  
Body:
```json
{
  "email": "{{buyerEmail}}",
  "password": "{{buyerPassword}}",
  "role": "buyer",
  "name": "Buyer Demo"
}
```

#### Login buyer
Method: `POST`  
URL: `{{baseUrl}}/auth/login`  
Body:
```json
{
  "email": "{{buyerEmail}}",
  "password": "{{buyerPassword}}"
}
```
Tests tab script:
```javascript
const data = pm.response.json();
pm.environment.set("buyerToken", data.token);
pm.environment.set("buyerId", data.user.id);
```

#### Register seller
Method: `POST`  
URL: `{{baseUrl}}/auth/register`  
Body:
```json
{
  "email": "{{sellerEmail}}",
  "password": "{{sellerPassword}}",
  "role": "seller",
  "shopName": "Shop Demo"
}
```

#### Login seller
Method: `POST`  
URL: `{{baseUrl}}/auth/login`  
Body:
```json
{
  "email": "{{sellerEmail}}",
  "password": "{{sellerPassword}}"
}
```
Tests tab script:
```javascript
const data = pm.response.json();
pm.environment.set("sellerToken", data.token);
pm.environment.set("sellerShopId", data.user.shopId);
```

#### Login admin
Method: `POST`  
URL: `{{baseUrl}}/auth/login`  
Body:
```json
{
  "email": "{{adminEmail}}",
  "password": "{{adminPassword}}"
}
```
Tests tab script:
```javascript
const data = pm.response.json();
pm.environment.set("adminToken", data.token);
```

### 17.4 User + address

#### Add address
Method: `POST`  
URL: `{{baseUrl}}/users/{{buyerId}}/addresses`  
Auth: buyer token  
Body:
```json
{
  "label": "Home",
  "line1": "123 Test Street",
  "city": "HCM",
  "country": "VN",
  "isDefault": true
}
```
Tests tab script:
```javascript
const data = pm.response.json();
pm.environment.set("addressId", data._id || data.id);
```

#### Set default address
Method: `PUT`  
URL: `{{baseUrl}}/users/{{buyerId}}/addresses/{{addressId}}/default`  
Auth: buyer token  
Body: none

### 17.5 Category + product variants

#### Create category
Method: `POST`  
URL: `{{baseUrl}}/categories`  
Auth: seller token  
Body:
```json
{
  "name": "Sneakers",
  "description": "Shoes category",
  "shopId": "{{sellerShopId}}"
}
```
Tests tab script:
```javascript
const data = pm.response.json();
pm.environment.set("categoryId", data._id || data.id);
```

#### Create product (JSON)
Method: `POST`  
URL: `{{baseUrl}}/products`  
Auth: seller token  
Body:
```json
{
  "name": "Running Shoes",
  "description": "Comfort shoes",
  "detail": "Safe product",
  "shopId": "{{sellerShopId}}",
  "categoryId": "{{categoryId}}",
  "variants": [
    { "name": "Size 41", "sku": "RUN-41", "price": 120, "quantity": 10 },
    { "name": "Size 42", "sku": "RUN-42", "price": 125, "quantity": 5 }
  ]
}
```
Tests tab script:
```javascript
const data = pm.response.json();
pm.environment.set("productId", data._id || data.id);
if (data.variants && data.variants.length) {
  pm.environment.set("variantId", data.variants[0]._id);
}
```

### 17.6 Cart + order + idempotency

#### Add to cart
Method: `POST`  
URL: `{{baseUrl}}/cart/add`  
Auth: buyer token  
Body:
```json
{
  "userId": "{{buyerId}}",
  "productId": "{{productId}}",
  "variantId": "{{variantId}}",
  "quantity": 1
}
```

#### Topup wallet
Method: `POST`  
URL: `{{baseUrl}}/payments/wallet/{{buyerId}}/topup`  
Auth: buyer token  
Body:
```json
{
  "amount": 300,
  "source": "postman"
}
```

#### Create order with idempotency key
Method: `POST`  
URL: `{{baseUrl}}/orders`  
Auth: buyer token  
Headers:
1. `Idempotency-Key: order-{{buyerId}}-001`
Body:
```json
{
  "userId": "{{buyerId}}",
  "paymentMethod": "wallet",
  "shippingAddress": {
    "label": "Home",
    "line1": "123 Test Street",
    "city": "HCM",
    "country": "VN"
  },
  "products": [
    {
      "productId": "{{productId}}",
      "variantId": "{{variantId}}",
      "variantName": "Size 41",
      "quantity": 1,
      "price": 120,
      "shopId": "{{sellerShopId}}",
      "productName": "Running Shoes"
    }
  ]
}
```
Tests tab script:
```javascript
const data = pm.response.json();
pm.environment.set("orderId", data.id);
```

#### Duplicate order request test
1. Gui lai request `POST /orders` y chang body + y chang `Idempotency-Key`.
2. Ky vong: tra cung `orderId` (200/201), khong tao order moi.

#### Idempotency conflict test
1. Van giu `Idempotency-Key` cu.
2. Doi body (vi du `quantity` tu 1 -> 2).
3. Ky vong: `409`.

#### Cancel order
Method: `POST`  
URL: `{{baseUrl}}/orders/{{orderId}}/cancel`  
Auth: buyer token  
Body: none

### 17.7 Wallet and refund check

#### Get wallet
Method: `GET`  
URL: `{{baseUrl}}/payments/wallet/{{buyerId}}`  
Auth: buyer token

#### Get wallet transactions
Method: `GET`  
URL: `{{baseUrl}}/payments/wallet/{{buyerId}}/transactions?limit=20`  
Auth: buyer token

Ky vong sau cancel:
1. Co transaction `refund_order`.
2. Khong co 2 transaction refund cho cung 1 `order_id`.

### 17.8 Review, chat, dispute body mau

#### Create review
Method: `POST`  
URL: `{{baseUrl}}/reviews/product/{{productId}}`  
Auth: buyer token  
Body:
```json
{
  "userId": "{{buyerId}}",
  "userName": "Buyer Demo",
  "rating": 5,
  "comment": "Good product"
}
```

#### Create conversation
Method: `POST`  
URL: `{{baseUrl}}/chat/conversations`  
Auth: buyer token  
Body:
```json
{
  "shopId": "{{sellerShopId}}",
  "buyerId": "{{buyerId}}",
  "buyerName": "Buyer Demo",
  "product": {
    "id": "{{productId}}",
    "name": "Running Shoes"
  }
}
```

#### Create dispute
Method: `POST`  
URL: `{{baseUrl}}/orders/{{orderId}}/disputes`  
Auth: buyer token  
Body:
```json
{
  "reason": "wrong_item",
  "note": "Item is not correct",
  "evidenceText": "Package photo and label mismatch"
}
```

### 17.9 Admin moderation and operations body mau

#### Approve pending product
Method: `PATCH`  
URL: `{{baseUrl}}/products/admin/{{productId}}/moderate`  
Auth: admin token  
Body:
```json
{
  "action": "approve",
  "note": "Approved by admin"
}
```

#### Reject pending product
Method: `PATCH`  
URL: `{{baseUrl}}/products/admin/{{productId}}/moderate`  
Auth: admin token  
Body:
```json
{
  "action": "reject",
  "note": "Restricted keywords"
}
```

#### Force cancel order
Method: `POST`  
URL: `{{baseUrl}}/orders/admin/orders/{{orderId}}/force-cancel`  
Auth: admin token  
Body: none

#### Update order status
Method: `PATCH`  
URL: `{{baseUrl}}/orders/admin/orders/{{orderId}}/status`  
Auth: admin token  
Body:
```json
{
  "status": "shipped"
}
```
