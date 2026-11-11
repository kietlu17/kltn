"""Diagram content for each use case. Labels starting with '$' render in mono
(endpoints, topics, field values); everything else renders in sans.

Sequence step tuples:
  ("m", from, to, label, kind)  kind: call | ret | async | ok (headline call) | ret-ok (headline reply)
  ("alt"|"opt"|"loop"|"par", "[guard]") ... ("else", "[guard]") ... ("end",)
Activity / BPMN nodes are placed on a lane x row (activity) or lane x col (BPMN) grid;
edges accept fp/tp ports ('t','b','l','r', optional ':offset'), via moves, g (guard) and gpos.
"""

# ------------------------------------------------------------------ helpers
def act(lane, row, t, **kw):
    return dict(k="action", lane=lane, row=row, t=t, **kw)


def dec(lane, row, t="", **kw):
    return dict(k="decision", lane=lane, row=row, t=t, **kw)


def mrg(lane, row, **kw):
    return dict(k="merge", lane=lane, row=row, **kw)


def ini(lane, row, **kw):
    return dict(k="initial", lane=lane, row=row, **kw)


def fin(lane, row, **kw):
    return dict(k="final", lane=lane, row=row, **kw)


def E(f, t, g=None, **kw):
    d = dict(f=f, t=t, **kw)
    if g:
        d["g"] = g
    return d


def task(lane, col, t, tt="", **kw):
    return dict(k="task", lane=lane, col=col, t=t, tt=tt, **kw)


def ev(k, lane, col, t="", **kw):
    return dict(k=k, lane=lane, col=col, t=t, **kw)


def gw(k, lane, col, t="", **kw):
    return dict(k=k, lane=lane, col=col, t=t, tpos=kw.pop("tpos", "t"), **kw)


USER = dict(id="u", label="Người mua", kind="actor")
SELLER = dict(id="s", label="Người bán", kind="actor")
ADMIN = dict(id="a", label="Quản trị viên", kind="actor")
WEB = dict(id="fe", label=":Web App", sub="frontend (React)")
GW = dict(id="gw", label=":API Gateway", sub="api-gateway")

USECASES = []

# ====================================================================== B1
USECASES.append(dict(
    slug="b1-tai-khoan-dia-chi", code="UC-B1", actor="Người mua",
    name="Quản lý tài khoản và địa chỉ",
    sequence=dict(
        parts=[USER, WEB, GW,
               dict(id="auth", label=":Auth Service", sub="auth-service"),
               dict(id="usr", label=":User Service", sub="user-service")],
        steps=[
            ("opt", "[chưa có tài khoản]"),
            ("m", "u", "fe", "Nhập email, mật khẩu, họ tên"),
            ("m", "fe", "gw", "$POST /auth/register"),
            ("m", "gw", "auth", "register(email, password, name)"),
            ("m", "auth", "auth", "Kiểm tra email trùng, bcrypt.hash"),
            ("m", "auth", "usr", "$POST /users {userId, name}"),
            ("m", "usr", "auth", "$201 hồ sơ", "ret"),
            ("m", "auth", "gw", "$201 Created", "ret"),
            ("m", "gw", "fe", "$201 Created", "ret"),
            ("end",),
            ("m", "fe", "gw", "$POST /auth/login"),
            ("m", "gw", "auth", "login(email, password)"),
            ("alt", "[thông tin đúng và isActive]"),
            ("m", "auth", "gw", "$200 JWT {role, tokenVersion}", "ret-ok"),
            ("m", "gw", "fe", "$200 JWT (lưu phiên)", "ret"),
            ("else", "[sai thông tin / tài khoản bị khóa]"),
            ("m", "auth", "gw", "$401 / 403", "ret"),
            ("m", "gw", "fe", "Thông báo lỗi đăng nhập", "ret"),
            ("end",),
            ("m", "u", "fe", "Thêm / sửa địa chỉ giao hàng"),
            ("m", "fe", "gw", "$POST /users/{id}/addresses + Bearer"),
            ("m", "gw", "gw", "Xác thực JWT, kiểm tra quyền"),
            ("m", "gw", "usr", "addAddress(userId, address)"),
            ("m", "usr", "usr", "Lưu địa chỉ, cập nhật mặc định"),
            ("m", "usr", "gw", "$201 Address", "ret"),
            ("m", "gw", "fe", "$201 Address", "ret"),
            ("m", "fe", "u", "Hiển thị sổ địa chỉ", "ret"),
        ],
    ),
    activity=dict(
        lanes=["Người mua", "Hệ thống"], lws=[340, 320],
        nodes=dict(
            i=ini(0, 0),
            a1=act(0, 1, "Truy cập trang Tài khoản"),
            d1=dec(0, 2, "Đã có tài khoản?", tside="r"),
            a2=act(0, 3, "Nhập email, mật khẩu, họ tên"),
            s1=act(1, 4, "Kiểm tra email, băm mật khẩu, tạo tài khoản và hồ sơ"),
            d2=dec(1, 5, "Hợp lệ?", tside="r"),
            m1=mrg(0, 6),
            a3=act(0, 7, "Đăng nhập bằng email, mật khẩu"),
            s2=act(1, 8, "Xác thực, kiểm tra trạng thái khóa"),
            d3=dec(1, 9, "Hợp lệ?", tside="r"),
            s4=act(1, 10, "Cấp JWT, tải hồ sơ và sổ địa chỉ"),
            m3=mrg(0, 11),
            d4=dec(0, 12, "Chọn thao tác", tside="r"),
            a4=act(0, 13.4, "Sửa thông tin cá nhân", dx=-80, w=136),
            a5=act(0, 13.4, "Thêm / sửa / xóa / đặt mặc định địa chỉ", dx=80, w=136),
            m2=mrg(0, 14.8),
            s5=act(1, 15.8, "Xác thực JWT, lưu thay đổi vào User Service", focal=True),
            a6=act(0, 16.8, "Xem thông tin đã cập nhật"),
            d6=dec(0, 17.8, "Tiếp tục?", tside="r"),
            f=fin(0, 18.8),
        ),
        edges=[
            E("i", "a1"), E("a1", "d1"),
            E("d1", "a2", "chưa có"),
            E("d1", "m1", "đã có", fp="l", tp="l", chan=56, gpos="mid"),
            E("a2", "s1", fp="r:-8"), E("s1", "d2"),
            E("d2", "a2", "không", fp="l", tp="r:8"),
            E("d2", "m1", "có", fp="b", tp="r"),
            E("m1", "a3"), E("a3", "s2", fp="r:-8"), E("s2", "d3"),
            E("d3", "a3", "sai / bị khóa", fp="l", tp="r:8"),
            E("d3", "s4", "đúng"),
            E("s4", "m3"), E("m3", "d4"),
            E("d4", "a4", "hồ sơ", fp="l", tp="t", gpos="end-l"),
            E("d4", "a5", "địa chỉ", fp="r", tp="t", gpos="end"),
            E("a4", "m2", fp="b", tp="l"), E("a5", "m2", fp="b", tp="r"),
            E("m2", "s5"), E("s5", "a6"), E("a6", "d6"),
            E("d6", "m3", "có", fp="l", tp="l", chan=48, gpos="mid"),
            E("d6", "f", "không"),
        ],
    ),
    bpmn=dict(
        pool="Sàn TMĐT", lanes=["Người mua", "Auth Service", "User Service"], cols=10, cw=136,
        nodes=dict(
            st=ev("start", 0, 0, "Cần quản lý tài khoản"),
            g1=gw("xor", 0, 1, "Đã có tài khoản?"),
            t1=task(0, 2, "Đăng ký tài khoản", "user"),
            t2=task(1, 2, "Tạo tài khoản, băm mật khẩu", "service"),
            t3=task(2, 3, "Tạo hồ sơ người dùng", "service"),
            g2=gw("xor", 0, 4),
            t4=task(0, 5, "Đăng nhập", "user"),
            t5=task(1, 5, "Xác thực và cấp JWT", "service"),
            g3=gw("xor", 1, 6, "Hợp lệ?", tpos="b"),
            e1=ev("end", 1, 7, "Đăng nhập|thất bại", dx=10),
            t6=task(0, 7, "Cập nhật hồ sơ / sổ địa chỉ", "user"),
            t7=task(2, 8, "Lưu hồ sơ và địa chỉ", "service", focal=True),
            e2=ev("end", 0, 9, "Thông tin đã cập nhật", tpos="t"),
        ),
        edges=[
            E("st", "g1"), E("g1", "t1", "Chưa"),
            E("g1", "g2", "Đã có", fp="b", tp="b", via=[("y", 56 + 128 - 12)], gpos="mid"),
            E("t1", "t2"), E("t2", "t3"), E("t3", "g2", fp="t", tp="l"),
            E("g2", "t4"), E("t4", "t5"), E("t5", "g3"),
            E("g3", "e1", "Không"),
            E("g3", "t6", "Có", fp="t", tp="l"),
            E("t6", "t7", fp="r", tp="l"),
            E("t7", "e2", fp="r", tp="b"),
        ],
    ),
))

from specs_more import UC as _MORE  # noqa: E402

USECASES.extend(_MORE)
