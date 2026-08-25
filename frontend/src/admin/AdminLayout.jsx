import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { useCart } from '../context/CartContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

const links = [
  { key: 'users', label: 'Người dùng' },
  { key: 'products', label: 'Sản phẩm' },
  { key: 'orders', label: 'Đơn hàng' },
  { key: 'disputes', label: 'Trả hàng/hoàn tiền' },
  { key: 'invoice_requests', label: 'Yêu cầu hóa đơn' },
  { key: 'finance', label: 'Ví sàn' },
  { key: 'categories', label: 'Danh mục' },
  { key: 'vouchers', label: 'Mã giảm giá', to: '/admin/vouchers' }
];

export default function AdminLayout() {
  const { logout } = useAuth();
  const { clearCart } = useCart();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = () => {
    logout();
    clearCart();
    showToast('Đã đăng xuất');
    navigate('/admin/login');
  };

  const isActive = (item) => (item.to ? location.pathname === item.to : location.pathname.includes(`/admin/dashboard/${item.key}`));

  return (
    <div className="seller-layout admin-layout">
      <aside className="seller-sidebar admin-sidebar">
        <h3>Cổng quản trị</h3>
        <nav>
          <Link to="/admin/dashboard">Bảng điều khiển</Link>
          {links.map((item) => (
            <Link key={item.key} to={item.to || `/admin/dashboard/${item.key}`} className={isActive(item) ? 'active' : ''}>
              {item.label}
            </Link>
          ))}
          <button type="button" className="seller-nav-button" onClick={handleLogout}>Đăng xuất</button>
        </nav>
      </aside>
      <main className="seller-content">
        <Outlet />
      </main>
    </div>
  );
}
