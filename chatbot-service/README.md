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
- Lập kế hoạch và chọn nhánh dùng quy tắc, không gọi Gemini. Tìm kiếm sản phẩm dùng một lượt truy xuất và tối đa một lần gọi Gemini để chọn kết quả, trả lời. Câu hỏi chỉ có ảnh dùng CLIP và không gọi Gemini để trả lời; ảnh kèm mô tả có thể cần thêm một lần gọi Gemini để tạo caption.
- Gemini còn được dùng cho embeddings, trả lời chính sách và mô tả ảnh khi cần.
- Order Agent đọc đơn hàng qua API của tài khoản đã xác thực; đây là nhánh gọi công cụ, không phải RAG.
- CLIP vẫn tạo vector image-to-image độc lập; không phải LLM và không dùng chung vector space với Gemini.
- Product Agent luôn đọc lại trạng thái duyệt, giá và tồn kho trước khi trả sản phẩm.

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
