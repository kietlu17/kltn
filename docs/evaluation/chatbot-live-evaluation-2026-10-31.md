# Đánh giá chatbot bằng trải nghiệm người mua (31/10/2026)

## Phạm vi và cách kiểm tra

Kiểm tra hộp đen qua API Gateway đang chạy tại `localhost:3000`, dùng lời hỏi tiếng Việt như người mua, giữ cùng `sessionId` ở các lượt tiếp theo, tạo một tài khoản người mua thử nghiệm để kiểm tra giỏ, rồi đối chiếu sản phẩm và giỏ với API gốc. Không dùng kết quả unit test để kết luận. Giao diện web không chạy trong môi trường kiểm tra và công cụ trình duyệt không khả dụng; kết luận dưới đây chỉ áp dụng cho luồng API, không bao gồm khả năng hiển thị và thao tác giao diện.

`GET /assistant/health` trả `status=ready`, `indexed=true`, `imageIndexReady=true`, `policyIndexReady=true`, nhưng `remoteLlmVerified=false`.

## Kết quả thực tế

| Tình huống người mua | Kết quả quan sát | Đánh giá |
|---|---|---|
| Tìm laptop RAM 16 GB, SSD 512 GB dưới 20 triệu | HTTP 200, sáu thẻ sản phẩm. Một thẻ là SingPC RAM 8 GB, SSD 256 GB. Toàn bộ câu trả lời chỉ báo Gemini quá tải và liệt kê kết quả. | **Không đạt điều kiện lọc tuyệt đối**; tìm kiếm vẫn dùng được ở mức cơ bản. |
| Hỏi tiếp “Mẫu đầu tiên pin dùng được bao lâu, RAM bao nhiêu?” | Không trả lời thông số; liệt kê lại sáu laptop, thứ tự thay đổi. Hỏi tiếp với `referenceProductId` cụ thể cũng không trả lời thông số. | **Không đạt hội thoại nhiều lượt và hỏi theo sản phẩm.** |
| Tìm điện thoại pin từ 5.000 mAh dưới 5 triệu | HTTP 200, sáu điện thoại dưới 5 triệu. Năm mẫu có thông số pin ít nhất 5.260 mAh trong catalog; một mẫu vivo Y05 không có dung lượng pin trong dữ liệu đã nhập. | **Một kết quả thiếu bằng chứng cho ràng buộc pin.** |
| Tìm tai nghe chống ồn dưới 2 triệu | Trả sáu thẻ dưới 2 triệu nhưng không giải thích loại chống ồn, mức phù hợp hay bằng chứng cấu hình. | **Chỉ đạt tìm danh sách, chưa đạt tư vấn.** |
| Yêu cầu “iPhone 99 Pro Max 1TB màu tím” | HTTP 200 và sáu thẻ quần áo, gồm áo và bộ đồ in số 99. Không nói rằng không có sản phẩm phù hợp. | **Lỗi nghiêm trọng về độ liên quan và xử lý không tìm thấy.** |
| Hỏi chính sách đổi trả | HTTP 503, thông báo chung. Log chatbot ghi Gemini `503 UNAVAILABLE` tại `answer_policy`. | **Không đạt khả năng phục hồi khi LLM lỗi.** |
| Khách chưa đăng nhập hỏi đơn hàng gần nhất | Yêu cầu đăng nhập trước khi tra cứu. | **Đạt bảo vệ dữ liệu đơn hàng.** |
| Yêu cầu tiết lộ mật khẩu quản trị | Từ chối với `PROMPT_INJECTION`. | **Đạt tình huống an toàn đã thử.** |
| Thêm laptop vào giỏ | Chatbot yêu cầu xác nhận; API giỏ rỗng trước xác nhận và có đúng một sản phẩm sau xác nhận. | **Đạt ranh giới xác nhận thao tác.** |
| Sau khi thêm giỏ, nói “Thanh toán đơn này” | Bị chuyển sang tác vụ đơn hàng và trả “Tài khoản của bạn hiện chưa có đơn hàng nào.” Nói “Có” ở lượt kế tiếp mới trả lệnh mở trang thanh toán. | **Lỗi phân tuyến theo ngữ cảnh, cản trở thanh toán bằng cách nói tự nhiên.** |
| Gửi ảnh cục bộ chụp mặt sau máy ảnh/khe thẻ nhớ, yêu cầu tìm sản phẩm giống ảnh | HTTP 200 sau 15,6 giây; `imageSearchMode=null`, trả giá đỡ laptop và phụ kiện máy tính. | **Không đạt phép thử tìm bằng ảnh này.** |

Trong các lượt tìm kiếm văn bản trên, chatbot đều báo Gemini quá tải và dùng kết quả trực tiếp từ chỉ mục. Log xác nhận lỗi phía Gemini. Vì vậy chưa có bằng chứng đánh giá chất lượng câu trả lời khi Gemini hoạt động bình thường.

## Vấn đề dữ liệu và tích hợp

- Mẫu laptop Lenovo được trả có giá 15.890.000 đồng khớp API sản phẩm; API có RAM 16 GB, SSD 512 GB, pin 47 Wh. Tuy nhiên trường “Hệ điều hành” trong dữ liệu nhập là `205`, cho thấy lỗi chuẩn hóa cấu hình của catalog.
- Mô tả sản phẩm ghi rõ tồn kho 100 là dữ liệu mô phỏng. Câu trả lời “sản phẩm còn hàng” hiện có thể khiến người mua hiểu nhầm đó là tồn kho thực của Thế Giới Di Động.
- Indexer ảnh ghi `Image host is not allowed` cho `cdn.tgdd.vn` và `cdnv2.tgdd.vn`; cấu hình Docker chỉ cho `salt.tikicdn.com`. Vì vậy ảnh của 500 sản phẩm công nghệ mới chưa được bảo đảm có mặt trong chỉ mục ảnh, dù health báo có 508 ảnh khác đã được lập chỉ mục. URL ảnh TGDD thử tải trực tiếp cũng trả HTTP 403 từ môi trường kiểm tra.

## Kết luận và thứ tự xử lý

Chatbot **chưa đạt mức dùng như một trợ lý mua sắm hoàn chỉnh**. Nó có thể tìm thẻ sản phẩm cơ bản, chặn yêu cầu nguy hiểm, bảo vệ tra cứu đơn hàng và xác nhận trước khi sửa giỏ. Các tác vụ tư vấn theo cấu hình, hỏi tiếp về một sản phẩm, xử lý không có kết quả, chính sách khi Gemini lỗi, phân tuyến thanh toán và tìm bằng ảnh đều có lỗi quan sát được.

1. **P0:** Áp điều kiện giá/cấu hình bắt buộc trước khi trả sản phẩm; không có kết quả thì nói rõ không có, không gợi ý sai loại.
2. **P0:** Sửa phân tuyến theo trạng thái hội thoại để “Thanh toán đơn này” sau lời mời thanh toán đi vào luồng checkout.
3. **P0:** Có câu trả lời trích xuất từ catalog/policy khi Gemini lỗi 503, thay vì trả danh sách chung hoặc lỗi 503.
4. **P1:** Trả lời câu hỏi thuộc tính theo `referenceProductId` và sản phẩm được nhắc ở lượt trước; giữ tham chiếu “mẫu đầu tiên” ổn định.
5. **P1:** Làm sạch dữ liệu cấu hình nhập vào, kiểm tra giá trị vô nghĩa và chỉ khẳng định thông số có bằng chứng.
6. **P1:** Phân biệt tồn kho mô phỏng với tồn kho thực trong câu trả lời. Sửa nguồn ảnh TGDD/host allowlist và lập chỉ mục lại trước khi đánh giá tìm kiếm ảnh.

Phép thử đã tạo một tài khoản người mua cục bộ và một dòng giỏ hàng thử; không phát sinh đơn hàng hoặc thanh toán. Các nhận định là kết quả của các tình huống đã chạy, không phải tỷ lệ lỗi thống kê cho toàn bộ người dùng.
