import { Link, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { useCart } from '../context/CartContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

export default function SellerLayout() {
  const { logout } = useAuth();
  const { clearCart } = useCart();
  const { showToast } = useToast();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    clearCart();
    showToast('Đã đăng xuất');
    navigate('/seller/login');
  };

  return (
    <div className="seller-layout">
      <aside className="seller-sidebar">
        <h3>Khu vực người bán</h3>
        <nav>
          <Link to="/seller/dashboard">Bảng điều khiển</Link>
          <Link to="/seller/products">Sản phẩm</Link>
          <Link to="/seller/categories">Danh mục</Link>
          <Link to="/seller/orders">Đơn hàng</Link>
          <Link to="/seller/chat">Chat</Link>
          <Link to="/seller/products/create">Tạo sản phẩm</Link>
          <button className="seller-nav-button" onClick={handleLogout}>Đăng xuất</button>
        </nav>
      </aside>
      <main className="seller-content">
        <Outlet />
      </main>
    </div>
  );
}
