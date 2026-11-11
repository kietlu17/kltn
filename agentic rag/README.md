# Agentic RAG shopping service

Service dùng LangChain, LangGraph, Gemini và Qdrant, thay thế `chatbot-service`. API chỉ đọc vector;
collection catalog do worker `agentic-indexer` (`python -m app.indexer`) xây và cập nhật.

## Luồng chính: supervisor + 2 agent

```text
request
  -> understand (supervisor): 1 semantic decision bằng LLM cho mọi lượt văn bản
  -> plan: map task -> agent  ───────────────────────┬──────────────────────┐ (song song)
     ProductAgent (app/agents/product.py)            policy_side            research_side
       hỏi đáp & tra cứu cho khách:                  (task chính sách phụ)  (web search khi LLM
       browse categories, product_detail, so sánh,                          đặt web_research=true)
       policy, hybrid search Qdrant
         -> cross-encoder pre-sort -> LLM judge chấm relevance -> top-k thích ứng
         -> 0 kết quả: nới ràng buộc (≤2 vòng) -> vẫn 0: web_expand (web gợi ý loại hàng
            catalog có) -> tìm lại, LLM judge vẫn chấm theo nhu cầu gốc
     OrderAgent (app/agents/order.py)
       giỏ hàng, thanh toán, đơn hàng, xác nhận:
       cart_view, prepare_cart (LLM đối chiếu variant/dòng giỏ thật), prepare_checkout,
       order_status, resolve_pending (confirmActionId -> ghi idempotent / tạo order)
     clarify_guard / general (supervisor)
  -> collect ─┴─> finalize: LLM viết câu trả lời từ dữ kiện đã kiểm tra (verifiedFacts,
                  ranking, webResearch); template/tất định chỉ là fallback
```

### Ưu tiên LLM, rule chỉ là fallback (`AGENTIC_LLM_FIRST=true`)

| Bước | LLM (mặc định) | Fallback khi model lỗi/hết budget |
|------|----------------|-----------------------------------|
| Hiểu lượt nói | `decide` cho mọi câu, kể cả "có", "xl", câu tìm kiếm thường | fast-path tất định, `search_parser` |
| Xếp hạng | `rank_candidates`: chấm 0–3 + kiểm chứng thông số mơ hồ trong cùng 1 call | lọc tên theo loại hàng, verifier riêng, cross-encoder |
| Top-k | chỉ giữ relevance ≥2; nếu chỉ có mức 1 thì trả kèm `partialMatch` | cắt theo điểm cross-encoder tương đối |
| Chọn variant / dòng giỏ | `resolve_order` trên danh sách variant và giỏ hàng thật | khớp màu/size tất định |
| Phương thức thanh toán, mã đơn | trích từ `decide` (`payment_method`, `order_id`) | regex |
| Câu trả lời | LLM từ dữ kiện đã kiểm tra | template / câu trả lời thuộc tính tất định |

`AGENTIC_LLM_FIRST=false` trả về chế độ ưu tiên độ trễ cũ (fast-path, hedge parse, template).

### Web search (product agent)

Gemini grounded Google Search (`AGENTIC_WEB_SEARCH`, luôn dùng Gemini key kể cả khi chat qua gateway
OpenAI-compatible). Chỉ chạy cho ca khó: LLM đánh dấu `web_research` (so sánh công nghệ, thông số chính
hãng tin đăng thường thiếu, cách chọn, nhu cầu rộng như quà tặng) hoặc catalog trả 0 kết quả sau khi nới.
Kết quả web chỉ là thông tin tham khảo kèm nguồn trong `sources`; không dùng để khẳng định giá, tồn kho
hay việc shop có bán. Câu trả lời ghi rõ "theo thông tin tham khảo trên web".

## Giới hạn LLM và độ trễ

Mỗi lượt có một `TurnBudget` (`app/budget.py`): tối đa `AGENTIC_MAX_LLM_CALLS` lần gọi sinh văn bản
(mặc định 6) và hạn chót `AGENTIC_TURN_DEADLINE_SECONDS` (mặc định 15s). Mỗi loại gọi có timeout riêng
(`decide`/`order` 4s, `rank` 4s, `verify` 3s, `answer`/`policy` 4s, `web` 7s, embedding 3s). Embedding chỉ
tính thời gian, không tính lượt. Một lượt tìm kiếm thường dùng 3 call (decide, rank, answer).
Phần dưới mô tả chế độ `AGENTIC_LLM_FIRST=false`.
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

Catalog được trình bày cho agent dưới dạng cây `Chủng loại → Chủng loại con → … → Sản phẩm → variant`.
`Category` có `parentId`, `path`, `level` (product-service). Các node gốc dùng chung (Thời trang, Điện tử,
Nhà cửa & Đời sống, Làm đẹp, Thực phẩm, Khác) thuộc `shopId: "platform"`; category của từng shop là node con,
nên sản phẩm giữ nguyên `categoryId`. Dữ liệu cũ dạng tên phẳng (`YODY · Áo thun nữ`,
`MUJI · Quần áo › Trang Phục Nữ › Áo Thun › 053:...`) được chuyển bằng
`node src/scripts/buildCategoryTree.js` (mặc định dry-run; `--apply` ghi kèm file backup; `--restore <file>` hoàn tác).

- `decide` nhận danh sách đường dẫn danh mục thật (`catalog_category_paths`, tối đa 3 cấp) và chọn
  `category_path`. Supervisor resolve đúng đường dẫn đó, cộng các nhánh cùng loại của shop khác
  (`Nữ › Áo Thun` của MUJI và `Nữ › Áo thun nữ` của YODY).
- Không có `category_path` thì resolve từ `product_type`: ưu tiên node bao trọn mọi từ ("áo thun" lấy mọi
  nhánh áo thun nam/nữ/trẻ em của mọi shop), cụm ngành hàng được quy về nhánh gốc ("quần áo nữ" →
  Thời trang › Nữ, "đồ điện tử" → Điện tử), cuối cùng mới là node có tên nằm trong câu.
- Filter category được nới đầu tiên (sau thuộc tính phụ) khi không có kết quả, vì nhánh có thể bị chọn sai.
- Indexer ghi đường dẫn đầy đủ vào chunk `base` (`Danh mục: Thời trang › Nữ › Áo thun nữ`) và `categoryName`.

Triển khai: chạy `buildCategoryTree.js --apply` trên MongoDB → khởi động lại product-service →
chạy lại `python -m app.indexer` (chỉ chunk `base` của mỗi sản phẩm cần embed lại, khoảng 2.500 lượt).

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

## Re-rank và top-k

Tìm kiếm chạy hai tầng. Tầng 1 là hybrid (dense + BM25, RRF) lấy `AGENTIC_RERANK_CANDIDATES` ứng viên
(mặc định 20). Tầng 2 là cross-encoder đa ngôn ngữ `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (huấn luyện
trên mMARCO, có tiếng Việt), đọc câu hỏi cùng tên/danh mục/mô tả của từng ứng viên rồi xếp lại; hiển thị
top-k = `AGENTIC_RESULT_LIMIT` (mặc định 5). Model chạy trên model server `image-embedding` (`POST /rerank`,
CPU, ~0,3–0,5 s cho 20 ứng viên). Model server lỗi hoặc quá `AGENTIC_RERANK_TIMEOUT_SECONDS` thì giữ thứ tự
hybrid. Không re-rank khi sắp xếp theo giá hoặc khi tìm bằng ảnh.

## Tìm bằng hình ảnh

`POST /assistant/chat` nhận thêm `image` (data URL hoặc base64 JPEG/PNG/WebP, tối đa 5 MB). Ảnh được
embed bằng CLIP ViT-B/32 trên model server (`POST /embed`) và tìm trong collection `catalog_images_*` do
`chatbot-image-indexer` xây; mỗi sản phẩm lấy ảnh giống nhất, ngưỡng `AGENTIC_IMAGE_MIN_SCORE`. Chữ kèm ảnh
chỉ dùng để lọc giá/màu/size/thương hiệu ("giống ảnh này nhưng dưới 500k"); lượt có ảnh không gọi LLM để
quyết định. Cần chạy `image-embedding` trong stack chính:

    docker compose up -d image-embedding
    # index ảnh cho toàn catalog (CLIP local, không tốn quota Gemini)
    docker compose run --rm --no-deps -e CHATBOT_INDEX_ONCE=true chatbot-image-indexer

Frontend bật/tắt riêng từng tính năng: `VITE_ASSISTANT_IMAGE`, `VITE_ASSISTANT_VOICE` (agentic-rag chưa có
`/assistant/transcribe`, nên tắt giọng nói).

