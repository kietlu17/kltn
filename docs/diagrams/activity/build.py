"""Activity diagrams for use cases 4.3.1 – 4.3.15 (PNG output).

    python docs/diagrams/activity/build.py
    node docs/diagrams/uml/render_png.cjs --dir activity
"""
from __future__ import annotations

import copy
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uml"))

from engine import build_activity, page  # noqa: E402
from specs import USECASES, E, act, dec, fin, ini, mrg  # noqa: E402

REUSE = {u["slug"]: u["activity"] for u in USECASES}


def ff(lane, row, **kw):
    return dict(k="flowfinal", lane=lane, row=row, **kw)


DIAGRAMS = [
    ("4-3-1-dang-ky-tai-khoan", "4.3.1 Đăng ký tài khoản", dict(
        lanes=["Khách", "Hệ thống"], lws=[340, 400],
        nodes=dict(
            i=ini(0, 0), a1=act(0, 1, "Mở trang Đăng ký"), m0=mrg(0, 2),
            a2=act(0, 3, "Nhập email, mật khẩu, chọn vai trò"),
            d0=dec(0, 4, "Vai trò?", tside="r"),
            a3=act(0, 5.2, "Nhập tên gian hàng, mã số thuế", dx=85, w=150),
            m1=mrg(0, 6.4),
            a4=act(0, 7.4, "Gửi đăng ký"),
            s1=act(1, 8.4, "Kiểm tra dữ liệu, email trùng"),
            d1=dec(1, 9.4, "Hợp lệ?", tside="r"),
            s2=act(1, 10.4, "Băm mật khẩu, tạo tài khoản"),
            d2=dec(1, 11.4, "Vai trò?", tside="r"),
            s3=act(1, 12.6, "Tạo hồ sơ người dùng", dx=-100, w=170),
            s4=act(1, 12.6, "Tạo gian hàng, gắn shopId", dx=100, w=170),
            m2=mrg(1, 13.8),
            a5=act(0, 14.8, "Nhận thông báo, chuyển tới Đăng nhập", focal=True),
            f=fin(0, 15.8)),
        edges=[
            E("i", "a1"), E("a1", "m0"), E("m0", "a2"), E("a2", "d0"),
            E("d0", "m1", "người mua"),
            E("d0", "a3", "người bán", fp="r", tp="t", gpos="end"),
            E("a3", "m1", fp="b", tp="r"),
            E("m1", "a4"), E("a4", "s1"), E("s1", "d1"),
            E("d1", "m0", "không", fp="l", tp="l", chan=44),
            E("d1", "s2", "có"), E("s2", "d2"),
            E("d2", "s3", "người mua", fp="l", tp="t", gpos="end-l"),
            E("d2", "s4", "người bán", fp="r", tp="t", gpos="end"),
            E("s3", "m2", fp="b", tp="l"), E("s4", "m2", fp="b", tp="r"),
            E("m2", "a5", fp="l", tp="t"), E("a5", "f"),
        ])),
    ("4-3-2-dang-nhap", "4.3.2 Đăng nhập", dict(
        lanes=["Người dùng", "Hệ thống"], lws=[360, 380],
        nodes=dict(
            i=ini(0, 0), m0=mrg(0, 1), a1=act(0, 2, "Nhập email, mật khẩu"),
            s1=act(1, 3, "Tìm tài khoản, so khớp mật khẩu"),
            d1=dec(1, 4, "Đúng thông tin?", tside="r"),
            d2=dec(1, 5.2, "Tài khoản bị khóa?", tside="r"),
            a2=act(0, 6.2, "Nhận thông báo tài khoản bị khóa", dx=-80, w=170),
            x1=fin(0, 7.2, dx=-80),
            s2=act(1, 6.8, "Ký JWT (userId, role, shopId, tokenVersion)", focal=True),
            a3=act(0, 8.2, "Lưu token, vào trang theo vai trò", dx=60, w=200),
            f=fin(0, 9.2, dx=60)),
        edges=[
            E("i", "m0"), E("m0", "a1"), E("a1", "s1"), E("s1", "d1"),
            E("d1", "m0", "sai", fp="l", tp="l", chan=44),
            E("d1", "d2", "đúng"),
            E("d2", "a2", "có", fp="l", tp="t", gpos="mid"), E("a2", "x1"),
            E("d2", "s2", "không"),
            E("s2", "a3", fp="l", tp="t"), E("a3", "f"),
        ])),
    ("4-3-3-duyet-tim-kiem-san-pham", "4.3.3 Duyệt và tìm kiếm sản phẩm", dict(
        lanes=["Người mua", "Hệ thống"], lws=[340, 380],
        nodes=dict(
            i=ini(0, 0), a1=act(0, 1, "Mở trang chủ"),
            s1=act(1, 2, "Tải danh mục và sản phẩm nổi bật"),
            m0=mrg(0, 3),
            a2=act(0, 4, "Nhập từ khóa / chọn danh mục / sắp xếp"),
            s2=act(1, 5, "Lọc sản phẩm đã duyệt, sắp xếp, phân trang"),
            a3=act(0, 6, "Xem kết quả (hoặc thông báo không có)"),
            d1=dec(0, 7, "Xem chi tiết?", tside="r"),
            a4=act(0, 8, "Chọn một sản phẩm"),
            s3=act(1, 9, "Lấy chi tiết, biến thể, thông số, đánh giá", focal=True),
            a5=act(0, 10, "Xem chi tiết, chọn biến thể"),
            f=fin(0, 11)),
        edges=[
            E("i", "a1"), E("a1", "s1"), E("s1", "m0", fp="l", tp="t"), E("m0", "a2"),
            E("a2", "s2"), E("s2", "a3", fp="l", tp="t"), E("a3", "d1"),
            E("d1", "m0", "tìm tiếp", fp="l", tp="l", chan=44, gpos="mid"),
            E("d1", "a4", "có"), E("a4", "s3"), E("s3", "a5", fp="l", tp="t"), E("a5", "f"),
        ])),
    ("4-3-4-tro-ly-mua-sam", "4.3.4 Tương tác với trợ lý mua sắm", dict(
        lanes=["Người mua", "Trợ lý mua sắm (chatbot-service)"], lws=[340, 500],
        nodes=dict(
            i=ini(0, 0), a1=act(0, 1, "Mở trợ lý mua sắm"), m0=mrg(0, 2),
            a2=act(0, 3, "Gửi câu hỏi / ảnh / giọng nói"),
            s1=act(1, 4, "Hiểu ý định bằng LLM"),
            d1=dec(1, 5, "Ý định?", tside="r"),
            r1=act(1, 6.4, "Tìm kiếm lai, lấy giá và tồn kho", dx=-160, w=150),
            p1=act(1, 6.4, "Truy xuất chính sách", w=130),
            c1=act(1, 6.4, "Tạo pendingAction (chưa ghi)", dx=160, w=150),
            m1=mrg(1, 7.8, dx=-80),
            s2=act(1, 8.8, "Sinh câu trả lời có trích dẫn", dx=-80, w=200),
            a3=act(0, 10, "Xem câu trả lời, thẻ sản phẩm"),
            d2=dec(0, 11, "Hỏi tiếp?", tside="r"),
            f=fin(0, 12, dx=-110),
            a4=act(0, 13.2, "Xem thẻ xác nhận"),
            d3=dec(0, 14.2, "Xác nhận?", tside="t"),
            x1=fin(0, 14.2, dx=-110),
            s3=act(1, 15.4, "Ghi giỏ hàng / tạo đơn (idempotent)", focal=True),
            a5=act(0, 16.6, "Xem kết quả thao tác"),
            f2=fin(0, 17.6)),
        edges=[
            E("i", "a1"), E("a1", "m0"), E("m0", "a2"), E("a2", "s1"), E("s1", "d1"),
            E("d1", "r1", "tìm sản phẩm", fp="l", tp="t", gpos="end-l"),
            E("d1", "p1", "chính sách", gpos="end-l"),
            E("d1", "c1", "giỏ / đặt hàng", fp="r", tp="t", gpos="end-l"),
            E("r1", "m1", fp="b", tp="l"), E("p1", "m1", fp="b", tp="r"),
            E("m1", "s2"), E("s2", "a3", fp="l", tp="t"), E("a3", "d2"),
            E("d2", "m0", "có", fp="l", tp="l", chan=44, gpos="mid"),
            E("d2", "f", "không", fp="b", tp="t", gpos="left"),
            E("c1", "a4", fp="b", tp="t", mid=(13.2 - 0.5) * 64 + 112 + 16 - 12),
            E("a4", "d3"),
            E("d3", "x1", "hủy", fp="l", tp="r"),
            E("d3", "s3", "đồng ý"), E("s3", "a5", fp="l", tp="t"), E("a5", "f2"),
        ])),
    ("4-3-5-quan-ly-gio-hang", "4.3.5 Quản lý giỏ hàng", REUSE["b3-gio-hang"]),
    ("4-3-6-dat-hang", "4.3.6 Đặt hàng", dict(
        lanes=["Người mua", "Order Service", "Inventory · Voucher"], lws=[320, 380, 280],
        nodes=dict(
            i=ini(0, 0), a1=act(0, 1, "Mở giỏ, chọn sản phẩm cần mua"), m0=mrg(0, 2),
            a2=act(0, 3, "Chọn địa chỉ, voucher, phương thức"),
            a3=act(0, 4, "Bấm Đặt hàng"),
            s1=act(1, 5, "Kiểm tra idempotencyKey, tính tổng tiền"),
            s2=act(2, 6, "Giữ tồn kho (reserve)"),
            d1=dec(2, 7, "Đủ hàng?", tside="r"),
            d2=dec(1, 8.2, "Có mã voucher?", tside="r"),
            s4=act(2, 9.2, "Giữ voucher (reserve)"),
            d3=dec(2, 10.2, "Voucher hợp lệ?", tside="r"),
            m2=mrg(1, 11.2),
            sE=act(1, 12.4, "Nhả phần đã giữ, trả lỗi 409", dx=-100, w=160),
            s6=act(1, 13.6, "Lưu đơn pending_payment, phát order.created", focal=True),
            a4=act(0, 14.8, "Xem đơn vừa đặt, chuyển sang thanh toán"),
            f=fin(0, 15.8)),
        edges=[
            E("i", "a1"), E("a1", "m0"), E("m0", "a2"), E("a2", "a3"), E("a3", "s1"),
            E("s1", "s2"), E("s2", "d1"),
            E("d1", "sE", "không", fp="l", tp="t", gpos="mid"),
            E("d1", "d2", "có", fp="b", tp="t"),
            E("d2", "s4", "có", fp="r", tp="t", gpos="end"),
            E("d2", "m2", "không"),
            E("s4", "d3"),
            E("d3", "sE", "không", fp="l", tp="t:30", gpos="mid"),
            E("d3", "m2", "có", fp="b", tp="r"),
            E("m2", "s6"),
            E("sE", "m0", fp="l", tp="l", chan=44),
            E("s6", "a4", fp="l", tp="t"), E("a4", "f"),
        ])),
    ("4-3-7-thanh-toan-don-hang", "4.3.7 Thanh toán đơn hàng", dict(
        lanes=["Người mua", "Payment · Gateway · Wallet", "Order Service"], lws=[300, 500, 320],
        nodes=dict(
            i=ini(2, 0), o1=act(2, 1, "Đơn pending_payment, phát order.created"),
            s1=act(1, 2, "Nhận order.created"),
            d1=dec(1, 3, "Phương thức?", tside="r"),
            q1=act(1, 4.4, "Tạo mã QR SePay", dx=-160, w=150),
            c1=act(1, 4.4, "Ghi nhận thu hộ (COD)", w=130),
            w1=act(1, 4.4, "Trừ số dư ví, ghi sổ cái", dx=160, w=150),
            dw=dec(1, 5.6, "Đủ số dư?", tside="l", dx=160),
            a1=act(0, 5.6, "Quét QR, chuyển khoản qua ngân hàng"),
            q2=act(1, 6.8, "Nhận webhook, đối soát số tiền", dx=-160, w=150),
            dq=dec(1, 8, "Khớp và còn hạn?", tside="r", dx=-160),
            o3=act(2, 6.8, "payment_failed: hủy đơn, nhả hàng và voucher", dx=-30, w=200),
            x1=fin(2, 6.8, dx=110),
            mS=mrg(1, 9.4),
            o2=act(2, 10.4, "Cập nhật paid / chờ COD, commit tồn kho và voucher", focal=True),
            a2=act(0, 11.6, "Xem đơn đã thanh toán"),
            f=fin(0, 12.6)),
        edges=[
            E("i", "o1"), E("o1", "s1", fp="l", tp="t"), E("s1", "d1"),
            E("d1", "q1", "chuyển khoản", fp="l", tp="t", gpos="end-l"),
            E("d1", "c1", "COD"),
            E("d1", "w1", "ví", fp="r", tp="t", gpos="end"),
            E("w1", "dw"),
            E("q1", "a1", fp="l", tp="t"), E("a1", "q2", fp="r", tp="t"), E("q2", "dq"),
            E("dw", "o3", "không", fp="r", tp="t:-40", gpos="mid"),
            E("dq", "o3", "không", fp="r", tp="b", gpos="mid"),
            E("o3", "x1", fp="r", tp="l"),
            E("dq", "mS", "có", fp="b", tp="l"),
            E("dw", "mS", "có", fp="b", tp="r"),
            E("c1", "mS"),
            E("mS", "o2", fp="r", tp="t"),
            E("o2", "a2", fp="l", tp="t"), E("a2", "f"),
        ])),
    ("4-3-8-quan-ly-san-pham-ton-kho", "4.3.8 Quản lý sản phẩm và tồn kho", dict(
        lanes=["Người bán", "Product Service", "Inventory Service"], lws=[340, 400, 320],
        nodes=dict(
            i=ini(0, 0), a1=act(0, 1, "Vào Kênh người bán"), m0=mrg(0, 2),
            d0=dec(0, 3, "Thao tác?", tside="r"),
            a2=act(0, 4.2, "Nhập thông tin, biến thể, giá, ảnh", dx=-60, w=150),
            a5=act(0, 4.2, "Nhập số lượng tồn mới", dx=90, w=140),
            i1=act(2, 5.4, "Cập nhật stockOnHand", dx=80, w=140),
            s1=act(1, 5.4, "Kiểm tra dữ liệu bắt buộc"),
            dv=dec(1, 6.4, "Hợp lệ?", tside="r"),
            s2=act(1, 7.4, "Lưu ảnh (MinIO) và sản phẩm"),
            s3=act(1, 8.4, "Kiểm duyệt từ khóa tự động"),
            dm=dec(1, 9.4, "Vi phạm?", tside="r"),
            s4=act(1, 10.6, "Đặt pending, chờ admin duyệt", dx=-100, w=170),
            s5=act(1, 10.6, "Đặt approved, hiển thị công khai", dx=100, w=170),
            mm=mrg(1, 11.8),
            i2=act(2, 12.8, "Khởi tạo / đồng bộ tồn kho (product.created)", dx=-50, w=160, focal=True),
            mE=mrg(0, 14),
            a6=act(0, 15, "Xem trạng thái sản phẩm và tồn kho"),
            dq=dec(0, 16, "Tiếp tục?", tside="r"),
            f=fin(0, 17)),
        edges=[
            E("i", "a1"), E("a1", "m0"), E("m0", "d0"),
            E("d0", "a2", "sản phẩm", fp="l", tp="t", gpos="end-l"),
            E("d0", "a5", "tồn kho", fp="r", tp="t", gpos="end"),
            E("a5", "i1", fp="r", tp="t"),
            E("a2", "s1", fp="b", tp="t"),
            E("s1", "dv"),
            E("dv", "a2", "không", fp="l", tp="l", chan=56),
            E("dv", "s2", "có"), E("s2", "s3"), E("s3", "dm"),
            E("dm", "s4", "có", fp="l", tp="t", gpos="end-l"),
            E("dm", "s5", "không", fp="r", tp="t", gpos="end"),
            E("s4", "mm", fp="b", tp="l"), E("s5", "mm", fp="b", tp="r"),
            E("mm", "i2", fp="r", tp="t"),
            E("i2", "mE", fp="l", tp="t"),
            E("i1", "mE", fp="b", tp="r"),
            E("mE", "a6"), E("a6", "dq"),
            E("dq", "m0", "có", fp="l", tp="l", chan=40, gpos="mid"),
            E("dq", "f", "không"),
        ])),
    ("4-3-9-kiem-duyet-san-pham", "4.3.9 Kiểm duyệt sản phẩm", REUSE["a2-kiem-duyet-san-pham"]),
    ("4-3-10-xu-ly-don-cua-cua-hang", "4.3.10 Xem và xử lý đơn hàng của cửa hàng", REUSE["s2-don-cua-gian-hang"]),
    ("4-3-11-xem-don-theo-doi-giao-hang", "4.3.11 Xem đơn hàng và theo dõi giao hàng", dict(
        lanes=["Người mua", "Hệ thống"], lws=[360, 380],
        nodes=dict(
            i=ini(0, 0), a1=act(0, 1, "Mở Đơn hàng của tôi"),
            s1=act(1, 2, "Lấy danh sách đơn của người mua"),
            m0=mrg(0, 3),
            a2=act(0, 4, "Lọc theo trạng thái, chọn đơn"),
            a3=act(0, 5, "Bấm Theo dõi vận chuyển"),
            s2=act(1, 6, "Kiểm tra quyền sở hữu, lấy vận đơn"),
            d1=dec(1, 7, "Đã có vận đơn?", tside="r"),
            a4=act(0, 8, "Xem trạng thái: chờ tạo vận đơn", dx=-85, w=160),
            a5=act(0, 8, "Xem hành trình và mốc thời gian", dx=90, w=150, focal=True),
            m1=mrg(0, 9.2),
            d2=dec(0, 10.2, "Xem đơn khác?", tside="r"),
            f=fin(0, 11.2)),
        edges=[
            E("i", "a1"), E("a1", "s1"), E("s1", "m0", fp="l", tp="t"), E("m0", "a2"), E("a2", "a3"),
            E("a3", "s2"), E("s2", "d1"),
            E("d1", "a4", "chưa", fp="l", tp="t", gpos="mid"),
            E("d1", "a5", "có", fp="b", tp="r"),
            E("a4", "m1", fp="b", tp="l"), E("a5", "m1", fp="b", tp="r"),
            E("m1", "d2"),
            E("d2", "m0", "có", fp="l", tp="l", chan=44, gpos="mid"),
            E("d2", "f", "không"),
        ])),
    ("4-3-12-huy-don-hang", "4.3.12 Hủy đơn hàng", dict(
        lanes=["Người mua", "Order Service", "Payment · Wallet"], lws=[340, 380, 300],
        nodes=dict(
            i=ini(0, 0), a1=act(0, 1, "Mở đơn hàng, bấm Hủy đơn"), a2=act(0, 2, "Xác nhận hủy"),
            s1=act(1, 3, "Kiểm tra quyền và trạng thái đơn"),
            d1=dec(1, 4, "Đã giao?", tside="r"),
            a3=act(0, 5, "Nhận thông báo: hãy yêu cầu trả hàng", dx=-70, w=180),
            x1=fin(0, 6, dx=-70),
            s2=act(1, 5.2, "Đặt trạng thái cancelled"),
            s3=act(1, 6.2, "Nhả tồn kho và voucher"),
            s4=act(1, 7.2, "Phát order.cancelled"),
            d2=dec(1, 8.2, "Đã thanh toán?", tside="l"),
            w1=act(2, 9.4, "Hoàn tiền vào ví người mua", focal=True),
            mR=mrg(1, 10.6),
            a4=act(0, 11.6, "Xem đơn đã hủy (và hoàn tiền nếu có)"),
            f=fin(0, 12.6)),
        edges=[
            E("i", "a1"), E("a1", "a2"), E("a2", "s1"), E("s1", "d1"),
            E("d1", "a3", "có", fp="l", tp="t", gpos="mid"), E("a3", "x1"),
            E("d1", "s2", "chưa"), E("s2", "s3"), E("s3", "s4"), E("s4", "d2"),
            E("d2", "w1", "có", fp="r", tp="t"),
            E("d2", "mR", "chưa"),
            E("w1", "mR", fp="b", tp="r"),
            E("mR", "a4", fp="l", tp="t"), E("a4", "f"),
        ])),
    ("4-3-13-yeu-cau-tra-hang-hoan-tien", "4.3.13 Yêu cầu trả hàng hoặc hoàn tiền", dict(
        lanes=["Người mua", "Order Service"], lws=[360, 380],
        nodes=dict(
            i=ini(0, 0), a1=act(0, 1, "Mở đơn hàng đã giao"), m0=mrg(0, 2),
            a2=act(0, 3, "Chọn Trả hàng / hoàn tiền, nhập lý do và bằng chứng"),
            a3=act(0, 4, "Gửi yêu cầu"),
            s1=act(1, 5, "Kiểm tra quyền sở hữu và trạng thái đơn"),
            d1=dec(1, 6, "Đơn đã giao?", tside="r"),
            a4=act(0, 7, "Nhận thông báo yêu cầu không hợp lệ", dx=80, w=170),
            x1=fin(0, 8, dx=80),
            d2=dec(1, 8.6, "Có lý do?", tside="r"),
            s2=act(1, 9.6, "Tạo yêu cầu (dispute open)", focal=True),
            a5=act(0, 10.6, "Nhận xác nhận, chờ quản trị viên xử lý"),
            f=fin(0, 11.6)),
        edges=[
            E("i", "a1"), E("a1", "m0"), E("m0", "a2"), E("a2", "a3"), E("a3", "s1"), E("s1", "d1"),
            E("d1", "a4", "chưa", fp="l", tp="t", gpos="mid"), E("a4", "x1"),
            E("d1", "d2", "rồi"),
            E("d2", "m0", "thiếu", fp="l", tp="l", chan=44),
            E("d2", "s2", "có"), E("s2", "a5", fp="l", tp="t"), E("a5", "f"),
        ])),
    ("4-3-14-giai-quyet-tra-hang-hoan-tien", "4.3.14 Giải quyết yêu cầu trả hàng và hoàn tiền", dict(
        lanes=["Quản trị viên", "Order Service", "Payment · Wallet"], lws=[340, 400, 300],
        nodes=dict(
            i=ini(0, 0), a1=act(0, 1, "Mở danh sách yêu cầu trả hàng"),
            s1=act(1, 2, "Lấy yêu cầu và đơn liên quan"),
            a2=act(0, 3, "Xem lý do, bằng chứng"),
            d1=dec(0, 4, "Chấp nhận?", tside="t"),
            a3=act(0, 5.2, "Nhập ghi chú từ chối", dx=-80, w=160),
            s2=act(1, 5.2, "Đặt resolved, đơn refund_processing"),
            s4=act(1, 6.2, "Phát order.refund_requested"),
            w1=act(2, 7.4, "Cộng tiền vào ví người mua", focal=True),
            s5=act(1, 8.6, "Nhận wallet.refunded, đặt refunded"),
            s3=act(1, 9.8, "Đóng yêu cầu (rejected)", dx=-100, w=160),
            mE=mrg(1, 11),
            a4=act(0, 12, "Xem kết quả xử lý"),
            f=fin(0, 13)),
        edges=[
            E("i", "a1"), E("a1", "s1"), E("s1", "a2", fp="l", tp="t"), E("a2", "d1"),
            E("d1", "a3", "từ chối", fp="l", tp="t", gpos="end-l"),
            E("d1", "s2", "chấp nhận", fp="r", tp="t"),
            E("s2", "s4"), E("s4", "w1"), E("w1", "s5", fp="l", tp="t"),
            E("a3", "s3", fp="b", tp="t"),
            E("s5", "mE"), E("s3", "mE", fp="b", tp="l"),
            E("mE", "a4", fp="l", tp="t"), E("a4", "f"),
        ])),
    ("4-3-15-vi-giao-dich-nap-tien", "4.3.15 Xem ví, lịch sử giao dịch và nạp tiền", dict(
        lanes=["Người mua", "Wallet · Payment Gateway", "SePay / Ngân hàng"], lws=[340, 380, 260],
        nodes=dict(
            i=ini(0, 0), a1=act(0, 1, "Mở Ví của tôi"),
            s1=act(1, 2, "Lấy số dư và lịch sử giao dịch"),
            a2=act(0, 3, "Xem số dư, lịch sử giao dịch"),
            d1=dec(0, 4, "Nạp tiền?", tside="r"),
            x0=fin(0, 4, dx=-110),
            a3=act(0, 5.2, "Nhập số tiền cần nạp"),
            s2=act(1, 6.2, "Tạo yêu cầu nạp, sinh mã QR SePay"),
            a4=act(0, 7.2, "Quét QR, chuyển khoản"),
            b1=act(2, 8.2, "Xử lý giao dịch, gửi webhook"),
            s3=act(1, 9.2, "Đối soát webhook (số tiền, mã)"),
            d2=dec(1, 10.2, "Khớp và còn hạn?", tside="r"),
            a5=act(0, 10.2, "Nhận thông báo nạp thất bại", dx=20, w=170),
            x1=fin(0, 10.2, dx=-125),
            s4=act(1, 11.4, "Cộng số dư ví, ghi sổ cái", focal=True),
            a6=act(0, 12.6, "Xem số dư mới"),
            f=fin(0, 13.6)),
        edges=[
            E("i", "a1"), E("a1", "s1"), E("s1", "a2", fp="l", tp="t"), E("a2", "d1"),
            E("d1", "x0", "không", fp="l", tp="r"),
            E("d1", "a3", "có"), E("a3", "s2"), E("s2", "a4", fp="l", tp="t"),
            E("a4", "b1", fp="r", tp="t"), E("b1", "s3", fp="l", tp="t"), E("s3", "d2"),
            E("d2", "a5", "không", fp="l", tp="r"), E("a5", "x1", fp="l", tp="r"),
            E("d2", "s4", "có"), E("s4", "a6", fp="l", tp="t"), E("a6", "f"),
        ])),
]


def main():
    for slug, title, spec in DIAGRAMS:
        spec = copy.deepcopy(spec)
        spec["title"] = title.split(" ", 1)[1]
        w, h, body = build_activity(spec)
        html = page(f"act-{slug}", f"UML 2.5 · Activity diagram · {title.split(' ')[0]}", title,
                    f"Activity diagram cho use case {title}.", w, h, body)
        html = html.replace('<p class="nav"><a href="index.html">← Mục lục</a></p>', "")
        (HERE / f"{slug}.html").write_text(html, encoding="utf-8")
        print(slug)


if __name__ == "__main__":
    main()
