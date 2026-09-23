# Product Agent

## Hai tầng LangGraph

```text
RouterAgent
  route → product_agent → END

ProductAgent
  understand → retrieve(ProductRAG) → decide_and_answer → END
                         ↑                    │
                         └──── refine ────────┘
```

`RouterAgent` là supervisor graph. `product_agent` là domain subgraph đầu
tiên và dùng chung state với router; có thể thêm order/policy agent bằng route
mới mà không đổi HTTP contract.

`ProductAgent` có số vòng retrieval hữu hạn, mặc định 2 và tối đa 3. Node
`refine` chỉ sửa query; giá, variant terms và product ID tham chiếu không được
nới lỏng.

## LangChain RAG

`ProductRAG.chain` là một LCEL runnable:

1. Gemini tạo `RETRIEVAL_QUERY` embeddings.
2. Qdrant trả candidates từ document và caption.
3. Nếu có ảnh, CLIP retrieval chạy trong collection ảnh riêng.
4. Các nhánh được hợp nhất bằng reciprocal-rank fusion.
5. Product Service và Inventory Service cung cấp dữ liệu mới nhất.
6. Bộ lọc deterministic loại sản phẩm chưa duyệt, hết hàng, sai giá hoặc sai
   màu/size.
7. Gemini structured output chỉ được phép chọn ID trong candidates đã lọc.

### Ảnh

- Yêu cầu chỉ có ảnh: CLIP trực tiếp, không cần gọi LLM.
- Ảnh kèm điều kiện: Gemini multimodal tạo caption, kết hợp text RAG và CLIP.
- Hỏi tiếp có thể dùng vector ảnh trong session; byte ảnh không được lưu.
- Tìm tương tự theo product ID dùng tối đa ba vector ảnh nguồn và ưu tiên cùng
  category.

Gemini và CLIP là hai vector space tách biệt. Hệ thống hợp nhất thứ hạng, không
so sánh raw cosine score giữa hai model.

## Grounding và giới hạn

- Không chấp nhận product ID do model tự tạo.
- Không dùng tồn kho hoặc giá từ Qdrant để khẳng định trạng thái hiện tại.
- Không tự bỏ điều kiện khi hết vòng tìm kiếm.
- Không khẳng định ảnh là cùng SKU, hàng chính hãng hoặc đúng thương hiệu.
- Direct image search thất bại được trả thành lỗi dependency; nhánh kết hợp có
  thể giữ text results và trả warning.
