"""English versions of the thesis figures (3.2 – 4.4) -> docs/diagrams/thesis/en/.

    python docs/diagrams/thesis/build_en.py
    node docs/diagrams/uml/render_png.cjs --dir thesis/en

Reuses the Vietnamese specs in build.py and translates every label before layout,
so wrapping and widths are computed on the English text.
"""
from __future__ import annotations

import copy
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "en"
sys.path.insert(0, str(HERE.parent / "uml"))
sys.path.insert(0, str(HERE))

import build  # noqa: E402
import engine  # noqa: E402

TR = {
    # participants / lanes
    "Người mua": "Buyer", "Người dùng": "User", ":Bộ xử lý văn bản": ":Text Processor",
    # 3.6
    "Xác nhận và thực hiện đặt hàng qua AI Chatbot": "Order confirmation and execution via the AI Chatbot",
    "Yêu cầu đặt sản phẩm": "Request to order products",
    "Gửi yêu cầu và ngữ cảnh": "Send request and context",
    "Đọc giỏ hàng và tạo báo giá": "Read cart and create quote",
    "Quote và thông tin cần xác nhận": "Quote and details to confirm",
    "Hiển thị tóm tắt đơn hàng": "Show order summary",
    "Yêu cầu xác nhận": "Ask for confirmation",
    "Xác nhận đặt hàng": "Confirm order",
    "Gửi xác nhận": "Send confirmation",
    "Yêu cầu thực thi với quote": "Execute with quote",
    "Xác thực và nhận quyền xử lý một lần": "Authenticate and claim one-time execution",
    "Kiểm tra lại giá và tồn kho": "Re-check price and stock",
    "Kết quả kiểm tra": "Check result",
    "Tạo đơn với idempotency key": "Create order with idempotency key",
    "Kết quả tạo đơn": "Order creation result",
    "Trạng thái xử lý": "Processing status",
    "Trả kết quả": "Return result",
    "Thông báo trạng thái đơn hàng": "Notify order status",
    # 4.2
    "Tiền xử lý, Chunking, embedding và lập chỉ mục": "Preprocessing, chunking, embedding and indexing",
    "Đọc dữ liệu sản phẩm": "Read product data",
    "Dữ liệu sản phẩm": "Product data",
    "Kiểm tra và chuẩn hóa": "Validate and normalize",
    "Văn bản đã xử lý": "Processed text",
    "Tạo các đơn vị truy xuất (chunk)": "Create retrieval units (chunks)",
    "Gửi nội dung cần vector hóa": "Send content to embed",
    "Upsert vector và metadata": "Upsert vectors and metadata",
    "Kết quả lập chỉ mục": "Indexing result",
    # 4.3
    "Tư vấn sản phẩm thông qua Agentic RAG": "Product consultation via Agentic RAG",
    "“Tìm loa Bluetooth dưới 2 triệu, pin lâu”": "“Bluetooth speaker under 2M VND, long battery”",
    "Gửi tin nhắn và session context": "Send message and session context",
    "Điều phối yêu cầu sản phẩm": "Route product request",
    "Tìm kiếm theo tiêu chí": "Search by criteria",
    "Danh sách ứng viên": "Candidate list",
    "Đọc thông tin sản phẩm hiện tại": "Read current product data",
    "Giá và thông tin sản phẩm": "Price and product details",
    "Truy vấn + ngữ cảnh đã xác minh": "Query + verified context",
    "Nội dung tư vấn": "Recommendation text",
    "Kết quả xử lý": "Processing result",
    "Câu trả lời và dữ liệu liên quan": "Answer and related data",
    "Hiển thị kết quả": "Display result",
    # 3.2
    "Điều phối các nhánh xử lý trong LangGraph": "Branch orchestration in LangGraph",
    "Nhận tin nhắn và State": "Receive message and State",
    "Ý định?": "Intent?",
    "Retrieval + kiểm tra sản phẩm": "Retrieval + product check",
    "Truy xuất thông tin chính sách": "Retrieve policy information",
    "Loại thao tác?": "Operation type?",
    "Đọc dữ liệu nghiệp vụ": "Read business data",
    "Kiểm tra quyền và xác nhận": "Check permission and confirm",
    "Thực thi qua Service": "Execute via service",
    "Tổng hợp kết quả": "Aggregate results",
    "Cập nhật State / Checkpoint": "Update State / Checkpoint",
    "Trả lời người dùng": "Reply to user",
    "sản phẩm": "product", "chính sách": "policy", "giỏ hàng / đơn hàng": "cart / order",
    "tra cứu": "lookup", "thay đổi trạng thái": "state change",
    # 3.3
    "Hybrid Retrieval và tạo câu trả lời": "Hybrid retrieval and answer generation",
    "Nhận truy vấn tiếng Việt": "Receive Vietnamese query",
    "Chuẩn hóa truy vấn": "Normalize query",
    "Bật Reranker?": "Reranker enabled?",
    "Nhóm theo Product ID": "Group by product ID",
    "Lấy thông tin sản phẩm hiện tại": "Fetch current product data",
    "Xây dựng ngữ cảnh": "Build context",
    "LLM tạo câu trả lời": "LLM generates answer",
    "Trả kết quả cho Chatbot": "Return result to chatbot",
    "có": "yes", "không": "no",
    # 4.4
    "Kiểm soát xác nhận và thực thi đặt hàng an toàn": "Safe order confirmation and execution control",
    "Yêu cầu đặt hàng": "Request to place order",
    "Chuẩn bị thông tin giao dịch": "Prepare transaction details",
    "Tạo Quote có thời hạn": "Create time-limited quote",
    "Người dùng xác nhận?": "User confirms?",
    "Hủy hoặc tiếp tục hội thoại": "Cancel or continue chat",
    "Kiểm tra xác thực / quyền": "Check authentication / permission",
    "Quote còn hiệu lực?": "Quote still valid?",
    "Atomic Claim một lần": "One-time atomic claim",
    "Claim hợp lệ?": "Claim valid?",
    "Từ chối thực thi lại": "Reject re-execution",
    "Thông tin hợp lệ?": "Data still valid?",
    "Yêu cầu lập báo giá mới": "Request a new quote",
    "Checkout với Idempotency Key": "Checkout with idempotency key",
    "Order Service tạo đơn": "Order Service creates order",
    "Trả trạng thái đơn hàng": "Return order status",
    # 3.4
    "Chunking và tạo dữ liệu vector sản phẩm": "Chunking and product vector generation",
    "Tên sản phẩm": "Product name", "Mô tả sản phẩm": "Description",
    "Thuộc tính kỹ thuật": "Technical attributes", "Thông tin biến thể": "Variant information",
    "Chuẩn hóa\ndữ liệu": "Normalize\ndata",
    "Chunking theo\ncấu hình hệ thống": "Chunking by\nsystem config",
    "CÁC CHUNK": "CHUNKS",
    "Gắn Product ID\n/ Metadata": "Attach product ID\n/ metadata",
    "Tạo\nEmbedding": "Create\nembeddings",
    "Bước trọng tâm": "Focal step", "Bước xử lý": "Processing step", "Lưu trữ": "Storage",
    "Dữ liệu đầu vào": "Input data", "Đọc / ghi trạng thái": "State read / write",
    # 3.5
    "Quản lý ngữ cảnh hội thoại bằng LangGraph State và Checkpoint":
        "Conversation context management with LangGraph State and Checkpoint",
    "GHI CHECKPOINT": "WRITE CHECKPOINT", "ĐỌC THEO SESSION": "READ BY SESSION",
    "Tin nhắn mới": "New message", "Khôi phục State": "Restore State",
    "Kết hợp ngữ cảnh cũ\nvà thông tin mới": "Merge prior context\nwith new input",
    "Cập nhật trạng thái": "Update state", "Lưu Checkpoint": "Save checkpoint", "Phản hồi": "Response",
    # engine legends
    "CHÚ GIẢI": "LEGEND", "Bắt đầu": "Start", "Kết thúc": "End", "Hành động": "Action",
    "Quyết định / Hợp nhất": "Decision / Merge", "Luồng điều khiển [guard]": "Control flow [guard]",
    "Thông điệp đồng bộ": "Synchronous message", "Bất đồng bộ (Kafka/sự kiện)": "Asynchronous message",
    "Thông điệp trả về": "Return message",
}


def tr(s):
    if not isinstance(s, str):
        return s
    if s in TR:
        return TR[s]
    if s.startswith("$") and s[1:] in TR:
        return "$" + TR[s[1:]]
    return s


def deep(v):
    if isinstance(v, dict):
        return {k: deep(x) for k, x in v.items()}
    if isinstance(v, list):
        return [deep(x) for x in v]
    if isinstance(v, tuple):
        return tuple(deep(x) for x in v)
    return tr(v)


# Route every remaining drawn string (legends, hand-laid boxes) through the dictionary.
_text, _label, _legend, _box = engine.text, engine.label, engine.legend, build.box


def text_en(x, y, s, *a, **k):
    return _text(x, y, tr(s), *a, **k)


def label_en(x, y, s, *a, **k):
    return _label(x, y, tr(s), *a, **k)


def legend_en(items, *a, **k):
    return _legend([(fn, tr(lab)) for fn, lab in items], *a, **k)


def box_en(x, y, w, h, name, sub=None, kind="backend"):
    return _box(x, y, w, h, tr(name), tr(sub), kind)


for mod in (engine, build):
    mod.text, mod.label, mod.legend = text_en, label_en, legend_en
build.box = box_en


def write(slug, fig, title, kind, w, h, body):
    fig = fig.replace("Hình", "Figure")
    html = engine.page(slug, f"{fig} · {kind}", f"{fig}. {title}", f"{fig}: {title}.", w, h, body)
    html = html.replace('<p class="nav"><a href="index.html">← Mục lục</a></p>', "")
    html = html.replace('<html lang="vi">', '<html lang="en">')
    (OUT / f"{slug}.html").write_text(html, encoding="utf-8")
    print(slug)


def main():
    OUT.mkdir(exist_ok=True)
    for slug, fig, title, spec in build.SEQUENCES:
        spec = deep(copy.deepcopy(spec))
        spec["title"] = tr(title)
        write(slug, fig, tr(title), "Sequence diagram", *engine.build_sequence(spec))
    for slug, fig, title, spec in build.ACTIVITIES:
        spec = deep(copy.deepcopy(spec))
        spec["title"] = tr(title)
        write(slug, fig, tr(title), "Activity diagram", *engine.build_activity(spec))
    for slug, fig, title, fn in build.HAND:
        write(slug, fig, tr(title), "Data flow", *fn())


if __name__ == "__main__":
    main()
