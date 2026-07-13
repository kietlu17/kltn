# Payment, Wallet, Payment Gateway, Saga, Outbox

Tai lieu nay giai thich thiet ke hien tai sau khi tach Wallet Service va Payment Gateway khoi Payment Service. Trong he thong nay, thanh toan khong con la mot khoi logic duy nhat. Thay vao do moi service giu mot bounded context rieng, giao tiep voi nhau bang domain events thong qua Kafka, va dung Outbox/Inbox de giam rui ro mat event hoac consume lap.

## Tong Quan Vai Tro

He thong hien co 3 bounded context chinh lien quan den thanh toan:

| Service | Vai tro hien tai | Khong nen lam |
| --- | --- | --- |
| `payment-service` | Dieu phoi saga thanh toan. Nhan `order.created`, `order.cancelled`, `wallet.*`, `qr.payment.*`, sau do phat `payment.pending`, `payment.succeeded`, `payment.failed`, `payment.timeout`, `payment.refunded`. | Khong giu tien vi, khong tao QR, khong xu ly webhook ngan hang. |
| `wallet-service` | Quan ly vi nguoi dung, ledger bat bien, balance projection, debit/refund/topup, consume lenh debit/refund/topup va publish wallet domain events. | Khong quyet dinh trang thai order, khong verify webhook SePay. |
| `payment-gateway` | Quan ly request QR SePay, tao QR, verify webhook, expire request, publish `qr.payment.succeeded`, `qr.payment.failed`, `qr.payment.expired`. | Khong cap nhat order, khong cong/tru tien vi truc tiep. |

He thong Order Service van la owner cua aggregate `Order`. No consume `payment.*` events de cap nhat status order va kich hoat compensation nhu huy order, hoan stock, yeu cau refund.

## Phan Tich Theo DDD

### Payment Context

`payment-service` la Saga/Application Service, khong phai noi giu tien. Domain cua no la "Payment Saga" - tuc la dieu phoi cac buoc thanh toan bat dong bo.

Thanh phan chinh:

| Thanh phan | Y nghia |
| --- | --- |
| Saga/process manager | Theo doi va dieu phoi luong thanh toan dua tren event. |
| Domain events | `payment.pending`, `payment.succeeded`, `payment.failed`, `payment.timeout`, `payment.refunded`. |
| Commands/events gui sang bounded context khac | `wallet.debit.requested`, `wallet.refund.requested`. |
| Outbox | Dam bao viec publish event ra Kafka sau khi state local duoc commit. |
| Inbox | Dam bao moi Kafka message chi duoc xu ly logic mot lan theo `message_id`. |

`payment-service` khong nen biet chi tiet bang vi, balance, ledger hay cau truc webhook ngan hang. No chi nhin thay cac ket qua business: wallet debited, wallet debit failed, QR payment succeeded, QR payment failed, QR expired.

### Wallet Context

`wallet-service` la owner cua Wallet Aggregate. No nam giu quy tac bat bien ve tien:

- So tien debit phai lon hon 0.
- Khong cho debit neu available balance khong du.
- Moi thay doi so du phai co ledger entry.
- Debit/refund/topup phai idempotent bang `reference_id`.
- Balance hien tai la projection tu ledger, khong phai su that duy nhat.

Aggregate chinh:

| Aggregate/Entity | Vai tro |
| --- | --- |
| `Wallet` | Identity cua vi theo `user_id + currency`. |
| `WalletBalance` | Projection hien tai: available balance, locked balance, version. |
| `WalletLedgerEntry` | Ledger bat bien ghi lai moi nghiep vu credit/debit/refund/failed debit. |
| `InboxEvent` | Chong consume lap event tu Kafka. |
| `OutboxEvent` | Luu event can publish cung transaction voi ledger/balance. |

Domain events wallet:

| Event | Khi nao phat |
| --- | --- |
| `wallet.credited` | Khi topup/credit thanh cong. |
| `wallet.debited` | Khi debit order thanh cong. |
| `wallet.debit_failed` | Khi debit that bai, vi du khong du tien. |
| `wallet.refunded` | Khi refund order thanh cong. |
| `wallet.external_payment_recorded` | Khi ghi nhan order da thanh toan bang kenh ngoai nhu QR/bank transfer. |

### Payment Gateway Context

`payment-gateway` la bounded context cho external payment provider. Hien tai provider la SePay QR.

No quan ly:

- Tao payment request.
- Tao QR URL.
- Verify API key webhook.
- Match webhook voi request code.
- Check amount.
- Mark request paid/failed/expired.
- Phat QR payment events.

No khong cap nhat order va khong cong tien vao vi truc tiep. Viec do thuoc ve wallet/payment saga.

Domain events gateway:

| Event | Topic | Y nghia |
| --- | --- | --- |
| `QRPaymentSucceeded` | `qr.payment.succeeded` | QR da duoc thanh toan hop le. |
| `QRPaymentFailed` | `qr.payment.failed` | QR fail, vi du transfer amount khong du. |
| `QRPaymentExpired` | `qr.payment.expired` | QR qua han thanh toan. |

## Cau Truc Bang Wallet Service

### `wallets`

Bang nay dinh danh vi cua user.

| Cot | Y nghia |
| --- | --- |
| `id` | UUID cua wallet. |
| `user_id` | User owner cua vi. |
| `currency` | Don vi tien, mac dinh `VND`. |
| `status` | Trang thai vi, mac dinh `active`. |
| `created_at`, `updated_at` | Audit timestamps. |

Rang buoc quan trong:

- Unique theo `user_id + currency`.
- Mot user co the co nhieu vi neu sau nay ho tro nhieu currency.

### `wallet_balances`

Bang projection so du hien tai cua wallet.

| Cot | Y nghia |
| --- | --- |
| `wallet_id` | Primary key, tham chieu `wallets.id`. |
| `available_balance` | So du co the su dung. |
| `locked_balance` | So du dang bi hold/reserve. Hien tai chua dung nhieu, nhung de san cho hold/capture. |
| `version` | Version tang moi lan balance thay doi. |
| `updated_at` | Thoi diem projection duoc update. |

Bang nay duoc update trong cung transaction voi ledger entry. Trong hien tai, balance projection giup doc nhanh, con ledger moi la audit trail quan trong.

### `wallet_ledger_entries`

Bang ledger bat bien cho tat ca giao dich vi.

| Cot | Y nghia |
| --- | --- |
| `id` | UUID cua ledger entry. |
| `wallet_id` | Wallet lien quan. |
| `user_id` | User owner, duplicate co chu y de query nhanh. |
| `order_id` | Order lien quan neu co. |
| `type` | Loai giao dich: `topup`, `debit_order`, `refund_order`, `external_payment_order`, ... |
| `direction` | `credit`, `debit`, hoac `none`. |
| `amount` | So tien cua giao dich. |
| `status` | `completed` hoac `failed`. |
| `reason` | Ly do business: `order_payment`, `insufficient_wallet_balance`, `order_cancelled`, ... |
| `reference_id` | Idempotency key duy nhat. |
| `available_before`, `available_after` | Snapshot available balance truoc/sau. |
| `locked_before`, `locked_after` | Snapshot locked balance truoc/sau. |
| `metadata` | Du lieu bo sung nhu source, request code, gateway transaction id. |
| `saga_id` | Saga id de trace. |
| `correlation_id` | Correlation id de trace end-to-end. |
| `created_at` | Thoi diem tao entry. |

Rang buoc quan trong:

- `reference_id` unique.
- Moi nghiep vu co key on dinh:
  - Debit order: `order:{orderId}:debit`
  - Refund order: `order:{orderId}:refund`
  - External payment: `order:{orderId}:external_payment`
  - QR wallet topup: `qr:wallet:{requestCode/requestId}`

Nho `reference_id`, neu Kafka redeliver message hoac API retry, wallet-service tra ve ket qua cu thay vi tru/tang tien lan nua.

### `inbox_events`

Bang nay chong consume lap message tu Kafka.

| Cot | Y nghia |
| --- | --- |
| `message_id` | Dinh danh message. Lay tu `eventId`, `idempotencyKey`, hoac fallback `topic:partition:offset`. |
| `topic` | Topic Kafka. |
| `payload` | Payload da nhan. |
| `status` | `processing`, `processed`, `failed`. |
| `attempts` | So lan xu ly. |
| `error` | Loi gan nhat neu fail. |
| `processed_at` | Thoi diem xu ly xong. |

Neu message cu da `processed`, consumer skip. Neu message fail, Kafka co the retry va row inbox ghi lai attempts/error.

### `outbox_events`

Bang nay dam bao event khong bi mat khi transaction DB da commit nhung Kafka publish bi loi.

| Cot | Y nghia |
| --- | --- |
| `id` | UUID event outbox. |
| `aggregate_type` | Loai aggregate, vi du `wallet`, `payment_saga`, `sepay_payment_request`. |
| `aggregate_id` | Id aggregate. |
| `event_type` | Ten event domain, vi du `WalletDebited`. |
| `topic` | Kafka topic can publish. |
| `event_key` | Kafka key. |
| `payload` | Noi dung event. |
| `headers` | Header logical, gom saga/correlation. |
| `status` | `pending`, `published`, `failed`. |
| `attempts` | So lan publish. |
| `next_attempt_at` | Thoi diem retry tiep theo. |
| `published_at` | Thoi diem publish thanh cong. |
| `error` | Loi gan nhat. |
| `saga_id`, `correlation_id` | Trace ids. |

Producer nen ghi outbox trong cung DB transaction voi thay doi domain. Background publisher doc outbox va gui Kafka. Neu Kafka fail, outbox row van con va retry sau.

## Luong Saga Chinh

### 1. Thanh Toan Bang Vi

Muc tieu: user dat hang va thanh toan bang wallet.

Luon xu ly:

1. `order-service` tao order, tru stock, publish `order.created`.
2. `payment-service` consume `order.created`.
3. Neu `paymentMethod = wallet`, `payment-service` ghi outbox event `wallet.debit.requested`.
4. Outbox publisher cua `payment-service` publish `wallet.debit.requested`.
5. `wallet-service` consume event qua inbox.
6. `wallet-service` bat dau DB transaction:
   - Lock wallet/balance.
   - Check idempotency bang `reference_id = order:{orderId}:debit`.
   - Neu du tien: tru `available_balance`.
   - Tao `wallet_ledger_entries` loai `debit_order`.
   - Tao outbox event `wallet.debited`.
   - Commit transaction.
7. Outbox publisher cua `wallet-service` publish `wallet.debited`.
8. `payment-service` consume `wallet.debited`.
9. `payment-service` ghi outbox event `payment.succeeded`.
10. `order-service` consume `payment.succeeded` va update order status thanh `paid`.

Neu vi khong du tien:

1. `wallet-service` tao ledger entry `debit_order` voi `status = failed`, reason `insufficient_wallet_balance`.
2. `wallet-service` publish `wallet.debit_failed`.
3. `payment-service` publish `payment.failed`.
4. `order-service` update order thanh `payment_failed`, cancel order va compensate stock.

### 2. Refund Khi Huy Don

Muc tieu: order da thanh toan bi huy va can refund ve wallet.

Luon xu ly:

1. `order-service` cancel order va publish `order.cancelled`.
2. Payload co `shouldRefundToWallet = true` neu order du dieu kien refund.
3. `payment-service` consume `order.cancelled`.
4. `payment-service` publish command `wallet.refund.requested` qua outbox.
5. `wallet-service` consume command qua inbox.
6. `wallet-service` DB transaction:
   - Check `reference_id = order:{orderId}:refund`.
   - Check da co debit/external payment truoc do, tru khi `allowWithoutDebit = true`.
   - Cong lai `available_balance`.
   - Tao ledger entry `refund_order`.
   - Tao outbox event `wallet.refunded`.
   - Commit.
7. `payment-service` consume `wallet.refunded`.
8. `payment-service` publish `payment.refunded`.

Ghi chu: voi `bank_transfer`, refund request hien cho phep `allowWithoutDebit = true` de tranh race khi order da paid nhung wallet-service chua kip ghi external payment ledger tu QR event.

### 3. Thanh Toan QR Cho Order

Muc tieu: user chon bank transfer/SePay QR.

Luon xu ly:

1. `order-service` tao order va publish `order.created`.
2. `payment-service` consume `order.created`.
3. Neu `paymentMethod = bank_transfer`, publish `payment.pending`.
4. Frontend goi API tao QR.
5. API gateway route `/payments/sepay/...` sang `payment-gateway`.
6. `payment-gateway` tao row `sepay_payment_requests` status `pending`, co `expires_at`.
7. User chuyen khoan.
8. SePay goi webhook.
9. `payment-gateway` verify API key, match request code, check amount.
10. Neu hop le:
    - Mark request `paid`.
    - Tao outbox event `qr.payment.succeeded`.
11. `wallet-service` consume `qr.payment.succeeded`:
    - Neu purpose `order_payment`, ghi ledger `external_payment_order`.
12. `payment-service` consume `qr.payment.succeeded`:
    - Publish `payment.succeeded`.
13. `order-service` consume `payment.succeeded`:
    - Update order status thanh `paid`.

Neu amount khong du:

1. `payment-gateway` mark request `failed`.
2. Publish `qr.payment.failed`.
3. `payment-service` publish `payment.failed`.
4. `order-service` cancel order va compensate stock.

Neu het han:

1. `payment-gateway` expiry worker mark request `expired`.
2. Publish `qr.payment.expired`.
3. `payment-service` publish `payment.timeout`.
4. `order-service` cancel order va compensate stock.

Ngoai ra `payment-service` cung co order-level timeout cho bank transfer de tranh order ket o `payment_processing` neu user khong tao QR hoac QR service khong tao duoc request.

### 4. QR Topup Wallet

Muc tieu: user nap tien vao vi bang QR.

Luon xu ly:

1. Frontend goi `/payments/wallet/:userId/topup/sepay-qr`.
2. API gateway route request nay sang `payment-gateway`.
3. `payment-gateway` tao `sepay_payment_requests` purpose `wallet_topup`.
4. SePay webhook den.
5. `payment-gateway` verify webhook va publish `qr.payment.succeeded`.
6. `wallet-service` consume event.
7. Neu purpose `wallet_topup`, wallet-service:
   - Check idempotency `qr:wallet:{requestCode/requestId}`.
   - Cong balance.
   - Tao ledger `topup`.
   - Publish `wallet.credited`.

Payment-service khong can tham gia luong topup wallet, vi day la nghiep vu noi bo cua wallet context sau khi gateway da xac nhan payment thanh cong.

## Outbox Hoat Dong Nhu The Nao

Transactional Outbox giai quyet bai toan: "DB commit thanh cong nhung Kafka publish fail thi sao?"

Khong dung outbox:

1. Service update DB.
2. Service publish Kafka.
3. Neu DB commit xong nhung Kafka fail, he thong mat event.

Dung outbox:

1. Service bat dau DB transaction.
2. Service update bang domain.
3. Service insert row `outbox_events`.
4. Commit DB transaction.
5. Background worker doc `outbox_events status = pending`.
6. Publish Kafka.
7. Neu thanh cong, mark `published`.
8. Neu fail, mark `failed`, tang `attempts`, set `next_attempt_at`.

Ket qua:

- Domain state va event intent duoc commit atomic trong cung DB.
- Kafka co the fail tam thoi ma khong mat event.
- Retry co state ro rang trong DB.

## Inbox Hoat Dong Nhu The Nao

Inbox giai quyet bai toan: "Kafka co the deliver lai message, consume hai lan thi sao?"

Moi consumer lam:

1. Parse payload.
2. Tao `message_id` tu `eventId`, `idempotencyKey`, hoac `topic:partition:offset`.
3. `findOrCreate` row trong `inbox_events`.
4. Neu row da `processed`, skip.
5. Neu chua processed, xu ly business logic.
6. Thanh cong thi mark `processed`.
7. Loi thi mark `failed`, ghi `error`, tang `attempts`, throw lai de Kafka retry.

Inbox khong thay the idempotency domain. No ngan logic consume lap o muc message. Wallet van can `reference_id` unique de dam bao khong tru/cong tien lap neu command duplicate nhung co message id khac.

## Dam Bao ACID Trong He Thong

Can tach ro 2 cap do:

1. ACID cuc bo trong tung service.
2. Tinh nhat quan toan he thong giua nhieu service.

Trong microservices, khong nen co distributed transaction 2PC giua Order, Payment, Wallet, Gateway. He thong nay dung Saga + Outbox/Inbox nen tinh nhat quan lien service la eventual consistency.

### ACID Cuc Bo

Moi service co database rieng va transaction rieng:

- Wallet Service dam bao ACID cho thay doi balance/ledger/outbox.
- Payment Service dam bao ACID cho inbox/outbox saga.
- Payment Gateway dam bao ACID cho request QR/webhook log/outbox.
- Order Service dam bao ACID cho order state/inbox.

### Khong Co ACID Phan Tan

Vi du thanh toan bang vi cham 4 service:

- Order tao order.
- Payment yeu cau debit wallet.
- Wallet tru tien.
- Order update paid.

Tat ca khong nam trong mot database transaction duy nhat. Neu buoc sau fail, saga se retry hoac compensation. Vi vay he thong khong co distributed ACID, ma co:

- Local ACID.
- Durable events.
- Idempotent consumers.
- Compensation.
- Eventual consistency.

## Cau Hoi: ACID Trong Wallet Service Duoc Dam Bao Nhu The Nao?

Wallet Service la noi can ACID manh nhat vi no quan ly tien. Hien tai ACID trong wallet-service duoc dam bao o muc local transaction PostgreSQL/Sequelize.

### Atomicity

Moi nghiep vu thay doi tien chay trong `sequelize.transaction`.

Vi du debit order:

1. Check idempotency.
2. Lock wallet/balance.
3. Check available balance.
4. Update `wallet_balances`.
5. Insert `wallet_ledger_entries`.
6. Insert `outbox_events`.
7. Commit.

Neu bat ky buoc nao loi, transaction rollback. Khi rollback:

- Balance khong bi tru.
- Ledger khong duoc tao.
- Outbox event khong duoc tao.

Do do khong co trang thai nua voi: "balance da tru nhung ledger/outbox chua co".

### Consistency

Wallet service giu cac invariant:

- Amount phai > 0.
- Khong debit neu `available_balance < amount`.
- Moi giao dich tien phai co ledger entry.
- `reference_id` unique ngan duplicate business operation.
- `available_after`/`available_before` ghi lai snapshot de audit.
- Refund khong lap do `order:{orderId}:refund` unique.
- Debit order khong lap do `order:{orderId}:debit` unique.

Sau transaction thanh cong, balance projection va ledger phai khop voi operation vua lam.

### Isolation

Khi doc wallet/balance trong transaction, code dung lock update:

- `Wallet.findOne(... lock: transaction.LOCK.UPDATE)`
- `WalletBalance.findOne(... lock: transaction.LOCK.UPDATE)`

Muc dich la tranh 2 debit dong thoi cung doc mot balance cu va cung tru tien.

Vi du wallet co 100k, hai order cung debit 80k:

- Transaction A lock balance, tru con 20k, commit.
- Transaction B phai doi lock.
- Sau khi B doc lai balance con 20k, B fail `insufficient_wallet_balance`.

Neu khong co row lock, ca hai transaction co the cung thay 100k va cung debit thanh cong, gay am tien.

### Durability

Sau khi transaction commit vao PostgreSQL:

- Balance da update se ton tai.
- Ledger da ton tai.
- Outbox event da ton tai.

Neu service crash ngay sau commit nhung truoc khi publish Kafka, background outbox publisher se doc lai event pending va publish tiep. Day la diem quan trong giup durability cua "intent to publish".

## Dieu ACID Khong Dam Bao

Wallet Service chi dam bao ACID trong DB cua no. No khong dam bao:

- Order va wallet cung commit atomic.
- Kafka publish thanh cong cung luc DB commit.
- Payment Gateway request va Wallet ledger cung nam trong mot transaction.

Nhung cac khoang trong do duoc bu bang:

- Outbox retry.
- Inbox idempotency.
- Domain idempotency key.
- Saga compensation.
- Order-level timeout.
- Logging theo `sagaId` va `correlationId`.

## Rui Ro Va Diem Can Nang Cap Tiep

Thiet ke hien tai da co nen tang dung, nhung neu dua vao production can nang cap them:

1. Migration thay vi `sequelize.sync()`.
2. Index/constraint ro hon cho ledger va inbox/outbox.
3. Worker outbox rieng hoac co distributed lock de tranh nhieu instance publish cung row.
4. Retry policy co dead-letter topic.
5. Monitoring dashboard cho outbox failed/inbox failed.
6. Reconciliation job so sanh gateway payment request, wallet ledger, payment saga, order status.
7. Double-entry ledger neu muon mo rong sang fintech nghiem tuc.
8. Hold/capture flow dung `locked_balance` cho truong hop can reserve tien truoc khi capture.

## Tom Tat Ngan

- `payment-service` la saga orchestrator.
- `wallet-service` la owner cua tien va ledger.
- `payment-gateway` la adapter/bounded context cho nha cung cap thanh toan ngoai.
- Outbox dam bao event intent khong mat khi Kafka loi.
- Inbox dam bao consume idempotent khi Kafka redeliver.
- Wallet Service co local ACID nho DB transaction, row lock, ledger entry, unique idempotency key va outbox trong cung transaction.
- Toan he thong khong co distributed ACID; thay vao do la Saga + eventual consistency + compensation.
