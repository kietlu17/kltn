import { Routes, Route, Navigate, useParams } from 'react-router-dom';
import Navbar from './components/Navbar.jsx';
import Toast from './components/Toast.jsx';
import ProtectedRoute from './components/ProtectedRoute.jsx';
import Home from './pages/Home.jsx';
import ProductList from './pages/ProductList.jsx';
import ProductDetail from './pages/ProductDetail.jsx';
import ShopDetail from './pages/ShopDetail.jsx';
import Cart from './pages/Cart.jsx';
import Checkout from './pages/Checkout.jsx';
import Orders from './pages/Orders.jsx';
import Profile from './pages/Profile.jsx';
import Login from './pages/Login.jsx';
import Register from './pages/Register.jsx';
import Help from './pages/Help.jsx';
import Addresses from './pages/Addresses.jsx';
import CarrierSimulator from './pages/CarrierSimulator.jsx';
import SellerLayout from './seller/SellerLayout.jsx';
import SellerDashboard from './seller/SellerDashboard.jsx';
import SellerProductList from './seller/ProductList.jsx';
import CreateProduct from './seller/CreateProduct.jsx';
import EditProduct from './seller/EditProduct.jsx';
import SellerCategories from './seller/Categories.jsx';
import SellerOrders from './seller/SellerOrders.jsx';
import SellerChat from './seller/SellerChat.jsx';
import AdminLayout from './admin/AdminLayout.jsx';
import AdminDashboard from './admin/AdminDashboard.jsx';
import VoucherManager from './components/VoucherManager.jsx';

export default function App() {
  function LegacyProductRedirect() {
    const { id } = useParams();
    return <Navigate to={`/product/${id}`} replace />;
  }

  return (
    <div className="app">
      <Navbar />
      <Toast />
      <main className="page">
        <Routes>
          <Route
            path="/"
            element={<Home />}
          />
          <Route
            path="/products"
            element={<ProductList />}
          />
          <Route
            path="/product/:id"
            element={<ProductDetail />}
          />
          <Route
            path="/shop/:id"
            element={<ShopDetail />}
          />
          <Route
            path="/cart"
            element={
              <ProtectedRoute allowedRoles={['buyer']}>
                <Cart />
              </ProtectedRoute>
            }
          />
          <Route
            path="/checkout"
            element={
              <ProtectedRoute allowedRoles={['buyer']}>
                <Checkout />
              </ProtectedRoute>
            }
          />
          <Route
            path="/orders"
            element={
              <ProtectedRoute allowedRoles={['buyer']}>
                <Orders />
              </ProtectedRoute>
            }
          />
          <Route
            path="/profile"
            element={
              <ProtectedRoute allowedRoles={['buyer']}>
                <Profile />
              </ProtectedRoute>
            }
          />
          <Route
            path="/addresses"
            element={
              <ProtectedRoute allowedRoles={['buyer']}>
                <Addresses />
              </ProtectedRoute>
            }
          />
          <Route path="/login" element={<Login expectedRole="buyer" />} />
          <Route path="/register" element={<Register forcedRole="buyer" />} />
          <Route path="/help" element={<Help />} />
          <Route path="/carrier" element={<CarrierSimulator />} />
          <Route path="/seller/login" element={<Login expectedRole="seller" />} />
          <Route path="/seller/register" element={<Register forcedRole="seller" />} />
          <Route path="/admin/login" element={<Login expectedRole="admin" />} />
          <Route
            path="/seller"
            element={
              <ProtectedRoute allowedRoles={['seller']}>
                <SellerLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={<SellerDashboard />} />
            <Route path="products" element={<SellerProductList />} />
            <Route path="categories" element={<SellerCategories />} />
            <Route path="orders" element={<SellerOrders />} />
            <Route path="chat" element={<SellerChat />} />
            <Route path="vouchers" element={<VoucherManager title="Mã giảm giá của shop" />} />
            <Route path="products/create" element={<CreateProduct />} />
            <Route path="products/edit/:id" element={<EditProduct />} />
          </Route>
          <Route
            path="/admin"
            element={(
              <ProtectedRoute allowedRoles={['admin']}>
                <AdminLayout />
              </ProtectedRoute>
            )}
          >
            <Route index element={<Navigate to="dashboard/users" replace />} />
            <Route path="dashboard" element={<AdminDashboard />} />
            <Route path="dashboard/:tab" element={<AdminDashboard />} />
            <Route path="vouchers" element={<VoucherManager title="Mã giảm giá của sàn" />} />
          </Route>
          <Route path="/products/:id" element={<LegacyProductRedirect />} />
        </Routes>
      </main>
      <footer className="footer">
        <div className="container footer-inner">
          <div>
            <h4>Shopee Lite</h4>
            <p className="muted">Sàn thương mại được xây dựng cho demo microservices nhanh.</p>
          </div>
          <div className="footer-links">
            <span>Giới thiệu</span>
            <span>Trung tâm trợ giúp</span>
            <span>Điều khoản</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
