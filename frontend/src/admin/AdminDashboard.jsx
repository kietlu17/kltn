import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import api from '../services/api';
import { useToast } from '../context/ToastContext.jsx';

const orderStatuses = ['pending_payment', 'payment_processing', 'paid', 'confirmed', 'shipped', 'delivered', 'payment_failed', 'cancelled'];
const codOrderStatuses = ['pending_payment', 'confirmed', 'shipped', 'paid', 'payment_failed', 'cancelled'];

function isCodOrder(order) {
  return String(order?.payment_method || '').toLowerCase() === 'cod';
}

function SectionHeader({ title, subtitle }) {
  return (
    <div className="section-header">
      <h2>{title}</h2>
      <span className="section-link">{subtitle}</span>
    </div>
  );
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
  const [categoryForm, setCategoryForm] = useState({});

  const loadUsers = () => api.get('/auth/admin/users').then((res) => setUsers(res.data || [])).catch(() => setUsers([]));
  const loadPendingProducts = () => api.get('/products/admin/pending').then((res) => setPendingProducts(res.data || [])).catch(() => setPendingProducts([]));
  const loadOrders = () => api.get('/orders/admin/orders').then((res) => setOrders(res.data || [])).catch(() => setOrders([]));
  const loadDisputes = () => api.get('/orders/admin/disputes').then((res) => setDisputes(res.data || [])).catch(() => setDisputes([]));
  const loadCategories = () => api.get('/categories/admin/all').then((res) => setCategories(res.data || [])).catch(() => setCategories([]));

  useEffect(() => {
    if (!tab) navigate('/admin/dashboard/users', { replace: true });
  }, [tab, navigate]);

  useEffect(() => {
    if (activeTab === 'users') loadUsers();
    if (activeTab === 'products') loadPendingProducts();
    if (activeTab === 'orders') loadOrders();
    if (activeTab === 'disputes') loadDisputes();
    if (activeTab === 'categories') loadCategories();
  }, [activeTab]);

  const activeCounts = useMemo(
    () => ({
      users: users.length,
      products: pendingProducts.length,
      orders: orders.length,
      disputes: disputes.length,
      categories: categories.length
    }),
    [users, pendingProducts, orders, disputes, categories]
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
      showToast(err?.response?.data?.message || 'Cập nhật thất bại', 'error');
    }
  }

  async function forceCancelOrder(orderId) {
    try {
      await api.post(`/orders/admin/orders/${orderId}/force-cancel`);
      showToast('Đã hủy đơn hàng');
      loadOrders();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Hủy cưỡng bức thất bại', 'error');
    }
  }

  async function updateDispute(disputeId, status) {
    try {
      await api.patch(`/orders/admin/disputes/${disputeId}`, { status });
      showToast(`Đã cập nhật khiếu nại: ${status}`);
      loadDisputes();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Cập nhật khiếu nại thất bại', 'error');
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
              <div>Cập nhật</div>
            </div>
            {orders.map((order) => (
              <div key={order.id} className="seller-table-row">
                <div>#{order.id}</div>
                <div>{order.user_id}</div>
                <div>{order.status}</div>
                <div className="admin-actions">
                  <select value={order.status} onChange={(event) => updateOrderStatus(order.id, event.target.value)}>
                    {(isCodOrder(order) ? codOrderStatuses : orderStatuses).map((status) => (
                      <option key={status} value={status}>{status}</option>
                    ))}
                  </select>
                  <button type="button" className="btn btn-ghost" onClick={() => forceCancelOrder(order.id)}>
                    Hủy cưỡng bức
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {activeTab === 'disputes' && (
        <>
          <SectionHeader title="Quản lý khiếu nại" subtitle={`${activeCounts.disputes} phiếu`} />
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
                <div>{dispute.status}</div>
                <div className="admin-actions">
                  <button type="button" className="btn btn-primary" onClick={() => updateDispute(dispute.id, 'resolved')}>Giải quyết</button>
                  <button type="button" className="btn btn-outline" onClick={() => updateDispute(dispute.id, 'rejected')}>Từ chối</button>
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
