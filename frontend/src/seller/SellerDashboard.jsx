import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

const sellerOrderStatuses = [
  { key: 'pending', label: 'Chờ xử lý', color: '#f59e0b' },
  { key: 'confirmed', label: 'Đã xác nhận', color: '#7c3aed' },
  { key: 'shipped', label: 'Đang giao', color: '#2563eb' },
  { key: 'delivered', label: 'Hoàn tất', color: '#16a34a' },
  { key: 'cancelled', label: 'Hủy / hoàn', color: '#ef4444' }
];

function normalizeOrderProducts(order) {
  if (Array.isArray(order?.products)) return order.products;
  if (typeof order?.products === 'string') {
    try {
      return JSON.parse(order.products);
    } catch {
      return [];
    }
  }
  return [];
}

function getOrderStatusGroup(status) {
  const key = String(status || '').toLowerCase();
  if (['delivered', 'paid'].includes(key)) return 'delivered';
  if (key === 'shipped') return 'shipped';
  if (key === 'confirmed') return 'confirmed';
  if (['cancelled', 'payment_failed', 'refund_processing', 'refunded'].includes(key)) return 'cancelled';
  return 'pending';
}

function canConfirmOrder(order) {
  const method = String(order?.payment_method || '').toLowerCase();
  const status = String(order?.status || '').toLowerCase();
  if (['cancelled', 'payment_failed', 'confirmed', 'shipped', 'delivered', 'refund_processing', 'refunded'].includes(status)) return false;
  return method === 'cod' ? ['pending_payment', 'payment_processing', 'paid'].includes(status) : status === 'paid';
}

function getPercentageChange(current, previous) {
  if (!previous) return current ? 100 : 0;
  return ((current - previous) / previous) * 100;
}

function formatCompactNumber(value) {
  return new Intl.NumberFormat('vi-VN', { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value || 0));
}

function formatPayoutStatus(status) {
  const key = String(status || '').toLowerCase();
  if (key === 'completed') return 'Hoàn tất';
  if (key === 'failed') return 'Thất bại';
  if (key === 'processing') return 'Đang xử lý';
  return 'Đang chờ';
}

function SellerTrend({ value }) {
  const normalized = Number.isFinite(value) ? value : 0;
  const className = normalized > 0 ? 'positive' : normalized < 0 ? 'negative' : 'neutral';
  return (
    <span className={`seller-trend ${className}`}>
      {normalized > 0 ? '↑' : normalized < 0 ? '↓' : '•'} {Math.abs(normalized).toLocaleString('vi-VN', { maximumFractionDigits: 1 })}%
    </span>
  );
}

export default function SellerDashboard() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const [orders, setOrders] = useState([]);
  const [finance, setFinance] = useState(null);
  const [payouts, setPayouts] = useState([]);
  const [withdrawAmount, setWithdrawAmount] = useState('100');
  const [withdrawLoading, setWithdrawLoading] = useState(false);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState('');
  const [invoiceFeature, setInvoiceFeature] = useState(null);
  const [invoiceFeatureForm, setInvoiceFeatureForm] = useState({
    requestedMode: 'checkout_form',
    reason: ''
  });

  const years = useMemo(() => {
    const current = now.getFullYear();
    return [current - 2, current - 1, current, current + 1];
  }, [now]);

  async function loadSellerOverview(shopId) {
    if (!shopId) return;
    setDashboardLoading(true);
    setDashboardError('');
    const results = await Promise.allSettled([
      api.get(`/orders/seller/${shopId}`),
      api.get(`/payments/wallet/shop/${shopId}/balance`),
      api.get(`/payments/wallet/shop/${shopId}/payouts?limit=5`),
      api.get(`/shops/${shopId}/invoice-feature`)
    ]);

    if (results[0].status === 'fulfilled') setOrders(results[0].value.data || []);
    if (results[1].status === 'fulfilled') setFinance(results[1].value.data || null);
    if (results[2].status === 'fulfilled') setPayouts(results[2].value.data || []);
    if (results[3].status === 'fulfilled') {
      const feature = results[3].value.data || null;
      setInvoiceFeature(feature);
      setInvoiceFeatureForm((prev) => ({
        ...prev,
        requestedMode: feature?.invoiceRequestMode === 'checkout_form' ? 'chat_required' : 'checkout_form'
      }));
    }

    const failedCount = results.filter((result) => result.status === 'rejected').length;
    if (failedCount) setDashboardError(`Không thể tải ${failedCount}/4 nguồn dữ liệu. Các số liệu còn lại vẫn được hiển thị.`);
    setDashboardLoading(false);
  }

  useEffect(() => {
    const shopId = user?.shopId || user?.id;
    if (!shopId) {
      setOrders([]);
      return;
    }
    loadSellerOverview(shopId);
  }, [user]);

  const daysInMonth = useMemo(() => new Date(year, month, 0).getDate(), [month, year]);

  const insights = useMemo(() => {
    const revenue = Array.from({ length: daysInMonth }, () => 0);
    const counts = Array.from({ length: daysInMonth }, () => 0);
    const productMap = new Map();
    const selectedOrders = [];
    const previousOrders = [];
    const previousMonth = month === 1 ? 12 : month - 1;
    const previousYear = month === 1 ? year - 1 : year;

    orders.forEach((order) => {
      const created = new Date(order.created_at || order.createdAt);
      if (Number.isNaN(created.getTime())) return;
      if (created.getFullYear() === previousYear && created.getMonth() + 1 === previousMonth) previousOrders.push(order);
      if (created.getFullYear() !== year || created.getMonth() + 1 !== month) return;
      selectedOrders.push(order);

      const items = normalizeOrderProducts(order);
      const isValid = !['cancelled', 'payment_failed', 'refunded'].includes(String(order.status || '').toLowerCase());
      const orderRevenue = isValid ? Number(order.total_price || order.total || 0) : 0;
      const dayIndex = Math.max(0, Math.min(daysInMonth - 1, created.getDate() - 1));
      revenue[dayIndex] += orderRevenue;
      counts[dayIndex] += 1;

      if (!isValid) return;
      items.forEach((item) => {
        const name = item.productName || item.name || item.productId || 'Sản phẩm chưa rõ';
        const quantity = Number(item.quantity || 0);
        const itemRevenue = Number(item.price || 0) * quantity;
        const current = productMap.get(name) || { name, quantity: 0, revenue: 0 };
        productMap.set(name, { ...current, quantity: current.quantity + quantity, revenue: current.revenue + itemRevenue });
      });
    });

    const validSelectedOrders = selectedOrders.filter((order) => !['cancelled', 'payment_failed', 'refunded'].includes(String(order.status || '').toLowerCase()));
    const validPreviousOrders = previousOrders.filter((order) => !['cancelled', 'payment_failed', 'refunded'].includes(String(order.status || '').toLowerCase()));
    const totalRevenue = validSelectedOrders.reduce((sum, order) => sum + Number(order.total_price || order.total || 0), 0);
    const previousRevenue = validPreviousOrders.reduce((sum, order) => sum + Number(order.total_price || order.total || 0), 0);
    const totalProducts = validSelectedOrders.reduce((sum, order) => sum + normalizeOrderProducts(order).reduce((itemSum, item) => itemSum + Number(item.quantity || 0), 0), 0);
    const previousProducts = validPreviousOrders.reduce((sum, order) => sum + normalizeOrderProducts(order).reduce((itemSum, item) => itemSum + Number(item.quantity || 0), 0), 0);
    const statusCounts = sellerOrderStatuses.map((status) => ({
      ...status,
      count: selectedOrders.filter((order) => getOrderStatusGroup(order.status) === status.key).length
    }));
    const statusTotal = Math.max(selectedOrders.length, 1);
    let statusOffset = 0;
    const donutSegments = statusCounts.map((status) => {
      const start = statusOffset;
      statusOffset += (status.count / statusTotal) * 360;
      return `${status.color} ${start}deg ${statusOffset}deg`;
    });

    return {
      dailyRevenue: revenue,
      dailyOrders: counts,
      topProducts: Array.from(productMap.values()).sort((a, b) => b.revenue - a.revenue).slice(0, 5),
      totalRevenue,
      totalOrders: validSelectedOrders.length,
      totalProducts,
      averageOrderValue: validSelectedOrders.length ? totalRevenue / validSelectedOrders.length : 0,
      revenueTrend: getPercentageChange(totalRevenue, previousRevenue),
      orderTrend: getPercentageChange(validSelectedOrders.length, validPreviousOrders.length),
      productTrend: getPercentageChange(totalProducts, previousProducts),
      statusCounts,
      donutBackground: selectedOrders.length ? `conic-gradient(${donutSegments.join(', ')})` : '#e5e7eb',
      needsConfirmation: orders.filter(canConfirmOrder).length,
      readyToShip: orders.filter((order) => String(order.status || '').toLowerCase() === 'confirmed' && !order.shipment_tracking_code).length,
      pendingInvoices: orders.filter((order) => order.invoice_request?.requested && order.invoice_request?.status !== 'issued').length,
      refundOrders: orders.filter((order) => String(order.status || '').toLowerCase() === 'refund_processing').length
    };
  }, [orders, daysInMonth, month, year]);

  const maxRevenue = useMemo(() => Math.max(...insights.dailyRevenue, 1), [insights.dailyRevenue]);
  const maxTopRevenue = useMemo(() => Math.max(...insights.topProducts.map((item) => item.revenue), 1), [insights.topProducts]);

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

  function formatInvoiceMode(mode) {
    if (mode === 'checkout_form') return 'Hiện form khi tạo đơn';
    if (mode === 'off') return 'Tắt hiển thị';
    return 'Khách chat shop';
  }

  function formatInvoiceFeatureStatus(status) {
    if (status === 'pending_review') return 'Chờ admin duyệt';
    if (status === 'rejected') return 'Yêu cầu gần nhất bị từ chối';
    if (status === 'off') return 'Đang tắt';
    return 'Đang hoạt động';
  }

  async function submitInvoiceFeatureRequest() {
    const shopId = user?.shopId || user?.id;
    if (!shopId) return;
    try {
      await api.post(`/shops/${shopId}/invoice-feature-requests`, invoiceFeatureForm);
      const response = await api.get(`/shops/${shopId}/invoice-feature`);
      setInvoiceFeature(response.data || null);
      setInvoiceFeatureForm((prev) => ({ ...prev, reason: '' }));
      showToast('Đã gửi yêu cầu, vui lòng chờ admin duyệt');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể gửi yêu cầu hóa đơn', 'error');
    }
  }

  return (
    <div className="container page-section seller-dashboard seller-operations-dashboard">
      <header className="seller-ops-header">
        <div>
          <span className="seller-ops-eyebrow">TRUNG TÂM NGƯỜI BÁN</span>
          <h1>Chào {user?.shopName || user?.email || 'người bán'},</h1>
          <p>Đây là tình hình kinh doanh và những việc shop cần ưu tiên hôm nay.</p>
        </div>
        <div className="seller-ops-header-actions">
          <span>Cập nhật {new Date().toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })}</span>
          <button type="button" className="btn btn-outline" disabled={dashboardLoading} onClick={() => loadSellerOverview(user?.shopId || user?.id)}>
            {dashboardLoading ? 'Đang tải...' : 'Làm mới dữ liệu'}
          </button>
        </div>
      </header>

      {dashboardError && <div className="seller-data-warning">{dashboardError}</div>}

      <section className="seller-period-toolbar">
        <div className="seller-period-picker">
          <div>
            <label>Tháng báo cáo</label>
            <select value={month} onChange={(event) => setMonth(Number(event.target.value))}>
              {Array.from({ length: 12 }, (_, idx) => idx + 1).map((value) => <option key={value} value={value}>Tháng {value}</option>)}
            </select>
          </div>
          <div>
            <label>Năm</label>
            <select value={year} onChange={(event) => setYear(Number(event.target.value))}>
              {years.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </div>
        </div>
        <nav className="seller-quick-links" aria-label="Thao tác nhanh">
          <Link to="/seller/orders">Quản lý đơn</Link>
          <Link to="/seller/products">Sản phẩm</Link>
          <Link to="/seller/products/create">+ Thêm sản phẩm</Link>
          <Link to="/seller/categories">Danh mục</Link>
        </nav>
      </section>

      <section className="seller-kpi-grid" aria-label="Chỉ số kinh doanh chính">
        <article className="seller-kpi-card revenue">
          <div><span>Doanh thu hợp lệ</span><span className="seller-kpi-icon">₫</span></div>
          <strong>{formatPrice(insights.totalRevenue)}</strong>
          <footer><SellerTrend value={insights.revenueTrend} /><span>so với tháng trước</span></footer>
        </article>
        <article className="seller-kpi-card orders">
          <div><span>Đơn hàng</span><span className="seller-kpi-icon">#</span></div>
          <strong>{insights.totalOrders.toLocaleString('vi-VN')}</strong>
          <footer><SellerTrend value={insights.orderTrend} /><span>đơn hợp lệ trong kỳ</span></footer>
        </article>
        <article className="seller-kpi-card products">
          <div><span>Sản phẩm đã bán</span><span className="seller-kpi-icon">P</span></div>
          <strong>{insights.totalProducts.toLocaleString('vi-VN')}</strong>
          <footer><SellerTrend value={insights.productTrend} /><span>so với tháng trước</span></footer>
        </article>
        <article className="seller-kpi-card average">
          <div><span>Giá trị đơn trung bình</span><span className="seller-kpi-icon">A</span></div>
          <strong>{formatPrice(insights.averageOrderValue)}</strong>
          <footer><span className="seller-kpi-caption">Doanh thu trên mỗi đơn hợp lệ</span></footer>
        </article>
      </section>

      <section className="seller-attention-panel">
        <div className="seller-attention-copy">
          <span className="seller-attention-mark">!</span>
          <div><h2>Việc cần xử lý</h2><p>Hoàn thành sớm để duy trì chất lượng vận hành của shop.</p></div>
        </div>
        <div className="seller-attention-items">
          <Link to="/seller/orders"><strong>{insights.needsConfirmation}</strong><span>Đơn chờ xác nhận</span><small>Kiểm tra ngay →</small></Link>
          <Link to="/seller/orders"><strong>{insights.readyToShip}</strong><span>Chờ bàn giao</span><small>Tạo vận đơn →</small></Link>
          <Link to="/seller/orders"><strong>{insights.pendingInvoices}</strong><span>Chờ xuất hóa đơn</span><small>Xử lý hóa đơn →</small></Link>
          <Link to="/seller/orders"><strong>{insights.refundOrders}</strong><span>Yêu cầu hoàn tiền</span><small>Xem chi tiết →</small></Link>
        </div>
      </section>

      <section className="seller-ops-grid">
        <article className="seller-ops-card seller-revenue-card">
          <div className="seller-card-header">
            <div><h3>Doanh thu theo ngày</h3><p>Doanh thu hợp lệ và số đơn trong tháng {month}/{year}</p></div>
            <div className="seller-card-total"><span>Tổng kỳ này</span><strong>{formatPrice(insights.totalRevenue)}</strong></div>
          </div>
          <div className="seller-revenue-chart" role="img" aria-label={`Biểu đồ doanh thu tháng ${month}/${year}`}>
            {insights.dailyRevenue.map((value, index) => (
              <div className="seller-revenue-day" key={`revenue-${index}`} title={`Ngày ${index + 1}: ${formatPrice(value)} · ${insights.dailyOrders[index]} đơn`}>
                <span className={insights.dailyOrders[index] ? 'seller-order-count visible' : 'seller-order-count'}>{insights.dailyOrders[index]}</span>
                <div className="seller-revenue-track"><span style={{ height: `${Math.max((value / maxRevenue) * 100, value ? 6 : 1)}%` }} /></div>
                <small>{index === 0 || (index + 1) % 5 === 0 || index + 1 === daysInMonth ? index + 1 : ''}</small>
              </div>
            ))}
          </div>
          <div className="seller-chart-footer">
            <span><i className="seller-legend revenue" />Doanh thu</span>
            <span><i className="seller-legend orders" />Số trên cột là lượng đơn</span>
            <span>Trung bình {formatPrice(daysInMonth ? insights.totalRevenue / daysInMonth : 0)}/ngày</span>
          </div>
        </article>

        <article className="seller-ops-card seller-status-card">
          <div className="seller-card-header"><div><h3>Trạng thái đơn</h3><p>Phân bố đơn trong kỳ đã chọn</p></div></div>
          <div className="seller-donut-layout">
            <div className="seller-donut" style={{ background: insights.donutBackground }}>
              <div><strong>{insights.statusCounts.reduce((sum, item) => sum + item.count, 0)}</strong><span>Tổng đơn</span></div>
            </div>
            <div className="seller-status-legend">
              {insights.statusCounts.map((status) => (
                <div key={status.key}><i style={{ background: status.color }} /><span>{status.label}</span><strong>{status.count}</strong></div>
              ))}
            </div>
          </div>
        </article>

        <article className="seller-ops-card seller-products-card">
          <div className="seller-card-header">
            <div><h3>Sản phẩm bán chạy</h3><p>Xếp hạng theo doanh thu trong kỳ</p></div>
            <Link to="/seller/products">Quản lý sản phẩm</Link>
          </div>
          {insights.topProducts.length ? (
            <div className="seller-product-ranking">
              {insights.topProducts.map((item, index) => (
                <div className="seller-product-rank-row" key={item.name}>
                  <span className="seller-product-rank">{index + 1}</span>
                  <div className="seller-product-info">
                    <div><strong>{item.name}</strong><span>{item.quantity} sản phẩm</span></div>
                    <div className="seller-product-progress"><span style={{ width: `${(item.revenue / maxTopRevenue) * 100}%` }} /></div>
                  </div>
                  <strong>{formatPrice(item.revenue)}</strong>
                </div>
              ))}
            </div>
          ) : <div className="seller-empty-state">Chưa có sản phẩm bán ra trong kỳ này.</div>}
        </article>

        <article className="seller-ops-card seller-wallet-card">
          <div className="seller-card-header"><div><h3>Dòng tiền của shop</h3><p>Phân biệt tiền khả dụng, đang xử lý và chờ đối soát</p></div></div>
          <div className="seller-wallet-balance">
            <span>Số dư có thể rút</span>
            <strong>{formatPrice(finance?.sellerBalance?.availableBalance || 0)}</strong>
          </div>
          <div className="seller-wallet-breakdown">
            <div><span>Chờ đối soát</span><strong>{formatPrice(finance?.incomingSettlements?.totalAmount || 0)}</strong></div>
            <div><span>Đang rút</span><strong>{formatPrice(finance?.payoutPending?.availableBalance || 0)}</strong></div>
            <div><span>Đã rút</span><strong>{formatPrice(finance?.completedPayoutAmount || 0)}</strong></div>
          </div>
          <div className="seller-withdraw-form">
            <input type="number" min="1" value={withdrawAmount} onChange={(event) => setWithdrawAmount(event.target.value)} placeholder="Nhập số tiền muốn rút" />
            <button type="button" className="btn btn-primary" onClick={withdrawShopBalance} disabled={withdrawLoading}>
              {withdrawLoading ? 'Đang tạo lệnh...' : 'Rút tiền'}
            </button>
          </div>
          <div className="seller-payout-list">
            {payouts.slice(0, 3).map((payout) => (
              <div key={payout.id || payout._id}>
                <span><strong>{formatPayoutStatus(payout.status)}</strong><small>{payout.createdAt || payout.created_at ? new Date(payout.createdAt || payout.created_at).toLocaleDateString('vi-VN') : 'Giao dịch gần đây'}</small></span>
                <strong>{formatPrice(payout.amount)}</strong>
              </div>
            ))}
            {!payouts.length && <div className="seller-empty-state compact">Chưa có lịch sử rút tiền.</div>}
          </div>
        </article>

        <article className="seller-ops-card seller-invoice-card">
          <div className="seller-card-header">
            <div><h3>Cấu hình hóa đơn điện tử</h3><p>Yêu cầu thay đổi cách khách cung cấp thông tin hóa đơn.</p></div>
            <span className={`seller-feature-status ${invoiceFeature?.invoiceFeatureStatus || 'off'}`}>{formatInvoiceFeatureStatus(invoiceFeature?.invoiceFeatureStatus)}</span>
          </div>
          <div className="seller-invoice-layout">
            <div className="seller-invoice-current">
              <span>Chế độ hiện tại</span>
              <strong>{formatInvoiceMode(invoiceFeature?.invoiceRequestMode)}</strong>
              <small>Mọi thay đổi cần được quản trị viên xét duyệt trước khi áp dụng.</small>
            </div>
            <div className="seller-invoice-form">
              <div>
                <label>Chế độ đề xuất</label>
                <select value={invoiceFeatureForm.requestedMode} onChange={(event) => setInvoiceFeatureForm((prev) => ({ ...prev, requestedMode: event.target.value }))}>
                  <option value="checkout_form">Mở form hóa đơn khi tạo đơn</option>
                  <option value="chat_required">Tắt form, khách chat shop</option>
                  <option value="off">Ẩn hỗ trợ hóa đơn</option>
                </select>
              </div>
              <div>
                <label>Lý do thay đổi</label>
                <input value={invoiceFeatureForm.reason} onChange={(event) => setInvoiceFeatureForm((prev) => ({ ...prev, reason: event.target.value }))} placeholder="Ví dụ: shop đã kết nối MISA" />
              </div>
              <button type="button" className="btn btn-outline" onClick={submitInvoiceFeatureRequest}>Gửi yêu cầu duyệt</button>
            </div>
          </div>
          {(invoiceFeature?.requests || []).slice(0, 2).map((request) => (
            <div key={request._id || request.id} className="seller-invoice-request-row">
              <span>{formatInvoiceMode(request.requestedMode)}</span>
              <strong>{request.status === 'pending' ? 'Chờ duyệt' : request.status === 'approved' ? 'Đã duyệt' : 'Từ chối'}</strong>
            </div>
          ))}
        </article>
      </section>
    </div>
  );
}
