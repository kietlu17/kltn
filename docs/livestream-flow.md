# Livestream Flow

Tai lieu nay mo ta luong livestream commerce theo kien truc moi: LiveKit la media plane va realtime room bus; AI co-host la LiveKit participant; Kafka chi luu cac event quan trong de audit/analytics.

## 1. Thanh phan

```text
Frontend
  - SellerLiveStudio: publish camera/mic, ghim san pham, chat trong room
  - BuyerLiveRoom: subscribe live, xem pinned product, chat trong room

API Gateway
  - Xac thuc JWT
  - Phan quyen seller/buyer/admin
  - Proxy /lives sang livestream-service

livestream-service
  - Control plane cho LiveSession va LivePinnedProduct
  - Tao LiveKit room/token
  - Dispatch AI co-host vao room khi live start
  - Verify LiveKit webhook va reconcile room
  - Flush stats tu Redis ve MongoDB

LiveKit Server
  - WebRTC audio/video
  - Data channel cho realtime chat va live events trong room
  - Agent dispatch de dua AI co-host vao room

ai-cohost-service
  - LiveKit Agent worker
  - Join room nhu mot participant
  - Nghe live.chat.message qua data channel
  - Detect intent mua hang
  - Goi cart-service
  - Publish ket qua ve room qua data channel
  - Ghi event quan trong vao Kafka

Kafka
  - Event log cho audit, analytics, notification, replay

MongoDB / Redis
  - MongoDB luu LiveSession, pinned product, stats snapshot
  - Redis dem viewer/presence tam thoi va batch stats
```

## 2. Flow seller start live

```text
Seller bam Bat dau live
  -> POST /lives/{liveId}/start
  -> livestream-service verify seller thuoc shop
  -> ensure LiveKit room live_{liveId}
  -> dispatch AI co-host agent vao room
  -> set live.status = live
  -> tao seller publisher token
  -> publish live.session.started.v1
  -> frontend seller connect LiveKit va publish camera/mic
```

AI co-host duoc dispatch explicit bang LiveKit Agent Dispatch API, kem metadata:

```json
{
  "liveId": "live_123",
  "shopId": "shop_123",
  "sellerId": "seller_123",
  "activePinnedProductId": "prod_123"
}
```

## 3. Flow chat realtime trong room

Chat khong di qua Socket.IO nua. Seller va buyer publish packet truc tiep len LiveKit data channel.

```text
Buyer gui chat
  -> room.localParticipant.publishData({ type: "live.chat.message", ... })
  -> LiveKit fanout den seller, buyer khac, AI co-host
  -> AI co-host ghi Kafka live.chat.message.created
```

Packet trong room:

```json
{
  "type": "live.chat.message",
  "id": "msg-123",
  "liveId": "live_123",
  "shopId": "shop_123",
  "senderId": "buyer_456",
  "senderRole": "buyer",
  "senderName": "buyer@example.com",
  "buyerId": "buyer_456",
  "text": "toi muon mua san pham nay 2 cai",
  "activePinnedProductId": "prod_123"
}
```

Kafka event:

```text
live.chat.message.created
```

## 4. Flow AI co-host add cart

```text
AI co-host participant nhan live.chat.message
  -> detect intent add_to_cart
  -> resolve productId tu activePinnedProductId
  -> resolve quantity tu text
  -> publish live.intent.detected vao room
  -> publish Kafka live.intent.detected
  -> POST cart-service /cart/add bang mTLS
  -> publish live.cart.item_added vao room
  -> publish Kafka live.cart.item_added
```

Room event khi detect intent:

```json
{
  "type": "live.intent.detected",
  "liveId": "live_123",
  "buyerId": "buyer_456",
  "intent": "add_to_cart",
  "productId": "prod_123",
  "quantity": 2,
  "confidence": 0.82,
  "reply": "Da nhan yeu cau mua 2 san pham dang ghim"
}
```

Room event khi add cart thanh cong:

```json
{
  "type": "live.cart.item_added",
  "liveId": "live_123",
  "buyerId": "buyer_456",
  "productId": "prod_123",
  "quantity": 2,
  "reply": "Da them 2 san pham vao gio hang"
}
```

Kafka events can luu:

```text
live.chat.message.created
live.intent.detected
live.cart.item_added
```

## 5. Flow ghim san pham

```text
Seller ghim/chuyen active product
  -> POST /lives/{liveId}/pinned-products hoac PATCH /lives/{liveId}/active-product
  -> livestream-service validate product thuoc shop
  -> luu snapshot pinned product vao MongoDB
  -> publish Kafka live.product.active_changed.v1
  -> seller frontend publish data channel live.product.active_changed
  -> buyer reload pinned products
```

## 6. Flow buyer xem live

```text
Buyer vao /live/{liveId}
  -> GET /lives/{liveId}
  -> GET /lives/{liveId}/pinned-products
  -> POST /lives/{liveId}/viewer-token
  -> connect LiveKit
  -> subscribe audio/video cua seller
  -> nhan chat/product/cart events tu data channel
```

## 7. Ket thuc live

```text
Seller bam Ket thuc
  -> POST /lives/{liveId}/end
  -> livestream-service set ending
  -> delete LiveKit room
  -> set ended
  -> publish live.session.ended.v1
  -> LiveKit disconnect seller, buyer, AI co-host
```

## 8. Production notes

- LiveKit data channel phu hop voi realtime in-room fanout; Kafka khong nam tren hot path cua chat UI.
- Kafka van la source cho audit/analytics/replay, khong phai message bus bat buoc de user thay chat realtime.
- AI co-host nen idempotent theo `message.id` de tranh add cart lap neu packet/retry.
- Intent detector hien tai la rule-based; co the thay bang LLM sau, nhung van giu cung contract room event va Kafka topic.
- LiveKit Agent worker scale ngang doc lap voi livestream-service. Nhieu worker cung dang ky `LIVEKIT_AGENT_NAME`; LiveKit dispatch se gan job cho worker kha dung.
- Viewer count nen uu tien LiveKit room participant/presence; Redis stats chi de aggregate va flush ve MongoDB.
- Khi chay local bang Docker Desktop, LiveKit can advertise host reachable cho ICE. Compose mac dinh dung `--node-ip 192.168.100.3` theo may dev hien tai; neu doi Wi-Fi/mang thi set `LIVEKIT_NODE_IP=<LAN_IP_may_host>` truoc khi `docker compose up`.
