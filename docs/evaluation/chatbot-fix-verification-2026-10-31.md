# Kiểm chứng chatbot sau khi sửa — 31/10/2026

## Phạm vi

Kiểm tra qua API Gateway đang chạy với catalog thật trong môi trường phát triển. Các ca dưới đây dùng phản hồi thực tế của chatbot và các dịch vụ giỏ hàng/đơn hàng, không lấy kết quả unit test làm bằng chứng chính.

## Kết quả quan sát

| Tình huống người mua | Kết quả |
| --- | --- |
| Laptop RAM 16 GB, SSD 512 GB, dưới 20 triệu | 6 gợi ý; mọi sản phẩm trả về có RAM và SSD đúng trong thông số. |
| Điện thoại pin từ 5000 mAh, dưới 5 triệu | 6 gợi ý với dung lượng pin được ghi rõ; sản phẩm thiếu dữ liệu pin bị loại. |
| Loa Bluetooth từ 20 W, dưới 1 triệu | 6 loa có công suất 20 W hoặc 30 W theo thông số. |
| Bình nước khoảng 500 mL | 3 sản phẩm 500 mL; câu hỏi bình giữ nhiệt 500 mL không bị thay bằng bình nước thường. |
| Áo thun nữ dưới 200 nghìn | 6 sản phẩm đúng nhóm hàng; chatbot không bị giới hạn ở hàng công nghệ. |
| Mẫu “iPhone 99 Pro Max” không có trong sàn | Không bịa sản phẩm hoặc mã máy. |
| Hỏi tiếp pin và RAM của laptop vừa xem | Giữ đúng sản phẩm tham chiếu, trả lời pin 50 Wh và RAM 16 GB từ thông số. |
| Tìm bằng ảnh MacBook từ CDN TGDD | API trả 200 và dùng chế độ `text_and_image_vector`, kết quả gồm MacBook Neo/MacBook Air. |
| Hỏi chính sách chung của sàn | Trả 200, nói rõ kho tài liệu chỉ có chính sách Shopee tham khảo, chưa xác minh chính sách riêng của sàn. |
| Thêm laptop rồi yêu cầu “Thanh toán đơn này” | Trước xác nhận giỏ có 0 món; sau xác nhận có 1 món; chatbot trả `open_checkout` với đúng `selectedProductIds`; số đơn vẫn bằng 0 trước khi người mua thao tác ở trang checkout. |
| So sánh Monster FORCE và AW-Ride, rồi hỏi hai lần “cái nào nhỏ gọn để bàn học” | Mỗi lần đều chọn AW-Ride dựa trên khối lượng 0,313 kg so với 2 kg; không lặp bảng so sánh hoặc thẻ sản phẩm. |

## Dữ liệu và trạng thái triển khai

- Đã sửa 226/500 bản ghi sản phẩm công nghệ TGDD có thông số nhập sai dạng số đơn lẻ; không thêm bản ghi trùng.
- Collection ảnh có ít nhất 693 vector thuộc shop TGDD sau khi lập chỉ mục lại; dịch vụ ảnh đang chạy và API health trả `ready`, `imageIndexReady: true`.
- Thanh toán thực tế được thực hiện ở trang `/checkout`; chatbot chỉ chuyển người mua cùng danh sách sản phẩm đã chọn. Chưa thực hiện giao dịch thanh toán tiền trong đợt kiểm chứng này.

## Hồi quy

- Biên dịch Python, kiểm tra cú pháp script nhập dữ liệu, cấu hình Docker Compose và `git diff --check` đều đạt.
- 66 kiểm thử liên quan đạt; kết luận chất lượng ở trên vẫn dựa trên thử nghiệm qua API Gateway.
- Hai kiểm thử cũ từng kỳ vọng mọi lỗi Gemini đều được gọi là “quá tải” và chính sách Shopee được dùng để khẳng định chính sách sàn. Đã điều chỉnh các kỳ vọng đó theo hành vi hiện tại: nói rõ Gemini không khả dụng và không gán chính sách bên thứ ba cho sàn.
- Trong lượt thử bốn bước, câu gợi ý ban đầu dùng phản hồi dự phòng vì Gemini tạm không khả dụng; các bước so sánh và chọn mẫu vẫn trả 200 và dùng dữ liệu catalog.
