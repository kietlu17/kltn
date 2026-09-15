import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

function mapLoginErrorMessage(err) {
  const rawMessage = err?.response?.data?.message || err?.response?.data?.error || err?.message || '';
  const message = String(rawMessage).toLowerCase();
  const status = err?.response?.status;

  if (message.includes('email and password are required')) {
    return 'Vui lòng nhập email và mật khẩu';
  }
  if (message.includes('invalid credentials')) {
    return 'Email hoặc mật khẩu không đúng';
  }
  if (message.includes('account is locked')) {
    return 'Tài khoản đã bị khóa';
  }
  if (message.includes('role mismatch')) {
    return 'Tài khoản không đúng vai trò đăng nhập';
  }
  if (message.includes('too many requests')) {
    return 'Bạn đăng nhập quá nhiều lần. Vui lòng thử lại sau';
  }
  if (message.includes('network') || message.includes('timeout')) {
    return 'Không thể kết nối máy chủ. Vui lòng thử lại sau';
  }
  if (status === 401) {
    return 'Phiên đăng nhập không hợp lệ hoặc thông tin đăng nhập không đúng';
  }
  if (status === 403) {
    return 'Bạn không có quyền đăng nhập khu vực này';
  }
  if (status >= 500) {
    return 'Máy chủ đăng nhập đang gặp lỗi. Vui lòng thử lại sau';
  }
  return 'Đăng nhập thất bại';
}

export default function Login({ expectedRole = null }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const { login } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const isSeller = expectedRole === 'seller';
  const isAdmin = expectedRole === 'admin';
  const registerPath = isSeller ? '/seller/register' : '/register';
  const heading = isAdmin ? 'Đăng nhập quản trị' : isSeller ? 'Đăng nhập người bán' : 'Đăng nhập';
  const description = isAdmin
    ? 'Quản lý hoạt động sàn và xử lý khiếu nại.'
    : isSeller
      ? 'Truy cập bảng điều khiển cửa hàng, đơn hàng và tồn kho.'
      : 'Thanh toán nhanh, ưu đãi chọn lọc và người bán uy tín.';

  async function loginHandler(event) {
    event?.preventDefault();
    if (!email || !password) {
      showToast('Vui lòng nhập email và mật khẩu', 'error');
      return;
    }

    try {
      const payload = expectedRole ? { email, password, role: expectedRole } : { email, password };
      const res = await api.post('/auth/login', payload);
      const nextUser = res.data.user;

      if (expectedRole && nextUser?.role !== expectedRole) {
        const message =
          expectedRole === 'seller'
            ? 'Tài khoản người mua phải đăng nhập tại /login'
            : expectedRole === 'admin'
              ? 'Tài khoản này không phải quản trị viên'
              : 'Tài khoản người bán phải đăng nhập tại /seller/login';
        showToast(message, 'error');
        navigate(expectedRole === 'seller' ? '/login' : expectedRole === 'admin' ? '/login' : '/seller/login');
        return;
      }

      login(nextUser, res.data.token);
      showToast('Đăng nhập thành công');

      if (nextUser?.role === 'admin') {
        navigate('/admin/dashboard');
        return;
      }
      if (nextUser?.role === 'seller') {
        navigate('/seller/dashboard');
        return;
      }
      navigate('/');
    } catch (err) {
      showToast(mapLoginErrorMessage(err), 'error');
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={loginHandler}>
        <h2>{heading}</h2>
        <label>Email</label>
        <input placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <label>Mật khẩu</label>
        <input placeholder="Mật khẩu" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <button className="btn btn-primary btn-full" type="submit">Đăng nhập</button>
        {!isAdmin && (
          <p className="muted">
            Chưa có tài khoản? <Link to={registerPath}>Đăng ký</Link>
          </p>
        )}
      </form>
      <div className="auth-side">
        <h3>Chào mừng quay lại Shopee Lite</h3>
        <p>{description}</p>
      </div>
    </div>
  );
}
