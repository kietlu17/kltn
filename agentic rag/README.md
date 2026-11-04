# Agentic RAG shopping service

Service dùng LangChain, LangGraph, Gemini và Qdrant, thay thế `chatbot-service`. API chỉ đọc vector;
collection catalog do worker `agentic-indexer` (`python -m app.indexer`) xây và cập nhật.

## Luồng chính

```text
request
  -> understand: fast-path tất định cho câu ngắn chắc chắn, còn lại 1 semantic decision
  -> planner có schema
  -> route theo intent  ─────────────────────────────┐ (song song)
     -> browse categories                            policy_side: trả lời task chính sách phụ
     -> hybrid search Qdrant (dense + BM25, RRF, group theo sản phẩm)
        -> 0 kết quả: nới ràng buộc tất định (tối đa 2 vòng, không gọi LLM)
     -> product/order/cart tools
     -> clarify_guard: hỏi lại có gợi ý -> đổi chiến lược -> đề nghị chuyển người thật
     -> chuẩn bị cart mutation (chưa ghi) -> confirmActionId -> ghi idempotent
     -> checkout quote -> confirmActionId -> tạo order
  -> collect ─┴─> finalize: template cho tìm kiếm thường, LLM cho so sánh/tư vấn
```

## Giới hạn LLM và độ trễ

Mỗi lượt có một `TurnBudget` (`app/budget.py`): tối đa `AGENTIC_MAX_LLM_CALLS` lần gọi sinh văn bản
(mặc định 4) và hạn chót `AGENTIC_TURN_DEADLINE_SECONDS` (mặc định 8s). Mỗi loại gọi có timeout riêng
(`decide` 4s, `verify` 3s, `answer`/`policy` 4s, embedding 3s). Embedding chỉ tính thời gian, không tính lượt.
Hết budget thì node dùng đường tất định: `_fallback_understanding`, câu trả lời template, verifier
tất định theo tên/thông số (kèm warning `UNVERIFIED`). Chỉ `decide` được retry 1 lần khi lỗi tạm thời.

Câu tìm kiếm thường ("tai nghe bluetooth dưới 500k", "áo thun nam màu đen size L") được
`app/search_parser.py` phân tích không cần LLM: giá (dưới/trên/từ…đến/khoảng/số tiền trần), màu, size,
cụm sản phẩm. `decide` vẫn chạy song song; nếu sau `AGENTIC_DECIDE_HEDGE_SECONDS` (mặc định 1.5s) model
chưa trả lời thì tìm luôn theo kết quả parse (warning `PARSED_SEARCH`). Model lỗi thì vẫn tìm theo parse
thay vì hỏi lại. Câu chính sách, giỏ hàng, đơn hàng, so sánh hoặc nhắc đến sản phẩm đã hiển thị luôn chờ model.
Verifier LLM chỉ chạy cho thông số mơ hồ ("pin trâu"); kiểm tra đúng loại sản phẩm dùng tên sản phẩm.

Các lượt thường không gọi LLM: xác nhận "có", chọn size/màu của sản phẩm đang xem, "rẻ nhất/mắc nhất",
xem danh mục. Embedding câu truy vấn (1h), kết quả verifier (10 phút) và cây danh mục (5 phút) được cache.
Log `agentic_turn` ghi `llm_calls`, `llm_kinds` và `budget_exhausted`.

`POST /assistant/chat/stream` trả Server-Sent Events: `status` theo từng node, `products` ngay khi có,
`token` của câu trả lời, rồi `final` là đúng `ChatResponse` của endpoint thường.

## Khách hỏi vòng vo

- confidence ≥ 0.75: thực thi. 0.5–0.75 với tìm kiếm: vẫn tìm, câu trả lời nêu rõ giả định
  ("Mình hiểu bạn đang tìm …") và kèm gợi ý. < 0.5: hỏi lại.
- `clarify_count` được lưu theo session. Lần 1 hỏi một câu kèm `suggestions` (danh mục thật hoặc sản phẩm
  đang hiển thị); lần 2 hoặc lặp lại đúng câu cũ thì đưa lựa chọn có cấu trúc; từ lần 3 trả `handoff: true`.
  Lượt thực thi thành công đặt lại bộ đếm.
- Câu nhiều yêu cầu: task chính sách chạy song song; task khác không thực thi được sẽ được nêu tên trong câu
  trả lời thay vì bị bỏ.

Các ràng buộc giá, category, audience, màu, size và product type được đưa vào Qdrant filter trước
khi tính vector similarity. Kết quả được deduplicate theo `productId`, sau đó đọc lại giá và tồn kho
từ Product/Inventory Service trước khi trả về.

Catalog được trình bày cho agent dưới dạng cây `category → product → variant`. Cây ưu tiên quan hệ
`parentId` thật; với dữ liệu cũ đang lưu path trong tên như `Quần áo › Nam › Áo thun`, service tạo node
ảo theo từng đoạn path và giữ danh sách category ID nguồn ở mỗi nhánh. Khi planner trả `category_path`,
service tự ánh xạ node cha thành toàn bộ category ID con rồi dùng `MatchAny` để pre-filter Qdrant.
Không có mapping thì hệ thống bỏ filter taxonomy và tiếp tục semantic search thay vì trả về rỗng giả.

Conversation state theo bốn phase của shopping journey: `exploring`, `detailing`, `narrowing`, `selling`.
`active_product_id` cùng màu/size đã chọn được giữ qua các câu hỏi nối tiếp. Vì vậy câu như “màu đen
bao nhiêu tiền” đọc variant của đúng sản phẩm đang focus; “mua mẫu này” tiếp tục dùng variant đó và
không mở lại tìm kiếm toàn catalog hay render thêm carousel đề xuất.

Node `understand` tách việc hiểu lượt nói khỏi planning. Nó nhận nguyên văn tiếng Việt có dấu, history,
sản phẩm đang focus và lựa chọn variant hiện tại, rồi phát ra `dialogue_act`, thuộc tính được hỏi, màu/size
được nhắc và confirmation. Chuỗi đã bỏ dấu chỉ dùng cho fallback deterministic; planner không còn phải
đoán lại ý nghĩa của các câu rút gọn như `xl`, `màu be có size nào` hoặc `có`.

## An toàn giao dịch

- LLM chỉ lập kế hoạch; code quyết định tool và tham số được phép gọi.
- Mọi thao tác thêm/sửa/xóa giỏ hàng đều tạo `pendingAction`; chỉ thực thi khi client gửi đúng
  `confirmActionId`.
- Checkout luôn tạo quote trước. `confirmationToken` chỉ lưu trong checkpoint và không trả về API.
- Confirm checkout gọi endpoint hiện tại, nơi giá và tồn kho được kiểm tra lại ngay trước khi tạo đơn.
- Session được gắn với `x-user-id`; session của tài khoản này không thể dùng bởi tài khoản khác.

## Chạy local

Qdrant trong compose gốc không publish port ra host. Có thể chạy service trong cùng Docker network,
hoặc tạm publish `6333:6333` khi thử local.

```powershell
cd 'agentic rag'
Copy-Item .env.example .env
# Điền GEMINI_API_KEY và URL phù hợp
python -m uvicorn app.main:app --host 0.0.0.0 --port 3030 --reload
```

Service tự tìm `.env` từ thư mục hiện tại lên thư mục cha, vì vậy có thể dùng `.env` ở root repo
hoặc một file `.env` riêng trong `agentic rag`.

Khi stack gốc đang chạy, khởi động service trong cùng network (có Qdrant và chứng thư mTLS):

```powershell
docker compose -f 'agentic rag/compose.agentic.yml' up -d --build
```

Service thử nghiệm được publish tại `http://localhost:3030`. Chưa đổi `CHATBOT_SERVICE_URL` của
API Gateway; việc chuyển traffic chỉ nên làm sau khi chạy bộ acceptance test.

Để thử qua frontend mà không sửa compose gốc, recreate riêng API Gateway bằng override:

```powershell
docker compose -f docker-compose.yml -f 'agentic rag/compose.gateway.yml' up -d --build --no-deps api-gateway
```

Collection mặc định do `app.indexer` sở hữu:
`catalog_<sha256("agentic-v1:gemini:<embedding model>:<dimensions>:chunked-hybrid")[:12]>`. Tên này khác
collection v4 của chatbot-service nên hai indexer không bao giờ ghi đè nhau. Đặt
`AGENTIC_QDRANT_COLLECTION=<catalog_v4>` để tạm đọc collection cũ (chỉ dense).

- Mỗi sản phẩm có một chunk `base` (tên, thương hiệu, danh mục, đầu mô tả), các chunk `specs` và `detail`
  (≤1500 ký tự, detail chồng 150 ký tự) và một chunk mỗi nhóm màu `variant_group`. Mọi chunk mở đầu bằng
  tên sản phẩm, nằm dưới giới hạn ~2048 token của `gemini-embedding-001`.
- Dense vector unnamed cộng sparse vector `bm25` (`Modifier.IDF`). `app/sparse.py` là encoder BM25 tất
  định cho tiếng Việt đã bỏ dấu, có bigram âm tiết, không bỏ stop word.
- Truy vấn: một lệnh `query_points_groups` với prefetch dense + BM25, hợp nhất RRF, group theo `productId`.

## Container embedding (`agentic-indexer`)

`python -m app.indexer` so sánh catalog hiện tại với Qdrant và cache embedding, rồi chỉ embed phần chưa có:

| Trường hợp | Chi phí quota |
|---|---|
| Chunk đã có, payload không đổi | 0 (bỏ qua) |
| Chỉ đổi giá/tồn kho/facet (text giữ nguyên) | 0 (ghi đè payload) |
| Text đã từng embed (cache SQLite, kể cả khi mất collection) | 0 (dùng lại vector) |
| Text trùng nhau giữa nhiều sản phẩm | embed 1 lần |
| Text mới hoặc đã đổi | gửi Gemini theo batch `INDEXER_BATCH_SIZE` (mặc định 50) |

Mỗi batch được ghi vào cache trước rồi mới upsert Qdrant, nên dừng container bất kỳ lúc nào cũng chỉ mất tối
đa batch đang chạy. Chunk cũ của sản phẩm chỉ bị xóa khi chunk mới đã đủ; sản phẩm bị xóa hoặc gỡ duyệt bị
xóa khỏi index ngay đầu chu kỳ.

```powershell
# Xem trước số text cần embed (không tốn quota, không tạo collection)
docker compose -f 'agentic rag/compose.agentic.yml' run --rm agentic-indexer python -m app.indexer plan

# Chạy / dừng / chạy tiếp
docker compose -f 'agentic rag/compose.agentic.yml' up -d --build agentic-indexer
docker compose -f 'agentic rag/compose.agentic.yml' stop agentic-indexer
docker compose -f 'agentic rag/compose.agentic.yml' start agentic-indexer

# Tiến độ
docker compose -f 'agentic rag/compose.agentic.yml' exec agentic-indexer python -m app.indexer status
docker compose -f 'agentic rag/compose.agentic.yml' logs -f agentic-indexer
```

Đổi API key: ghi key mới vào `agentic rag/secrets/gemini_api_key` (thư mục đã nằm trong `.gitignore`).
Worker đọc lại file trước mỗi batch, không cần restart. Khi hết quota hoặc key bị từ chối, worker chuyển sang
`waiting_quota`/`waiting_api_key` và tự chạy tiếp ngay khi file key đổi. Nếu không có file, worker dùng
`GEMINI_API_KEY` trong `.env`; đổi biến này thì cần `up -d` lại container.

Các biến điều chỉnh: `INDEXER_INTERVAL_SECONDS` (chu kỳ đồng bộ lại, mặc định 900s),
`INDEXER_BATCH_INTERVAL_SECONDS` (giãn cách giữa các batch khi bị giới hạn theo phút),
`INDEXER_REQUEST_SIZE`/`INDEXER_REQUEST_INTERVAL_SECONDS` (mỗi batch 50 được gửi thành các request nhỏ,
mặc định 10 text cách nhau 12s ≈ 50 text/phút; request thành công được lưu ngay),
`INDEXER_RETRY_SECONDS` (phần lỗi của batch được gửi lại sau 60s, đến khi xong cả batch), `INDEXER_MAX_BATCHES` (trần số batch mỗi
chu kỳ, 0 = không giới hạn). `/assistant/health` báo `catalogComplete` và `hybridReady` khi index đủ.

`AGENTIC_SEMANTIC_DECISION_V2=false` tạm quay về interpreter/planner cũ để rollback. Khi bật v2,
model tạo một semantic decision duy nhất; model lỗi hoặc confidence thấp sẽ hỏi làm rõ thay vì mặc định tìm sản phẩm.

## API

### `POST /assistant/chat`

```json
{
  "message": "Tìm áo sơ mi nữ màu trắng dưới 500 nghìn",
  "sessionId": null,
  "referenceProductId": null,
  "variantId": null,
  "addressId": null,
  "paymentMethod": null,
  "voucherCode": null,
  "confirmActionId": null,
  "cancelActionId": null
}
```

Identity được lấy từ header do API Gateway cấp:

- `x-user-id`
- `x-user-role` (`buyer` cho thao tác mua hàng)

Response có thể bổ sung `sources` cho câu hỏi chính sách và các route `policy`, `multi`, `clarify`,
`out_of_scope`; các field response cũ vẫn giữ nguyên. `suggestions` là các câu trả lời nhanh mà client
gửi lại nguyên văn như một tin nhắn; `handoff: true` nghĩa là nên đề nghị chat với người bán.

Khi response có `pendingAction.id`, client phải hiển thị nội dung xác nhận. Gửi request tiếp theo với
`confirmActionId` để thực thi hoặc `cancelActionId` để hủy. Không xác nhận bằng cách phân tích câu
"đồng ý" để tránh thực thi nhầm.

### `GET /assistant/health`

Kiểm tra Gemini config, Qdrant collection và tên collection thực tế.

## Test

```powershell
cd 'agentic rag'
python -m unittest discover -s tests -v
```

Test dùng fake model/vector/backend, không gọi Gemini hay ghi vào giỏ hàng thật.

