# Livestream Flow

Tài liệu này mô tả luồng livestream commerce theo kiến trúc hybrid self-host.

Mục tiêu chính: không để 10.000 viewer join trực tiếp vào một LiveKit room chỉ để xem và chat. LiveKit giữ vai trò media server cho shop publish WebRTC và tạo HLS egress. Buyer xem video qua HLS/CDN self-host, còn chat/event đi qua realtime-service riêng.

## 1. Thành Phần

```text
Seller Frontend
  -> SellerLiveStudio
  -> Bật camera/mic local preview
  -> Nhấn Bắt đầu live để publish camera/mic vào LiveKit
  -> Chat và ghim sản phẩm qua realtime-service

Buyer Frontend
  -> BuyerLiveRoom
  -> Xem video bằng HLS playback URL
  -> Chat qua realtime-service, không join LiveKit room
  -> Xem sản phẩm ghim, bấm + hoặc Mua ngay để thêm giỏ hàng

API Gateway
  -> Proxy /lives sang livestream-service
  -> Proxy /realtime sang realtime-service, hỗ trợ WebSocket upgrade

livestream-service
  -> Control plane cho LiveSession và LivePinnedProduct
  -> Tạo LiveKit room/token cho seller
  -> Start/stop LiveKit Egress để tạo HLS
  -> Lưu hlsPlaybackUrl
  -> Verify LiveKit webhook
  -> Reconcile room/egress

LiveKit Server
  -> Media plane WebRTC cho seller publisher
  -> Room/session management
  -> Không dùng làm chat bus cho buyer ở kiến trúc hybrid chuẩn

LiveKit Egress
  -> Join room nội bộ
  -> Transcode/segment stream thành HLS
  -> Upload playlist/segment lên MinIO

MinIO
  -> Object storage self-host cho HLS playlist và segment

Nginx HLS Gateway
  -> Serve /hls/{liveId}/index.m3u8
  -> Cache HLS segment
  -> Đóng vai trò CDN/cache layer self-host đầu tiên

realtime-service
  -> Socket.IO chat/presence ngoài LiveKit room
  -> Broadcast live:event cho seller và buyer
  -> Ghi Kafka live.chat.message.created
  -> Forward buyer chat sang ai-cohost-service /live-chat

ai-cohost-service
  -> FastAPI service
  -> Nhận chat event từ realtime-service
  -> Call LLM để detect intent add_to_cart
  -> Chỉ được thêm giỏ hàng, không được thanh toán
  -> Call cart-service khi intent hợp lệ
  -> Trả event về realtime-service để publish lại cho room chat

Kafka
  -> Event log cho audit, analytics, replay
  -> Lưu các event quan trọng:
     live.chat.message.created
     live.intent.detected
     live.cart.item_added
```

## 2. Flow Seller Start Live

```text
Seller nhấn Bắt đầu live
  -> POST /lives/{liveId}/start
  -> livestream-service verify seller thuộc shop
  -> ensure LiveKit room live_{liveId}
  -> set live.status = live
  -> tạo seller publisher token
  -> trả { livekit: { url, token, roomName } }
  -> SellerLiveStudio connect LiveKit
  -> publish camera/mic bằng WebRTC
  -> start HLS egress
  -> Egress ghi HLS playlist/segment vào MinIO
  -> livestream-service lưu hlsPlaybackUrl
```

Luồng media:

```text
Seller Browser
  -> WebRTC publish
  -> LiveKit room
  -> LiveKit Egress
  -> MinIO
  -> Nginx HLS Gateway/cache
  -> Buyer Browser xem HLS
```

## 3. Flow Buyer Xem Live

```text
Buyer vào /live/{liveId}
  -> GET /lives/{liveId}
  -> GET /lives/{liveId}/pinned-products
  -> lấy hlsPlaybackUrl
  -> phát video HLS qua Nginx/CDN
  -> connect realtime-service qua Socket.IO để chat
```

Buyer không gọi `/viewer-token` và không connect `room.connect(...)` vào LiveKit.

## 4. Flow Chat Ngoài Room

```text
Buyer gửi chat
  -> Socket.IO live:chat:send
  -> realtime-service validate JWT
  -> broadcast live:event type live.chat.message
  -> publish Kafka live.chat.message.created
  -> forward event sang ai-cohost-service /live-chat
```

Packet chat:

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
  "text": "tôi muốn mua sản phẩm này 2 cái",
  "activePinnedProductId": "prod_123"
}
```

## 5. Flow AI Thêm Giỏ Hàng

```text
ai-cohost-service nhận /live-chat
  -> gọi LLM để phân loại intent
  -> nếu không phải add_to_cart: bỏ qua
  -> nếu add_to_cart nhưng chưa có activePinnedProductId: trả live.intent.detected lỗi mềm
  -> fetch product detail từ product-service
  -> nếu có nhiều biến thể và user chưa nói rõ: trả live.intent.variant_required
  -> nếu đủ thông tin: POST cart-service /cart/add
  -> publish Kafka live.intent.detected
  -> publish Kafka live.cart.item_added
  -> trả events cho realtime-service
  -> realtime-service broadcast events về buyer/seller
```

AI chỉ được gọi cart-service để thêm giỏ hàng. AI không được gọi payment-service, order-service, wallet-service hoặc bất kỳ API thanh toán nào.

## 6. Flow Ghim Sản Phẩm

```text
Seller ghim/chuyển active product
  -> POST /lives/{liveId}/pinned-products hoặc PATCH /lives/{liveId}/active-product
  -> livestream-service validate product thuộc shop
  -> lưu snapshot pinned product vào MongoDB
  -> SellerLiveStudio emit live:event:send qua realtime-service
  -> realtime-service broadcast live.product.active_changed
  -> BuyerLiveRoom reload pinned products
```

## 7. Viewer Count Trong Hybrid

Có hai loại count khác nhau:

```text
Chat presence
  -> Đếm socket đang connect vào realtime-service
  -> Phù hợp để biết số người đang tương tác

HLS viewer count
  -> Không tự nhiên nằm trong LiveKit room
  -> Nên đo bằng heartbeat từ BuyerLiveRoom hoặc log/metrics từ Nginx/CDN
  -> Flush về Redis/MongoDB theo batch
```

Nếu cần hiển thị "10.000 người đang xem" chính xác, không lấy từ LiveKit participant count. Với hybrid, viewer thật đến từ HLS/CDN layer.

## 8. Kết Thúc Live

```text
Seller nhấn Kết thúc live
  -> POST /lives/{liveId}/end
  -> livestream-service set ending
  -> stop LiveKit Egress
  -> delete LiveKit room
  -> set ended
  -> publish live.session.ended.v1
```
