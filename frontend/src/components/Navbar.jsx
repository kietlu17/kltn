import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import { useCart } from '../context/CartContext.jsx';
import SearchBar from './SearchBar.jsx';
import CartBadge from './CartBadge.jsx';
import useShopMap from '../hooks/useShopMap';
import api from '../services/api';

export default function Navbar() {
  const { user, isSeller, isAdmin, logout } = useAuth();
  const { showToast } = useToast();
  const { cartCount, clearCart } = useCart();
  const navigate = useNavigate();
  const location = useLocation();
  const logoutPath = isAdmin ? '/admin/login' : isSeller ? '/seller/login' : '/login';
  const shopMap = useShopMap();
  const [buyerName, setBuyerName] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  const handleLogout = () => {
    logout();
    clearCart();
    showToast('Đã đăng xuất');
    navigate(logoutPath);
  };

  useEffect(() => {
    if (isSeller || isAdmin || !user?.id) {
      setBuyerName('');
      return undefined;
    }
    let active = true;

    const loadBuyerName = () => {
      api
        .get(`/users/${user.id}`)
        .then((res) => {
          if (active) setBuyerName(res.data?.name || '');
        })
        .catch(() => {
          if (active) setBuyerName('');
        });
    };

    loadBuyerName();
    const handleProfileUpdate = () => loadBuyerName();
    window.addEventListener('buyer-profile-updated', handleProfileUpdate);

    return () => {
      active = false;
      window.removeEventListener('buyer-profile-updated', handleProfileUpdate);
    };
  }, [isSeller, isAdmin, user?.id]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const handleOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, [menuOpen]);

  const displayName = useMemo(() => {
    if (isSeller) {
      const shopName = shopMap.get(user?.shopId)?.name;
      return shopName || user?.email || 'Người bán';
    }
    if (isAdmin) {
      return user?.email || 'Quản trị viên';
    }
    return buyerName || user?.email || 'Người mua';
  }, [isSeller, isAdmin, shopMap, user?.shopId, user?.email, buyerName]);

  const initials = displayName ? displayName.slice(0, 2).toUpperCase() : 'U';

  const handleSearch = (query) => {
    const params = query ? `?q=${encodeURIComponent(query)}` : '';
    navigate(`/${params}`);
  };

  const handleShopSelect = (shop) => {
    const shopId = shop?._id || shop?.id;
    if (!shopId) return;
    navigate(`/shop/${shopId}`);
  };

  const handleProductSelect = (product) => {
    const productId = product?._id || product?.id;
    if (!productId) return;
    navigate(`/product/${productId}`);
  };

  const handleCartClick = (event) => {
    if (user) return;
    event.preventDefault();
    showToast('Vui lòng đăng nhập để xem giỏ hàng', 'error');
    navigate('/login');
  };

  const searchParams = new URLSearchParams(location.search);
  const initialQuery = searchParams.get('q') || '';

  return (
    <header className="navbar">
      <div className="container navbar-main">
        <Link to={isSeller ? '/seller/dashboard' : '/'} className="logo">
          Shopee Lite
        </Link>

        {!isSeller && !isAdmin && (
          <SearchBar
            onSearch={handleSearch}
            onShopSelect={handleShopSelect}
            onProductSelect={handleProductSelect}
            initialValue={initialQuery}
          />
        )}

        <div className="navbar-actions">
          {!isSeller && !isAdmin && (
            <Link to="/cart" className="cart-link" onClick={handleCartClick}>
              <span className="cart-icon">Giỏ hàng</span>
              <CartBadge count={cartCount} />
            </Link>
          )}

          {!isSeller && !isAdmin && user && (
            <>
              <Link to="/orders" className="text-link">Đơn hàng</Link>
              <Link to="/addresses" className="text-link">Địa chỉ</Link>
            </>
          )}

          <Link to="/carrier" className="text-link">Carrier demo</Link>

          {isSeller && (
            <Link to="/seller/dashboard" className="cart-link">Khu vực người bán</Link>
          )}

          {isAdmin && (
            <Link to="/admin/dashboard" className="cart-link">Cổng quản trị</Link>
          )}

          {user ? (
            <div className="user-menu" ref={menuRef}>
              <button
                type="button"
                className="user-pill"
                onClick={() => setMenuOpen((prev) => !prev)}
              >
                <span className="avatar">{initials}</span>
                <span>{displayName}</span>
              </button>
              {menuOpen && (
                <div className="user-dropdown">
                  {!isSeller && !isAdmin && (
                    <Link
                      to="/profile"
                      className="user-dropdown-item"
                      onClick={() => setMenuOpen(false)}
                    >
                      Hồ sơ
                    </Link>
                  )}
                  <button
                    type="button"
                    className="user-dropdown-item danger"
                    onClick={() => {
                      setMenuOpen(false);
                      handleLogout();
                    }}
                  >
                    Đăng xuất
                  </button>
                </div>
              )}
            </div>
          ) : (
            <>
              <Link to="/login" className="text-link">Đăng nhập người mua</Link>
              <Link to="/register" className="btn btn-outline">Đăng ký người mua</Link>
              <Link to="/seller/login" className="text-link">Người bán</Link>
              <Link to="/admin/login" className="text-link">Quản trị</Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
