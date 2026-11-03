# Shopping Assistant — LangChain / LangGraph / Gemini

Chatbot service điều phối các nhánh sản phẩm, chính sách và đơn hàng. Nhánh sản phẩm kết hợp RAG với công cụ mua sắm.

## Kiến trúc

```text
Frontend → API Gateway /assistant → RouterAgent: plan một lần
                                      ├── product_agent: plan theo quy tắc
                                      │    ├── hành động mua sắm → commerce_action
                                      │    ├── cần làm rõ → decide_and_answer
                                      │    └── tìm sản phẩm → ProductRAG → decide_and_answer
                                      ├── customer_service_agent: retrieve_policy → answer_policy
                                      └── order_agent: load_order → answer_order

Text/caption → Gemini embeddings → Qdrant text collection
Ảnh catalog/khách → CLIP → Qdrant image collection
Ảnh khách/catalog → Gemini multimodal → caption tiếng Việt
Candidates → Product Service + Inventory Service → lọc nghiệp vụ → Gemini trả lời
Shopee Help API → local PDFs → policy indexer → Gemini embeddings → Qdrant policy collection
```

- LangGraph điều phối router và Product Agent.
- LangChain cung cấp Gemini chat/vision, embeddings, structured output và LCEL RAG runnable.
- Customer Service Agent chỉ trả lời dựa trên policy chunks kèm URL nguồn.
- Router dùng Gemini trả về ý định có schema để chọn nhánh sản phẩm, chính sách hoặc đơn hàng. Cùng kết quả hiểu ngữ nghĩa xác định thao tác giỏ hàng, xem danh mục và nhu cầu tìm kiếm mở; Product Agent giữ context nhiều lượt. Với nhu cầu rộng như tìm quà, nhánh discovery có thể dùng Google Search có grounding để lấy ý tưởng, tạo tối đa bốn truy vấn bổ sung, rồi chỉ tìm sản phẩm trong catalog của sàn. Khi bước hiểu ý định lỗi, chatbot mặc định về nhánh sản phẩm và không tự suy ra thao tác giao dịch. Nếu bước hiểu nhu cầu sản phẩm cũng lỗi, chatbot hỏi lại thay vì đoán ý định từ từ khóa.
- Tìm sản phẩm kết hợp truy vấn vector và từ khóa trên cùng bộ lọc Qdrant, gộp điểm theo sản phẩm và đọc lại trạng thái duyệt, giá, tồn kho từ các dịch vụ gốc. Truy vấn từ khóa dùng full-text index trên payload hiện có nên không phải tạo lại embedding. Câu hỏi chỉ có ảnh dùng CLIP và không gọi Gemini để trả lời; ảnh kèm mô tả có thể cần Gemini tạo caption.
- Câu hỏi “Shop bán gì?” đọc danh mục từ Product Service và chỉ ưu tiên danh mục có sản phẩm trong chỉ mục. Giao diện đưa lựa chọn so sánh, hỏi về mẫu và xem thêm; xem thêm loại các thẻ vừa hiện.
- Gemini còn được dùng cho embeddings, trả lời chính sách và mô tả ảnh khi cần.
- Order Agent đọc đơn hàng qua API của tài khoản đã xác thực; đây là nhánh gọi công cụ, không phải RAG.
- CLIP vẫn tạo vector image-to-image độc lập; không phải LLM và không dùng chung vector space với Gemini.
- Product Agent luôn đọc lại trạng thái duyệt, giá và tồn kho trước khi trả sản phẩm.

`CHATBOT_SHOPPING_WEB_RESEARCH=true` bật nghiên cứu Google Search cho nhu cầu mở; đặt `false` để chỉ mở rộng truy vấn bằng model. Nghiên cứu web chỉ tạo ý tưởng nhóm hàng, không được dùng làm bằng chứng về sản phẩm, giá hay tồn kho trên sàn. Nhánh này có thêm lượt gọi model/search và có thể tăng độ trễ; khi lỗi, tìm kiếm catalog vẫn tiếp tục. Sau khi nâng cấp, indexer tạo full-text index trên trường `text` của collection hiện tại.

Đo qua API khi các dịch vụ đang chạy:

```bash
cd chatbot-service
python -m src.scripts.evaluate_shopping --url http://localhost:3000 --cases ../docs/evaluation/shopping-acceptance.json --output shopping-report.json
```

Báo cáo JSON ghi lỗi điều kiện giá, thẻ trùng, biến thể chưa xác nhận tồn kho và độ trễ p50/p95. Các tình huống mẫu là kiểm thử hồi quy, không phải ước lượng tỉ lệ lỗi trên toàn bộ khách hàng.

## Trạng thái hội thoại

`sessionId` của API là `thread_id` của LangGraph. Router graph dùng
`AsyncSqliteSaver` để checkpoint trạng thái trong `/data/checkpoints.sqlite`;
ứng dụng không còn lưu hội thoại bằng bảng `Sessions` riêng. Mỗi lượt mới đọc
checkpoint đã hoàn tất gần nhất, đưa câu hỏi mới vào graph, rồi ghi lại lịch sử
rút gọn, kế hoạch tìm kiếm, sản phẩm đang xét và thao tác chờ xác nhận.

Ảnh gốc, thẻ sản phẩm đầy đủ, đoạn chính sách và dữ liệu đơn hàng trung gian là
các trường `UntrackedValue`: chúng phục vụ lượt xử lý nhưng không được ghi vào
checkpoint. Chỉ thẻ sản phẩm rút gọn được giữ cho câu hỏi tiếp nối. Ngữ cảnh
mua sắm, ảnh đã mã hóa vector và thao tác chờ có
thời hạn riêng; checkpoint hết hạn được dọn khi truy cập hoặc theo lịch. Khi
nâng cấp, các phiên còn hiệu lực từ `/data/sessions.sqlite` được nhập một lần
vào checkpoint để giữ cuộc hội thoại đang dùng. Frontend tiếp tục gửi và nhận
`sessionId` như trước.

`plan.context` là state mua sắm chuẩn hóa, có `version` và `revision`:

- `task`: tìm sản phẩm, hỏi một sản phẩm, so sánh hoặc tìm tương tự.
- `requirements`: loại sản phẩm, giới tính nếu có, màu/size khách yêu cầu,
  ngân sách và thuộc tính mở như RAM, dung lượng, chất liệu, thiết bị tương thích.
- `buyer`: thông tin người dùng đã cung cấp cho nhu cầu hiện tại, tách khỏi thông số hàng hóa.
- `selected_product_ids`: chỉ nhận ID từ danh sách đã hiển thị hoặc link/ID khách cung cấp.
- `awaiting`: thông tin còn thiếu cho tác vụ; tìm sản phẩm không bắt buộc chọn sản phẩm trước.
- `derived_size`: size ước lượng, nguồn và fingerprint đầu vào để tái sử dụng khi còn hợp lệ.

`agents/conversation.py` sở hữu schema, nâng cấp checkpoint cũ, reducer và phép
chiếu sang các trường phẳng của `SearchPlan` cho công cụ retrieval hiện hữu.
Gemini trích xuất patch của câu mới (không ghi đè toàn bộ state); code quyết định
chuyển tác vụ, giữ điều kiện, xóa điều kiện được bỏ và tính thông tin còn thiếu.
Một lượt trả lời chỉ có số đo đang được hỏi được xử lý trực tiếp, không gọi parser LLM.
Các lượt ngôn ngữ khác thêm một lần gọi structured LLM. Nếu parser lỗi, dùng adapter
quy tắc cũ làm phương án dự phòng; mức hiểu ngôn ngữ ở nhánh này hạn chế hơn.

Đổi chủ đề hoặc ảnh mới xóa điều kiện và tham chiếu không còn phù hợp, kể cả
danh sách cũ khi lượt tìm mới không có kết quả. Bổ sung thuộc tính giữ nguyên mục tiêu;
`clear_fields`/thuộc tính null thể hiện việc khách chủ động bỏ điều kiện. Xem mẫu
hoặc sửa ngân sách không xóa size đã suy ra; thay số đo, giới tính, loại sản phẩm
hoặc sản phẩm đang hỏi sẽ làm mất hiệu lực ước lượng. Thuộc tính mở hiện tham gia
query ngữ nghĩa và kiểm tra câu trả lời, chưa phải mọi thuộc tính đều có bộ lọc
payload cứng trong Qdrant.

Router vẫn sở hữu domain hiện tại. CommerceAgent sở hữu `pending_action`, token
xác nhận và thao tác giỏ/checkout; parser mua sắm không được phát lệnh giao dịch.
Order/policy tiếp tục có luồng riêng và không ghi đè nhu cầu mua sắm. Context dùng
chung TTL shopping và ràng buộc tài khoản hiện có. Không cần xóa phiên hay reindex.

Ví dụ `áo sơ mi nữ → màu trắng → size nào phù hợp → cao 1m6, nặng 50kg`
giữ query sản phẩm và lưu số đo riêng, tránh truy xuất quần hay đồ bộ chỉ vì
chúng chứa `50kg`. Bộ lọc kiểm tra lại loại/giới tính trên catalog mới nhất;
màu, tồn kho và khoảng size cm phải khớp trên cùng biến thể. Tất `25–27cm`
không được coi là vừa chân `24cm` hay `29cm`.

Tìm quần áo theo vóc dáng (`dialogue_act=size_search`) không yêu cầu chọn sản
phẩm trước. Ví dụ “nữ, cao 1m60, nặng 50kg thì áo sơ mi trắng nào phù hợp”
và “cho tôi xem vài mẫu” đi vào retrieval, giữ loại/màu/giới tính/số đo.
LLM ước lượng tối đa ba size chữ vào `estimated_sizes`, tách khỏi
`variant_terms` do khách yêu cầu. Sau lọc màu, giá và tồn kho, các mẫu có
biến thể thuộc size ước lượng được ưu tiên trước khi lấy sáu kết quả.
Size ước lượng không lọc cứng vì mỗi shop có cách chia size khác nhau;
size khách yêu cầu rõ ràng vẫn là điều kiện bắt buộc.

Nếu model trả về danh sách size rỗng, chatbot dùng Google Search grounding
qua Gemini rồi trích size từ bằng chứng có nguồn; không coi một bảng size
trên web là chuẩn của mọi shop. Nếu không có bằng chứng hoặc dịch vụ model
lỗi, vẫn tìm sản phẩm theo yêu cầu và ghi rõ chưa ước lượng được size.
Grounding dùng [công cụ Google Search của LangChain Gemini](https://reference.langchain.com/python/langchain-google-genai/chat_models/ChatGoogleGenerativeAI).
Nhánh web chỉ chạy khi thiếu ước lượng, có thêm độ trễ và chi phí API.

Tư vấn size **cho một mẫu quần áo cụ thể** yêu cầu sản phẩm, chiều cao và
cân nặng. `sizing_product_id` trong plan giữ mẫu đã chọn qua nhiều lượt chat;
khách có thể nhập tên mẫu đã xem hoặc gửi link `/product/<id>`.
Thẻ sản phẩm chỉ giữ các thao tác thêm giỏ và tìm tương tự. Khi đủ thông tin,
chatbot đọc sản phẩm hiện còn hiển thị và dùng LLM hiện tại để ước lượng size
từ kiến thức đã học, không bắt buộc bảng size hay số đo ngực/eo. Nhánh này
không truy xuất vector và không dùng sản phẩm làm tham chiếu tìm mẫu tương tự.
Code luôn thêm lời nhắc kết quả chỉ mang tính tham khảo, cần liên hệ nhà bán
hàng để xác nhận. Ước lượng không đồng nghĩa với kiểm chứng độ vừa hoặc tồn kho;
nếu model lỗi, chatbot xác nhận mẫu và số đo đã lưu, báo dịch vụ tạm lỗi và
cho phép nhắn “tư vấn lại size” sau thời gian cooldown. Trường hợp model không
có cơ sở ước lượng được thông báo riêng; không tự gán size mặc định.

Loại `tat` mới tương thích với payload Qdrant cũ `khac`: tìm trong cả hai,
sau đó xác nhận lại loại từ tên sản phẩm. Không cần xóa collection hay tạo
lại embedding; lần đồng bộ metadata tiếp theo sẽ cập nhật loại sản phẩm.
Test hồi quy: `python -m unittest discover -s tests -p 'test_shopping_context.py'`.

## Cấu trúc thư mục

```text
src/
├── agents/          # LangGraph state, router và Product Agent
├── api/             # Các thành phần API như speech-to-text
├── core/            # Cấu hình dùng chung
├── infrastructure/  # HTTP clients và model clients
├── policy/          # Customer Service Agent, crawler, PDF và policy RAG
├── product/         # Product RAG, catalog, visual search và indexers
├── scripts/         # Evaluation và migration scripts
├── image_embedding.py
└── main.py          # FastAPI entrypoint
```

Toàn bộ mã nguồn xử lý policy nằm trong `src/policy`; snapshot PDF local
nằm trong `output/pdf/shopee-help` và được mount read-only vào policy indexer.

## API

- `POST /assistant/chat`: chat text, ảnh hoặc product ID tham chiếu.
- `GET /assistant/products/{productId}/similar`: tìm sản phẩm tương tự không sinh lời tư vấn.
- `POST /assistant/transcribe`: Whisper local, audio tối đa 5 MB và 60 giây.
- `GET /assistant/health`: trạng thái cấu hình và hai chỉ mục.

Response chat giữ contract:

```json
{
  "sessionId": "...",
  "answer": "...",
  "products": [],
  "imageSearchMode": "text_and_image_vector",
  "retrievalRounds": 1,
  "warnings": [],
  "sources": [],
  "route": "product"
}
```

## Cấu hình

Docker Compose đọc file `.env` ở thư mục gốc repository. Python không tự load
`chatbot-service/.env` khi chạy trực tiếp.

```dotenv
GEMINI_API_KEY=
CHATBOT_GEMINI_MODEL=gemini-2.5-flash
CHATBOT_EMBEDDING_MODEL=gemini-embedding-001
CHATBOT_EMBEDDING_DIMENSIONS=768
CHATBOT_RERANK_CANDIDATES=30
CHATBOT_RERANK_BAYESIAN_PRIOR=20
CHATBOT_IMAGE_MODEL=openai/clip-vit-base-patch32
CHATBOT_IMAGE_REVISION=3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268
CHATBOT_IMAGE_MIN_SCORE=0.65
CHATBOT_MIN_SCORE=0.35
CHATBOT_SIMILAR_MIN_SCORE=0.5
CHATBOT_POLICY_PDF_PATHS=/policies/shopee-help
CHATBOT_POLICY_EMBED_BATCH_SIZE=50
CHATBOT_POLICY_EMBED_RETRIES=10
CHATBOT_POLICY_EMBED_DELAY_SECONDS=0.5
CHATBOT_POLICY_SYNC_SECONDS=86400
```

Khi Gemini Flash hết quota, Product Agent tiếp tục trả retrieval có cảnh báo;
Customer Service Agent dùng câu trích xuất từ policy gần nhất và vẫn gắn nguồn.

## Lập chỉ mục

`chatbot-indexer` đọc catalog approved, tạo document/caption và embedding văn
bản. Kafka chỉ đánh thức worker; full reconciliation vẫn chạy định kỳ.

Mỗi sản phẩm có một chunk `base` chứa tên, mô tả và chi tiết, cùng một chunk
`variant_group` cho mỗi nhóm màu. Các size, ID biến thể và khoảng giá được lưu
trong metadata của nhóm màu. Thay đổi size hoặc giá của nhóm hiện có chỉ cập
nhật metadata, không gọi embedding. Thay đổi nội dung hoặc thêm/bớt nhóm màu
cần embedding lại các chunk của sản phẩm. Schema hash mới sẽ chuyển các điểm
vector cũ khi `chatbot-indexer` chạy lại; nếu worker đang dừng để giữ quota,
Qdrant vẫn dùng các điểm cũ cho đến khi chủ động chạy migration.

`chatbot-image-indexer` tải ảnh catalog, gọi `image-embedding` để tạo CLIP
vector và đối soát collection ảnh. Hai worker cache theo content hash trong
SQLite và không đọc MongoDB trực tiếp.

Crawler chạy tách biệt để tải toàn bộ cây Shopee Help dành cho người mua thành
một PDF cho mỗi bài và tạo `manifest.json`. `chatbot-policy-indexer` không truy
cập Internet: worker đọc đệ quy các PDF local, chunk theo trang và lưu URL nguồn,
nhóm, danh mục, số trang trong một collection Qdrant riêng.

Tạo hoặc cập nhật snapshot local:

```powershell
cd chatbot-service
python -m src.policy.crawler
cd ..
```

PDF được lưu tại `output/pdf/shopee-help/<nhóm>/<danh-mục>/`. Nếu một bài lỗi,
crawler ghi chi tiết vào manifest và trả exit code lỗi thay vì âm thầm bỏ qua.

Đổi model/dimension embedding tạo namespace Qdrant mới, vì vậy cần chạy lại
indexer. Collection CLIP độc lập và không bị thay đổi khi chỉ đổi model Gemini.

## Chạy

```powershell
cd chatbot-service
python -m src.policy.crawler
cd ..
docker compose up -d --build image-embedding chatbot-service chatbot-indexer chatbot-image-indexer chatbot-policy-indexer
docker compose up -d --build api-gateway
Invoke-RestMethod http://localhost:3000/assistant/health
```

## Kiểm thử

```powershell
docker run --rm --mount "type=bind,source=$PWD/chatbot-service,target=/app" ecommerce-microservices-chatbot-service python -m unittest discover -s tests -v
```

Script kiểm tra retrieval trên catalog thật:

```powershell
docker compose exec chatbot-service python -m src.scripts.evaluate_product --limit 12 --output /data/product-evaluation.json
```

Self-lookup ảnh catalog chỉ kiểm tra wiring, không thay thế benchmark ảnh khách
độc lập.
