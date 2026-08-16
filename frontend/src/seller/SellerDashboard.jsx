import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

export default function SellerDashboard() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const [orders, setOrders] = useState([]);
  const [stats, setStats] = useState({ totalOrders: 0, totalProducts: 0, totalRevenue: 0 });
  const [finance, setFinance] = useState(null);
  const [payouts, setPayouts] = useState([]);
  const [withdrawAmount, setWithdrawAmount] = useState('100');
  const [withdrawLoading, setWithdrawLoading] = useState(false);

  const years = useMemo(() => {
    const current = now.getFullYear();
    return [current - 2, current - 1, current, current + 1];
  }, [now]);

  useEffect(() => {
    const shopId = user?.shopId || user?.id;
    if (!shopId) {
      setStats({ totalOrders: 0, totalProducts: 0, totalRevenue: 0 });
      return;
    }
    api
      .get(`/orders/seller/${shopId}/stats`, { params: { month, year } })
      .then((res) => setStats(res.data))
      .catch(() => setStats({ totalOrders: 0, totalProducts: 0, totalRevenue: 0 }));
  }, [user, month, year]);

  useEffect(() => {
    const shopId = user?.shopId || user?.id;
    if (!shopId) {
      setOrders([]);
      return;
    }
    api.get(`/orders/seller/${shopId}`).then((res) => setOrders(res.data)).catch(() => setOrders([]));
    api.get(`/payments/wallet/shop/${shopId}/balance`).then((res) => setFinance(res.data)).catch(() => setFinance(null));
    api.get(`/payments/wallet/shop/${shopId}/payouts?limit=5`).then((res) => setPayouts(res.data || [])).catch(() => setPayouts([]));
  }, [user]);

  const daysInMonth = useMemo(() => new Date(year, month, 0).getDate(), [month, year]);

  const { dailyRevenue, dailyOrders, topProducts } = useMemo(() => {
    const revenue = Array.from({ length: daysInMonth }, () => 0);
    const counts = Array.from({ length: daysInMonth }, () => 0);
    const productMap = new Map();

    orders.forEach((order) => {
      const created = new Date(order.created_at || order.createdAt);
      if (Number.isNaN(created.getTime())) return;
      if (created.getFullYear() !== year || created.getMonth() + 1 !== month) return;

      let items = [];
      if (Array.isArray(order.products)) {
        items = order.products;
      } else if (typeof order.products === 'string') {
        try {
          items = JSON.parse(order.products);
        } catch {
          items = [];
        }
      }

      const orderRevenue = items.reduce((sum, item) => sum + Number(item.price || 0) * Number(item.quantity || 0), 0);
      const dayIndex = Math.max(0, Math.min(daysInMonth - 1, created.getDate() - 1));
      revenue[dayIndex] += orderRevenue;
      counts[dayIndex] += 1;

      items.forEach((item) => {
        const name = item.productName || item.name || item.productId || 'Sản phẩm chưa rõ';
        const quantity = Number(item.quantity || 0);
        const current = productMap.get(name) || { name, quantity: 0 };
        productMap.set(name, { ...current, quantity: current.quantity + quantity });
      });
    });

    const topProductsList = Array.from(productMap.values()).sort((a, b) => b.quantity - a.quantity).slice(0, 5);
    return { dailyRevenue: revenue, dailyOrders: counts, topProducts: topProductsList };
  }, [orders, daysInMonth, month, year]);

  const maxRevenue = useMemo(() => Math.max(...dailyRevenue, 1), [dailyRevenue]);
  const maxOrders = useMemo(() => Math.max(...dailyOrders, 1), [dailyOrders]);
  const maxTopQty = useMemo(() => Math.max(...topProducts.map((item) => item.quantity), 1), [topProducts]);
  const totalRevenue = useMemo(() => dailyRevenue.reduce((sum, value) => sum + value, 0), [dailyRevenue]);
  const totalOrders = useMemo(() => dailyOrders.reduce((sum, value) => sum + value, 0), [dailyOrders]);
  const avgRevenue = useMemo(() => (daysInMonth ? totalRevenue / daysInMonth : 0), [totalRevenue, daysInMonth]);
  const avgOrders = useMemo(() => (daysInMonth ? totalOrders / daysInMonth : 0), [totalOrders, daysInMonth]);

  async function withdrawShopBalance() {
    const shopId = user?.shopId || user?.id;
    const amount = Number(withdrawAmount);
    if (!shopId || !Number.isFinite(amount) || amount <= 0) return;
    setWithdrawLoading(true);
    try {
      await api.post(`/payments/wallet/shop/${shopId}/withdrawals`, {
        amount,
        bankAccount: { provider: 'mock_bank', accountName: user?.shopName || user?.email || shopId }
      });
      const [balanceRes, payoutsRes] = await Promise.all([
        api.get(`/payments/wallet/shop/${shopId}/balance`),
        api.get(`/payments/wallet/shop/${shopId}/payouts?limit=5`)
      ]);
      setFinance(balanceRes.data);
      setPayouts(payoutsRes.data || []);
      showToast('Đã tạo lệnh rút tiền shop');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Rút tiền shop thất bại', 'error');
    } finally {
      setWithdrawLoading(false);
    }
  }

  return (
    <div className="container page-section seller-dashboard">
      <div className="section-header">
        <h2>Bảng điều khiển người bán</h2>
        <span className="section-link">Quản lý shop của bạn</span>
      </div>

      <div className="seller-grid">
        <div className="card">
          <h3>Thống kê theo tháng</h3>
          <p className="muted">Theo dõi số lượng bán và doanh thu theo tháng đã chọn.</p>
          <div className="form-grid">
            <div>
              <label>Tháng</label>
              <select value={month} onChange={(event) => setMonth(Number(event.target.value))}>
                {Array.from({ length: 12 }, (_, idx) => idx + 1).map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </div>
            <div>
              <label>Năm</label>
              <select value={year} onChange={(event) => setYear(Number(event.target.value))}>
                {years.map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="seller-stats">
            <div>
              <span className="muted">Đơn hàng</span>
              <strong>{stats.totalOrders || 0}</strong>
            </div>
            <div>
              <span className="muted">Sản phẩm đã bán</span>
              <strong>{stats.totalProducts || 0}</strong>
            </div>
            <div>
              <span className="muted">Doanh thu</span>
              <strong>{formatPrice(stats.totalRevenue)}</strong>
            </div>
          </div>
        </div>

        <div className="card">
          <h3>Sản phẩm</h3>
          <p className="muted">Tạo, chỉnh sửa hoặc xóa sản phẩm.</p>
          <Link to="/seller/products" className="btn btn-outline">Xem sản phẩm</Link>
          <Link to="/seller/products/create" className="btn btn-primary">Tạo sản phẩm</Link>
        </div>

        <div className="card">
          <h3>Đơn hàng</h3>
          <p className="muted">Xem đơn hàng mới và thông tin khách hàng.</p>
          <Link to="/seller/orders" className="btn btn-outline">Xem đơn hàng</Link>
        </div>

        <div className="card">
          <h3>Ví shop</h3>
          <p className="muted">Số dư khả dụng và các khoản settlement dự kiến về ví.</p>
          <div className="seller-stats">
            <div>
              <span className="muted">Khả dụng</span>
              <strong>{formatPrice(finance?.sellerBalance?.availableBalance || 0)}</strong>
            </div>
            <div>
              <span className="muted">Đang rút</span>
              <strong>{formatPrice(finance?.payoutPending?.availableBalance || 0)}</strong>
            </div>
            <div>
              <span className="muted">Đã rút</span>
              <strong>{formatPrice(finance?.completedPayoutAmount || 0)}</strong>
            </div>
            <div>
              <span className="muted">Dự kiến về ví</span>
              <strong>{formatPrice(finance?.incomingSettlements?.totalAmount || 0)}</strong>
            </div>
          </div>
          <div className="form-actions">
            <input
              type="number"
              min="1"
              value={withdrawAmount}
              onChange={(event) => setWithdrawAmount(event.target.value)}
              placeholder="Số tiền rút"
            />
            <button className="btn btn-outline" onClick={withdrawShopBalance} disabled={withdrawLoading}>
              {withdrawLoading ? 'Đang tạo lệnh...' : 'Rút tiền'}
            </button>
          </div>
          {payouts.slice(0, 3).map((payout) => (
            <div key={payout.id} className="checkout-row">
              <span>{payout.status}</span>
              <strong>{formatPrice(payout.amount)}</strong>
            </div>
          ))}
        </div>

        <div className="card">
          <h3>Danh mục</h3>
          <p className="muted">Sắp xếp sản phẩm theo danh mục.</p>
          <Link to="/seller/categories" className="btn btn-outline">Quản lý danh mục</Link>
        </div>

        <div className="card">
          <h3>Thông tin shop</h3>
          <p className="muted">Cập nhật thông tin và nhận diện thương hiệu shop.</p>
          <button className="btn btn-outline">Chỉnh sửa hồ sơ</button>
        </div>
      </div>

      <div className="card seller-chart-card">
        <div className="chart-header">
          <div>
            <h3>Xu hướng doanh thu</h3>
            <p className="muted">Doanh thu và số đơn theo ngày trong tháng đã chọn.</p>
          </div>
          <div className="chart-meta">
            <span className="muted">{`${month}/${year}`}</span>
          </div>
        </div>

        <div className="charts">
          <div className="chart-block">
            <div className="chart-title">Doanh thu theo ngày</div>
            <div className="chart-bars">
              {dailyRevenue.map((value, index) => (
                <div key={`rev-${index}`} className="chart-bar" data-value={formatPrice(value)}>
                  <span style={{ height: `${(value / maxRevenue) * 100}%` }} />
                </div>
              ))}
            </div>
            <div className="chart-summary">
              <span>Tổng: {formatPrice(totalRevenue)}</span>
              <span>Trung bình/ngày: {formatPrice(avgRevenue)}</span>
            </div>
            <div className="chart-axis">
              <span>Ngày 1</span>
              <span>{`Ngày ${daysInMonth}`}</span>
            </div>
          </div>

          <div className="chart-block">
            <div className="chart-title">Đơn hàng theo ngày</div>
            <div className="chart-bars orders">
              {dailyOrders.map((value, index) => (
                <div key={`orders-${index}`} className="chart-bar" data-value={`${value} đơn`}>
                  <span style={{ height: `${(value / maxOrders) * 100}%` }} />
                </div>
              ))}
            </div>
            <div className="chart-summary">
              <span>Tổng: {totalOrders} đơn</span>
              <span>Trung bình/ngày: {avgOrders.toFixed(1)}</span>
            </div>
            <div className="chart-axis">
              <span>Ngày 1</span>
              <span>{`Ngày ${daysInMonth}`}</span>
            </div>
          </div>

          <div className="chart-block">
            <div className="chart-title">Sản phẩm bán chạy</div>
            <div className="top-products">
              {topProducts.length === 0 ? (
                <div className="muted">Tháng này chưa có sản phẩm bán ra.</div>
              ) : (
                topProducts.map((item) => (
                  <div key={item.name} className="top-product-row">
                    <div className="top-product-name">{item.name}</div>
                    <div className="top-product-bar">
                      <span style={{ width: `${(item.quantity / maxTopQty) * 100}%` }} />
                    </div>
                    <div className="top-product-qty">{item.quantity}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
