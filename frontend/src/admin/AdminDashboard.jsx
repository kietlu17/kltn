import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import api from '../services/api';
import { useToast } from '../context/ToastContext.jsx';
import { formatDisputeStatus, formatOrderStatus } from '../utils/statusLabels';

const orderStatuses = ['pending_payment', 'payment_processing', 'paid', 'confirmed', 'shipped', 'delivered', 'refund_processing', 'refunded', 'payment_failed', 'cancelled'];
const codOrderStatuses = ['pending_payment', 'confirmed', 'shipped', 'delivered', 'paid', 'refund_processing', 'refunded', 'payment_failed', 'cancelled'];

function isCodOrder(order) {
  return String(order?.payment_method || '').toLowerCase() === 'cod';
}

function getSelectableOrderStatuses(order) {
  const statuses = isCodOrder(order) ? codOrderStatuses : orderStatuses;
  if (order?.status === 'delivered') {
    return statuses.filter((status) => status !== 'cancelled');
  }
  return statuses;
}

function SectionHeader({ title, subtitle }) {
  return (
    <div className="section-header">
      <h2>{title}</h2>
      <span className="section-link">{subtitle}</span>
    </div>
  );
}

function formatCurrency(value) {
  return Number(value || 0).toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

function formatSettlementStatus(status) {
  const key = String(status || '').toLowerCase();
  if (key === 'settled') return 'Đã chuyển';
  if (key === 'pending') return 'Chờ đối soát';
  if (key === 'awaiting_cod_remittance') return 'Chờ đơn vị vận chuyển nộp COD';
  return '-';
}

function formatLegalEntityType(type) {
  const key = String(type || '').toLowerCase();
  if (key === 'company') return 'Công ty';
  if (key === 'business_household') return 'Hộ kinh doanh';
  if (key === 'individual') return 'Cá nhân kinh doanh';
  return 'Chưa cập nhật';
}

const dashboardOrderStatuses = [
  { key: 'delivered', label: 'Hoàn tất', color: '#16a34a' },
  { key: 'shipped', label: 'Đang giao', color: '#2563eb' },
  { key: 'confirmed', label: 'Đã xác nhận', color: '#7c3aed' },
  { key: 'pending', label: 'Chờ xử lý', color: '#f59e0b' },
  { key: 'cancelled', label: 'Đã hủy', color: '#ef4444' }
];

function getOrderDate(order) {
  const date = new Date(order?.created_at || order?.createdAt || 0);
  return Number.isNaN(date.getTime()) ? null : date;
}

function getOrderShopId(order) {
  let products = order?.products;
  if (typeof products === 'string') {
    try {
      products = JSON.parse(products);
    } catch {
      products = [];
    }
  }
  return Array.isArray(products) ? products.find((item) => item?.shopId)?.shopId : null;
}

function getStatusGroup(status) {
  if (status === 'delivered' || status === 'paid') return 'delivered';
  if (status === 'shipped') return 'shipped';
  if (status === 'confirmed') return 'confirmed';
  if (status === 'cancelled' || status === 'payment_failed' || status === 'refunded') return 'cancelled';
  return 'pending';
}

function formatCompactCurrency(value) {
  return new Intl.NumberFormat('vi-VN', {
    notation: 'compact',
    maximumFractionDigits: 1
  }).format(Number(value || 0));
}

function TrendBadge({ value }) {
  const normalized = Number.isFinite(value) ? value : 0;
  const trendClass = normalized > 0 ? 'positive' : normalized < 0 ? 'negative' : 'neutral';
  return (
    <span className={`admin-trend ${trendClass}`}>
      {normalized > 0 ? '↑' : normalized < 0 ? '↓' : '•'} {Math.abs(normalized).toLocaleString('vi-VN', { maximumFractionDigits: 1 })}%
    </span>
  );
}

export default function AdminDashboard() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const activeTab = tab || 'overview';

  const [users, setUsers] = useState([]);
  const [pendingProducts, setPendingProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [disputes, setDisputes] = useState([]);
  const [categories, setCategories] = useState([]);
  const [invoiceRequests, setInvoiceRequests] = useState([]);
  const [categoryForm, setCategoryForm] = useState({});
  const [platformWallet, setPlatformWallet] = useState(null);
  const [platformWalletError, setPlatformWalletError] = useState('');
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState('');
  const [userSearch, setUserSearch] = useState('');
  const [userRoleFilter, setUserRoleFilter] = useState('all');
  const [userStatusFilter, setUserStatusFilter] = useState('all');

  const loadUsers = () => api.get('/auth/admin/users').then((res) => setUsers(res.data || [])).catch(() => setUsers([]));
  const loadPendingProducts = () => api.get('/products/admin/pending').then((res) => setPendingProducts(res.data || [])).catch(() => setPendingProducts([]));
  const loadOrders = () => api.get('/orders/admin/orders').then((res) => setOrders(res.data || [])).catch(() => setOrders([]));
  const loadDisputes = () => api.get('/orders/admin/disputes').then((res) => setDisputes(res.data || [])).catch(() => setDisputes([]));
  const loadCategories = () => api.get('/categories/admin/all').then((res) => setCategories(res.data || [])).catch(() => setCategories([]));
  const loadInvoiceRequests = () => api.get('/shops/admin/invoice-feature-requests').then((res) => setInvoiceRequests(res.data || [])).catch(() => setInvoiceRequests([]));
  const loadPlatformWallet = () => api.get('/payments/wallet/platform-wallet')
    .then((res) => {
      setPlatformWallet(res.data || null);
      setPlatformWalletError('');
    })
    .catch((err) => {
      setPlatformWallet(null);
      setPlatformWalletError(err?.response?.data?.message || 'Không lấy được ví sàn');
    });

  const loadOverview = async () => {
    setOverviewLoading(true);
    setOverviewError('');
    const requests = await Promise.allSettled([
      api.get('/auth/admin/users'),
      api.get('/products/admin/pending'),
      api.get('/orders/admin/orders'),
      api.get('/orders/admin/disputes'),
      api.get('/shops/admin/invoice-feature-requests')
    ]);
    const setters = [setUsers, setPendingProducts, setOrders, setDisputes, setInvoiceRequests];
    let failedRequests = 0;
    requests.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        setters[index](result.value.data || []);
      } else {
        failedRequests += 1;
      }
    });
    if (failedRequests) {
      setOverviewError(`Không thể tải ${failedRequests}/5 nguồn dữ liệu. Các chỉ số còn lại vẫn được hiển thị.`);
    }
    setOverviewLoading(false);
  };

  useEffect(() => {
    if (!tab) navigate('/admin/dashboard/overview', { replace: true });
  }, [tab, navigate]);

  useEffect(() => {
    if (activeTab === 'overview') loadOverview();
    if (activeTab === 'users') loadUsers();
    if (activeTab === 'products') loadPendingProducts();
    if (activeTab === 'orders') loadOrders();
    if (activeTab === 'disputes') loadDisputes();
    if (activeTab === 'invoice_requests') loadInvoiceRequests();
    if (activeTab === 'finance') loadPlatformWallet();
    if (activeTab === 'categories') loadCategories();
  }, [activeTab]);

  const activeCounts = useMemo(
    () => ({
      users: users.length,
      products: pendingProducts.length,
      orders: orders.length,
      disputes: disputes.length,
      invoice_requests: invoiceRequests.filter((item) => item.status === 'pending').length,
      finance: platformWallet ? 1 : 0,
      categories: categories.length
    }),
    [users, pendingProducts, orders, disputes, invoiceRequests, platformWallet, categories]
  );

  const overview = useMemo(() => {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const currentStart = new Date(startOfToday);
    currentStart.setDate(currentStart.getDate() - 6);
    const previousStart = new Date(currentStart);
    previousStart.setDate(previousStart.getDate() - 7);

    const validOrders = orders.filter((order) => !['cancelled', 'payment_failed', 'refunded'].includes(order.status));
    const sumRevenue = (items) => items.reduce((sum, order) => sum + Number(order.total_price || order.totalPrice || 0), 0);
    const currentOrders = validOrders.filter((order) => {
      const date = getOrderDate(order);
      return date && date >= currentStart;
    });
    const previousOrders = validOrders.filter((order) => {
      const date = getOrderDate(order);
      return date && date >= previousStart && date < currentStart;
    });
    const currentRevenue = sumRevenue(currentOrders);
    const previousRevenue = sumRevenue(previousOrders);
    const percentageChange = (current, previous) => {
      if (!previous) return current ? 100 : 0;
      return ((current - previous) / previous) * 100;
    };

    const revenueByDay = Array.from({ length: 7 }, (_, index) => {
      const date = new Date(currentStart);
      date.setDate(date.getDate() + index);
      const nextDate = new Date(date);
      nextDate.setDate(nextDate.getDate() + 1);
      const dayOrders = validOrders.filter((order) => {
        const orderDate = getOrderDate(order);
        return orderDate && orderDate >= date && orderDate < nextDate;
      });
      return {
        label: date.toLocaleDateString('vi-VN', { weekday: 'short' }),
        dateLabel: date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }),
        revenue: sumRevenue(dayOrders),
        orders: dayOrders.length
      };
    });

    const statusCounts = dashboardOrderStatuses.map((status) => ({
      ...status,
      count: orders.filter((order) => getStatusGroup(order.status) === status.key).length
    }));
    const statusTotal = Math.max(orders.length, 1);
    let statusOffset = 0;
    const donutSegments = statusCounts.map((status) => {
      const start = statusOffset;
      statusOffset += (status.count / statusTotal) * 360;
      return `${status.color} ${start}deg ${statusOffset}deg`;
    });

    const shopMap = new Map();
    validOrders.forEach((order) => {
      const shopId = getOrderShopId(order);
      if (!shopId) return;
      const current = shopMap.get(String(shopId)) || { shopId: String(shopId), orders: 0, revenue: 0 };
      current.orders += 1;
      current.revenue += Number(order.total_price || order.totalPrice || 0);
      shopMap.set(String(shopId), current);
    });

    return {
      buyers: users.filter((user) => user.role === 'buyer'),
      sellers: users.filter((user) => user.role === 'seller'),
      lockedUsers: users.filter((user) => user.isActive === false),
      validOrders,
      totalRevenue: sumRevenue(validOrders),
      averageOrderValue: validOrders.length ? sumRevenue(validOrders) / validOrders.length : 0,
      deliveredOrders: orders.filter((order) => ['delivered', 'paid'].includes(order.status)).length,
      revenueTrend: percentageChange(currentRevenue, previousRevenue),
      orderTrend: percentageChange(currentOrders.length, previousOrders.length),
      revenueByDay,
      maxDailyRevenue: Math.max(...revenueByDay.map((item) => item.revenue), 1),
      statusCounts,
      donutBackground: orders.length ? `conic-gradient(${donutSegments.join(', ')})` : '#e5e7eb',
      topShops: Array.from(shopMap.values()).sort((a, b) => b.revenue - a.revenue).slice(0, 5),
      openDisputes: disputes.filter((item) => item.status === 'open').length,
      pendingInvoiceRequests: invoiceRequests.filter((item) => item.status === 'pending').length
    };
  }, [users, orders, disputes, invoiceRequests]);

  const filteredUsers = useMemo(() => {
    const keyword = userSearch.trim().toLowerCase();
    return users.filter((user) => {
      const matchesKeyword = !keyword || String(user.email || '').toLowerCase().includes(keyword) || String(user.shopId || '').toLowerCase().includes(keyword);
      const matchesRole = userRoleFilter === 'all' || user.role === userRoleFilter;
      const matchesStatus = userStatusFilter === 'all' || (userStatusFilter === 'active' ? user.isActive !== false : user.isActive === false);
      return matchesKeyword && matchesRole && matchesStatus;
    });
  }, [users, userSearch, userRoleFilter, userStatusFilter]);

  async function setUserLock(user, isActive) {
    try {
      const action = isActive ? 'unlock' : 'lock';
      await api.patch(`/auth/admin/users/${user.id}/${action}`);
      showToast(`Đã ${isActive ? 'mở khóa' : 'khóa'} tài khoản`);
      loadUsers();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Thao tác tài khoản thất bại', 'error');
    }
  }

  async function moderateProduct(productId, action) {
    try {
      await api.patch(`/products/admin/${productId}/moderate`, { action });
      showToast(action === 'approve' ? 'Đã duyệt sản phẩm' : 'Đã từ chối sản phẩm');
      loadPendingProducts();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Duyệt sản phẩm thất bại', 'error');
    }
  }

  async function deleteProduct(productId) {
    try {
      await api.delete(`/products/admin/${productId}`);
      showToast('Đã xóa sản phẩm');
      loadPendingProducts();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Xóa thất bại', 'error');
    }
  }

  async function updateOrderStatus(orderId, status) {
    try {
      await api.patch(`/orders/admin/orders/${orderId}/status`, { status });
      showToast('Đã cập nhật trạng thái đơn hàng');
      loadOrders();
    } catch (err) {
      const data = err?.response?.data || {};
      if (data.refundRequired) {
        showToast('Đơn đã giao không thể hủy. Vui lòng xử lý yêu cầu trả hàng/hoàn tiền.', 'error');
        return;
      }
      showToast(data.message || 'Cập nhật thất bại', 'error');
    }
  }

  async function forceCancelOrder(orderId) {
    try {
      await api.post(`/orders/admin/orders/${orderId}/force-cancel`);
      showToast('Đã hủy đơn hàng');
      loadOrders();
    } catch (err) {
      const data = err?.response?.data || {};
      if (data.refundRequired) {
        showToast('Đơn đã giao không thể hủy. Vui lòng xử lý yêu cầu trả hàng/hoàn tiền.', 'error');
        return;
      }
      showToast(data.message || 'Hủy cưỡng bức thất bại', 'error');
    }
  }

  async function updateDispute(disputeId, status) {
    try {
      const response = await api.patch(`/orders/admin/disputes/${disputeId}`, { status });
      if (status === 'resolved' && response.data?.refundQueued) {
        showToast('Đã duyệt yêu cầu và gửi hoàn tiền');
      } else if (status === 'resolved' && response.data?.refundRequired) {
        showToast(response.data?.refundMessage || 'Đã duyệt yêu cầu, cần hoàn tiền thủ công');
      } else {
        showToast(`Đã cập nhật yêu cầu: ${formatDisputeStatus(status)}`);
      }
      loadDisputes();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Cập nhật yêu cầu thất bại', 'error');
    }
  }

  function formatInvoiceMode(mode) {
    if (mode === 'checkout_form') return 'Mở form checkout';
    if (mode === 'off') return 'Ẩn hỗ trợ hóa đơn';
    return 'Khách chat shop';
  }

  async function reviewInvoiceRequest(requestId, action) {
    try {
      await api.patch(`/shops/admin/invoice-feature-requests/${requestId}`, { action });
      showToast(action === 'approve' ? 'Đã duyệt yêu cầu hóa đơn' : 'Đã từ chối yêu cầu hóa đơn');
      loadInvoiceRequests();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Duyệt yêu cầu hóa đơn thất bại', 'error');
    }
  }

  async function saveCategory(category) {
    const id = category._id || category.id;
    const form = categoryForm[id] || {};
    try {
      await api.put(`/categories/admin/${id}`, {
        name: form.name ?? category.name,
        description: form.description ?? category.description,
        shopId: form.shopId ?? category.shopId
      });
      showToast('Đã cập nhật danh mục');
      loadCategories();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Cập nhật danh mục thất bại', 'error');
    }
  }

  async function removeCategory(categoryId) {
    try {
      await api.delete(`/categories/admin/${categoryId}`);
      showToast('Đã xóa danh mục');
      loadCategories();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Xóa danh mục thất bại', 'error');
    }
  }

  if (!tab) return null;

  return (
    <div className="container page-section">
      {activeTab === 'overview' && (
        <div className="admin-overview">
          <div className="admin-overview-header">
            <div>
              <span className="admin-eyebrow">TRUNG TÂM ĐIỀU HÀNH</span>
              <h1>Tổng quan sàn thương mại</h1>
              <p>Theo dõi tăng trưởng, vận hành người mua và chất lượng người bán trong một màn hình.</p>
            </div>
            <div className="admin-overview-actions">
              <span>Cập nhật {new Date().toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })}</span>
              <button type="button" className="btn btn-outline" onClick={loadOverview} disabled={overviewLoading}>
                {overviewLoading ? 'Đang tải...' : 'Làm mới dữ liệu'}
              </button>
            </div>
          </div>

          {overviewError && <div className="admin-data-warning">{overviewError}</div>}

          <section className="admin-kpi-grid" aria-label="Chỉ số kinh doanh chính">
            <article className="admin-kpi-card accent-orange">
              <div className="admin-kpi-heading"><span>Doanh số hợp lệ</span><span className="admin-kpi-icon">₫</span></div>
              <strong>{formatCurrency(overview.totalRevenue)}</strong>
              <div className="admin-kpi-foot"><TrendBadge value={overview.revenueTrend} /><span>so với 7 ngày trước</span></div>
            </article>
            <article className="admin-kpi-card accent-blue">
              <div className="admin-kpi-heading"><span>Đơn hàng</span><span className="admin-kpi-icon">#</span></div>
              <strong>{orders.length.toLocaleString('vi-VN')}</strong>
              <div className="admin-kpi-foot"><TrendBadge value={overview.orderTrend} /><span>{overview.deliveredOrders} đã hoàn tất</span></div>
            </article>
            <article className="admin-kpi-card accent-violet">
              <div className="admin-kpi-heading"><span>Người mua</span><span className="admin-kpi-icon">B</span></div>
              <strong>{overview.buyers.length.toLocaleString('vi-VN')}</strong>
              <div className="admin-kpi-foot"><span className="admin-kpi-note">{overview.buyers.filter((user) => user.isActive !== false).length} đang hoạt động</span></div>
            </article>
            <article className="admin-kpi-card accent-green">
              <div className="admin-kpi-heading"><span>Người bán</span><span className="admin-kpi-icon">S</span></div>
              <strong>{overview.sellers.length.toLocaleString('vi-VN')}</strong>
              <div className="admin-kpi-foot"><span className="admin-kpi-note">{overview.sellers.filter((user) => user.isActive !== false).length} đang hoạt động</span></div>
            </article>
          </section>

          <section className="admin-dashboard-grid">
            <article className="admin-dashboard-card admin-revenue-card">
              <div className="admin-card-header">
                <div><h3>Doanh số 7 ngày gần nhất</h3><p>Đơn hợp lệ, không gồm đơn hủy hoặc hoàn tiền</p></div>
                <div className="admin-card-summary"><span>AOV</span><strong>{formatCurrency(overview.averageOrderValue)}</strong></div>
              </div>
              <div className="admin-revenue-chart" role="img" aria-label="Biểu đồ doanh số bảy ngày gần nhất">
                {overview.revenueByDay.map((item) => (
                  <div className="admin-revenue-column" key={item.dateLabel} title={`${item.dateLabel}: ${formatCurrency(item.revenue)}`}>
                    <div className="admin-bar-value">{item.revenue ? formatCompactCurrency(item.revenue) : '0'}</div>
                    <div className="admin-bar-track"><span style={{ height: `${Math.max((item.revenue / overview.maxDailyRevenue) * 100, item.revenue ? 8 : 2)}%` }} /></div>
                    <strong>{item.label}</strong>
                    <small>{item.dateLabel}</small>
                  </div>
                ))}
              </div>
            </article>

            <article className="admin-dashboard-card admin-status-card">
              <div className="admin-card-header"><div><h3>Trạng thái đơn hàng</h3><p>Phân bố toàn bộ đơn trên hệ thống</p></div></div>
              <div className="admin-donut-layout">
                <div className="admin-donut" style={{ background: overview.donutBackground }}>
                  <div><strong>{orders.length}</strong><span>Tổng đơn</span></div>
                </div>
                <div className="admin-chart-legend">
                  {overview.statusCounts.map((status) => (
                    <div key={status.key}><span className="admin-legend-dot" style={{ background: status.color }} /><span>{status.label}</span><strong>{status.count}</strong></div>
                  ))}
                </div>
              </div>
            </article>

            <article className="admin-dashboard-card">
              <div className="admin-card-header"><div><h3>Cơ cấu người dùng</h3><p>Sức khỏe cộng đồng mua và bán</p></div><button type="button" className="admin-text-button" onClick={() => navigate('/admin/dashboard/users')}>Quản lý</button></div>
              <div className="admin-user-breakdown">
                {[
                  { label: 'Người mua', value: overview.buyers.length, color: '#7c3aed' },
                  { label: 'Người bán', value: overview.sellers.length, color: '#16a34a' },
                  { label: 'Đang bị khóa', value: overview.lockedUsers.length, color: '#ef4444' }
                ].map((item) => (
                  <div key={item.label}>
                    <div className="admin-breakdown-label"><span>{item.label}</span><strong>{item.value}</strong></div>
                    <div className="admin-progress"><span style={{ width: `${users.length ? (item.value / users.length) * 100 : 0}%`, background: item.color }} /></div>
                  </div>
                ))}
              </div>
            </article>

            <article className="admin-dashboard-card">
              <div className="admin-card-header"><div><h3>Cần xử lý</h3><p>Các vấn đề ảnh hưởng trải nghiệm sàn</p></div></div>
              <div className="admin-alert-list">
                <button type="button" onClick={() => navigate('/admin/dashboard/products')}><span className="admin-alert-icon orange">P</span><span><strong>Sản phẩm chờ duyệt</strong><small>Kiểm soát chất lượng niêm yết</small></span><b>{pendingProducts.length}</b></button>
                <button type="button" onClick={() => navigate('/admin/dashboard/disputes')}><span className="admin-alert-icon red">!</span><span><strong>Tranh chấp đang mở</strong><small>Ưu tiên bảo vệ người mua</small></span><b>{overview.openDisputes}</b></button>
                <button type="button" onClick={() => navigate('/admin/dashboard/invoice_requests')}><span className="admin-alert-icon blue">i</span><span><strong>Yêu cầu hóa đơn</strong><small>Chờ thẩm định người bán</small></span><b>{overview.pendingInvoiceRequests}</b></button>
              </div>
            </article>

            <article className="admin-dashboard-card admin-top-shops-card">
              <div className="admin-card-header"><div><h3>Người bán nổi bật</h3><p>Xếp hạng theo doanh số hợp lệ</p></div><button type="button" className="admin-text-button" onClick={() => { setUserRoleFilter('seller'); navigate('/admin/dashboard/users'); }}>Xem tất cả</button></div>
              {overview.topShops.length ? (
                <div className="admin-shop-ranking">
                  {overview.topShops.map((shop, index) => (
                    <div key={shop.shopId}>
                      <span className="admin-rank">{index + 1}</span>
                      <span className="admin-shop-avatar">{shop.shopId.slice(0, 1).toUpperCase()}</span>
                      <span className="admin-shop-name"><strong>{shop.shopId}</strong><small>{shop.orders} đơn hợp lệ</small></span>
                      <strong>{formatCurrency(shop.revenue)}</strong>
                    </div>
                  ))}
                </div>
              ) : <div className="admin-empty-mini">Chưa có dữ liệu doanh số người bán.</div>}
            </article>
          </section>
        </div>
      )}

      {activeTab === 'users' && (
        <>
          <SectionHeader title="Quản lý người mua & người bán" subtitle={`${filteredUsers.length}/${activeCounts.users} tài khoản`} />
          <div className="admin-user-summary">
            <div><span>Người mua</span><strong>{overview.buyers.length}</strong></div>
            <div><span>Người bán</span><strong>{overview.sellers.length}</strong></div>
            <div><span>Tài khoản hoạt động</span><strong>{users.filter((user) => user.isActive !== false).length}</strong></div>
            <div><span>Cần rà soát</span><strong>{overview.lockedUsers.length}</strong></div>
          </div>
          <div className="admin-user-filters">
            <input aria-label="Tìm người dùng" value={userSearch} onChange={(event) => setUserSearch(event.target.value)} placeholder="Tìm theo email hoặc mã shop..." />
            <select aria-label="Lọc theo vai trò" value={userRoleFilter} onChange={(event) => setUserRoleFilter(event.target.value)}>
              <option value="all">Tất cả vai trò</option>
              <option value="buyer">Người mua</option>
              <option value="seller">Người bán</option>
              <option value="admin">Quản trị viên</option>
            </select>
            <select aria-label="Lọc theo trạng thái" value={userStatusFilter} onChange={(event) => setUserStatusFilter(event.target.value)}>
              <option value="all">Tất cả trạng thái</option>
              <option value="active">Đang hoạt động</option>
              <option value="locked">Đã khóa</option>
            </select>
          </div>
          <div className="seller-table admin-table admin-users-table">
            <div className="seller-table-row seller-table-head">
              <div>Email</div>
              <div>Vai trò</div>
              <div>Trạng thái</div>
              <div>Thao tác</div>
            </div>
            {filteredUsers.map((user) => (
              <div key={user.id} className="seller-table-row">
                <div>{user.email}</div>
                <div><span className={`admin-role-badge ${user.role}`}>{user.role === 'buyer' ? 'Người mua' : user.role === 'seller' ? 'Người bán' : 'Quản trị'}</span></div>
                <div><span className={`admin-status-badge ${user.isActive ? 'active' : 'locked'}`}>{user.isActive ? 'Hoạt động' : 'Đã khóa'}</span></div>
                <div>
                  {user.role === 'admin' ? (
                    <span className="muted">Bảo vệ</span>
                  ) : (
                    <button type="button" className="btn btn-ghost" onClick={() => setUserLock(user, !user.isActive)}>
                      {user.isActive ? 'Khóa' : 'Mở khóa'}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
          {!filteredUsers.length && <div className="admin-empty-mini">Không tìm thấy tài khoản phù hợp với bộ lọc.</div>}
        </>
      )}

      {activeTab === 'products' && (
        <>
          <SectionHeader title="Duyệt sản phẩm" subtitle={`${activeCounts.products} chờ duyệt`} />
          <div className="seller-table admin-table admin-products-table">
            <div className="seller-table-row seller-table-head">
              <div>Tên</div>
              <div>Shop</div>
              <div>Giá</div>
              <div>Duyệt</div>
            </div>
            {pendingProducts.map((product) => (
              <div key={product._id || product.id} className="seller-table-row">
                <div>{product.name}</div>
                <div>{product.shopId}</div>
                <div>{Number(product.price || 0).toLocaleString('vi-VN', { style: 'currency', currency: 'VND' })}</div>
                <div className="admin-actions">
                  <button type="button" className="btn btn-primary" onClick={() => moderateProduct(product._id || product.id, 'approve')}>
                    Duyệt
                  </button>
                  <button type="button" className="btn btn-outline" onClick={() => moderateProduct(product._id || product.id, 'reject')}>
                    Từ chối
                  </button>
                  <button type="button" className="btn btn-ghost" onClick={() => deleteProduct(product._id || product.id)}>
                    Xóa
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {activeTab === 'orders' && (
        <>
          <SectionHeader title="Quản lý đơn hàng" subtitle={`${activeCounts.orders} đơn`} />
          <div className="seller-table admin-table admin-orders-table">
            <div className="seller-table-row seller-table-head">
              <div>ID</div>
              <div>Người dùng</div>
              <div>Trạng thái</div>
              <div>Vận đơn</div>
              <div>Ví shop</div>
              <div>Cập nhật</div>
            </div>
            {orders.map((order) => (
              <div key={order.id} className="seller-table-row">
                <div>#{order.id}</div>
                <div>{order.user_id}</div>
                <div>{formatOrderStatus(order.status)}</div>
                <div>{order.shipment_tracking_code || '-'}</div>
                <div>{formatSettlementStatus(order.settlement_status)}</div>
                <div className="admin-actions">
                  <select value={order.status} onChange={(event) => updateOrderStatus(order.id, event.target.value)}>
                    {getSelectableOrderStatuses(order).map((status) => (
                      <option key={status} value={status}>{formatOrderStatus(status)}</option>
                    ))}
                  </select>
                  {order.status === 'delivered' ? (
                    <button type="button" className="btn btn-outline" onClick={() => navigate('/admin/dashboard/disputes')}>
                      Xử lý hoàn tiền
                    </button>
                  ) : (
                    <button type="button" className="btn btn-ghost" onClick={() => forceCancelOrder(order.id)}>
                      Hủy cưỡng bức
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {activeTab === 'disputes' && (
        <>
          <SectionHeader title="Quản lý trả hàng/hoàn tiền" subtitle={`${activeCounts.disputes} phiếu`} />
          <div className="seller-table admin-table admin-disputes-table">
            <div className="seller-table-row seller-table-head">
              <div>ID</div>
              <div>Đơn hàng</div>
              <div>Lý do</div>
              <div>Trạng thái</div>
              <div>Thao tác</div>
            </div>
            {disputes.map((dispute) => (
              <div key={dispute.id} className="seller-table-row">
                <div>#{dispute.id}</div>
                <div>#{dispute.order_id}</div>
                <div>{dispute.reason}</div>
                <div>{formatDisputeStatus(dispute.status)}</div>
                <div className="admin-actions">
                  <button type="button" className="btn btn-primary" onClick={() => updateDispute(dispute.id, 'resolved')}>Giải quyết</button>
                  <button type="button" className="btn btn-outline" onClick={() => updateDispute(dispute.id, 'rejected')}>Từ chối</button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {activeTab === 'finance' && (
        <>
          <SectionHeader title="Ví sàn" subtitle={platformWallet ? `Cập nhật ${new Date(platformWallet.updatedAt).toLocaleString('vi-VN')}` : 'Số dư vận hành'} />
          {platformWalletError && <div className="empty-state">{platformWalletError}</div>}
          {platformWallet && (
            <>
              <div className="admin-finance-grid">
                <div className="admin-finance-tile">
                  <span>Vốn sàn ban đầu</span>
                  <strong>{formatCurrency(platformWallet.initialCapital)}</strong>
                </div>
                <div className="admin-finance-tile">
                  <span>Vốn sàn còn lại</span>
                  <strong>{formatCurrency(platformWallet.capital?.availableBalance)}</strong>
                </div>
                <div className="admin-finance-tile">
                  <span>Tiền sàn giữ hộ</span>
                  <strong>{formatCurrency(platformWallet.clearingHeldAmount)}</strong>
                </div>
              </div>
              <button type="button" className="btn btn-outline" onClick={loadPlatformWallet}>
                Làm mới
              </button>
            </>
          )}
        </>
      )}

      {activeTab === 'invoice_requests' && (
        <>
          <SectionHeader title="Duyệt yêu cầu hóa đơn" subtitle={`${activeCounts.invoice_requests} chờ duyệt`} />
          <div className="seller-table admin-table admin-invoice-requests-table">
            <div className="seller-table-row seller-table-head">
              <div>Shop</div>
              <div>Hiện tại</div>
              <div>Yêu cầu</div>
              <div>Thông tin thuế</div>
              <div>Trạng thái</div>
              <div>Thao tác</div>
            </div>
            {invoiceRequests.map((request) => (
              <div key={request._id || request.id} className="seller-table-row">
                <div>
                  <strong>{request.shopName}</strong>
                  <span className="muted">{request.shopId}</span>
                </div>
                <div>{formatInvoiceMode(request.currentMode)}</div>
                <div>
                  <strong>{formatInvoiceMode(request.requestedMode)}</strong>
                  {request.reason && <span className="muted">{request.reason}</span>}
                </div>
                <div>
                  <span>{formatLegalEntityType(request.legalEntityType)}</span>
                  <span className="muted">{request.taxCode || 'Chưa có MST'}</span>
                  {request.invoiceProvider && <span className="muted">{request.invoiceProvider}</span>}
                </div>
                <div>{request.status === 'pending' ? 'Chờ duyệt' : request.status === 'approved' ? 'Đã duyệt' : 'Từ chối'}</div>
                <div className="admin-actions">
                  {request.status === 'pending' ? (
                    <>
                      <button type="button" className="btn btn-primary" onClick={() => reviewInvoiceRequest(request._id || request.id, 'approve')}>
                        Duyệt
                      </button>
                      <button type="button" className="btn btn-outline" onClick={() => reviewInvoiceRequest(request._id || request.id, 'reject')}>
                        Từ chối
                      </button>
                    </>
                  ) : (
                    <span className="muted">Đã xử lý</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {activeTab === 'categories' && (
        <>
          <SectionHeader title="Quản lý danh mục" subtitle={`${activeCounts.categories} danh mục`} />
          <div className="seller-table admin-table admin-categories-table">
            <div className="seller-table-row seller-table-head">
              <div>Tên</div>
              <div>Mô tả</div>
              <div>Shop</div>
              <div>Thao tác</div>
            </div>
            {categories.map((category) => {
              const id = category._id || category.id;
              const form = categoryForm[id] || {};
              return (
                <div key={id} className="seller-table-row">
                  <div>
                    <input value={form.name ?? category.name ?? ''} onChange={(event) => setCategoryForm((prev) => ({ ...prev, [id]: { ...prev[id], name: event.target.value } }))} />
                  </div>
                  <div>
                    <input value={form.description ?? category.description ?? ''} onChange={(event) => setCategoryForm((prev) => ({ ...prev, [id]: { ...prev[id], description: event.target.value } }))} />
                  </div>
                  <div>
                    <input value={form.shopId ?? category.shopId ?? ''} onChange={(event) => setCategoryForm((prev) => ({ ...prev, [id]: { ...prev[id], shopId: event.target.value } }))} />
                  </div>
                  <div className="admin-actions">
                    <button type="button" className="btn btn-primary" onClick={() => saveCategory(category)}>Lưu</button>
                    <button type="button" className="btn btn-ghost" onClick={() => removeCategory(id)}>Xóa</button>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
