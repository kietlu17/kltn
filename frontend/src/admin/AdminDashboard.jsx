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

export default function AdminDashboard() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const activeTab = tab || 'users';

  const [users, setUsers] = useState([]);
  const [pendingProducts, setPendingProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [disputes, setDisputes] = useState([]);
  const [categories, setCategories] = useState([]);
  const [invoiceRequests, setInvoiceRequests] = useState([]);
  const [categoryForm, setCategoryForm] = useState({});
  const [platformWallet, setPlatformWallet] = useState(null);
  const [platformWalletError, setPlatformWalletError] = useState('');

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

  useEffect(() => {
    if (!tab) navigate('/admin/dashboard/users', { replace: true });
  }, [tab, navigate]);

  useEffect(() => {
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
      {activeTab === 'users' && (
        <>
          <SectionHeader title="Quản lý người dùng" subtitle={`${activeCounts.users} tài khoản`} />
          <div className="seller-table admin-table admin-users-table">
            <div className="seller-table-row seller-table-head">
              <div>Email</div>
              <div>Vai trò</div>
              <div>Trạng thái</div>
              <div>Thao tác</div>
            </div>
            {users.map((user) => (
              <div key={user.id} className="seller-table-row">
                <div>{user.email}</div>
                <div>{user.role}</div>
                <div>{user.isActive ? 'hoạt động' : 'đã khóa'}</div>
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
