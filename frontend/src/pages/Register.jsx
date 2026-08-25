import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useToast } from '../context/ToastContext.jsx';

export default function Register({ forcedRole = null }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState(forcedRole || 'buyer');
  const [name, setName] = useState('');
  const [shopName, setShopName] = useState('');
  const [shopDescription, setShopDescription] = useState('');
  const [legalEntityType, setLegalEntityType] = useState('unknown');
  const [taxCode, setTaxCode] = useState('');
  const [invoiceProvider, setInvoiceProvider] = useState('');
  const [invoiceRequestMode, setInvoiceRequestMode] = useState('chat_required');
  const { showToast } = useToast();
  const navigate = useNavigate();

  const effectiveRole = forcedRole || role;
  const isSeller = effectiveRole === 'seller';
  const loginPath = isSeller ? '/seller/login' : '/login';
  const heading = isSeller ? 'Tạo tài khoản người bán' : 'Tạo tài khoản';
  const sideHeading = isSeller ? 'Mở gian hàng ngay hôm nay' : 'Mua bán an tâm cùng Shopee Lite';
  const sideDescription = isSeller
    ? 'Khởi tạo cửa hàng và bắt đầu quản lý đơn hàng chỉ trong vài phút.'
    : 'Tạo cửa hàng hoặc khám phá hàng ngàn ưu đãi ngay.';

  async function register() {
    if (!email || !password) {
      showToast('Vui lòng nhập email và mật khẩu', 'error');
      return;
    }

    if (isSeller && !shopName.trim()) {
      showToast('Người bán cần nhập tên cửa hàng', 'error');
      return;
    }

    try {
      await api.post('/auth/register', {
        email,
        password,
        role: effectiveRole,
        name,
        shopName,
        shopDescription,
        legalEntityType,
        taxCode,
        invoiceProvider,
        invoiceRequestMode
      });
      showToast('Đăng ký thành công');
      navigate(loginPath);
    } catch (err) {
      const message = err?.response?.data?.message || 'Đăng ký thất bại';
      showToast(message, 'error');
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h2>{heading}</h2>
        <label>Email</label>
        <input placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />

        <label>Mật khẩu</label>
        <input placeholder="Tạo mật khẩu" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />

        {!isSeller && (
          <>
            <label>Họ và tên</label>
            <input placeholder="Tên của bạn" value={name} onChange={(e) => setName(e.target.value)} />
          </>
        )}

        {!forcedRole && (
          <>
            <label>Vai trò</label>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="buyer">Người mua</option>
              <option value="seller">Người bán</option>
            </select>
          </>
        )}

        {isSeller && (
          <>
            <label>Tên cửa hàng</label>
            <input placeholder="Tên cửa hàng của bạn" value={shopName} onChange={(e) => setShopName(e.target.value)} />
            <label>Mô tả cửa hàng</label>
            <textarea
              placeholder="Giới thiệu cửa hàng cho khách hàng"
              value={shopDescription}
              onChange={(e) => setShopDescription(e.target.value)}
            />
            <label>Loại hình kinh doanh</label>
            <select value={legalEntityType} onChange={(e) => setLegalEntityType(e.target.value)}>
              <option value="unknown">Chưa cập nhật</option>
              <option value="company">Công ty</option>
              <option value="business_household">Hộ kinh doanh</option>
              <option value="individual">Cá nhân kinh doanh</option>
            </select>
            <label>Mã số thuế</label>
            <input placeholder="MST nếu có" value={taxCode} onChange={(e) => setTaxCode(e.target.value)} />
            <label>Phần mềm hóa đơn</label>
            <input
              placeholder="Ví dụ: MISA, Sapo, VNPT"
              value={invoiceProvider}
              onChange={(e) => setInvoiceProvider(e.target.value)}
            />
            <label>Cách nhận yêu cầu hóa đơn</label>
            <select value={invoiceRequestMode} onChange={(e) => setInvoiceRequestMode(e.target.value)}>
              <option value="chat_required">Khách chat shop để gửi thông tin</option>
              <option value="checkout_form">Hiện form ở trang thanh toán</option>
              <option value="off">Không hiển thị hỗ trợ hóa đơn</option>
            </select>
          </>
        )}

        <button className="btn btn-primary btn-full" onClick={register}>Đăng ký</button>
        <p className="muted">
          Đã có tài khoản? <Link to={loginPath}>Đăng nhập</Link>
        </p>
      </div>

      <div className="auth-side">
        <h3>{sideHeading}</h3>
        <p>{sideDescription}</p>
      </div>
    </div>
  );
}
