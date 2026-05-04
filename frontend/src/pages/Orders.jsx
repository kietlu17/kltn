import { useEffect, useMemo, useState } from 'react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

function formatDate(value) {
  if (!value) return 'Không có';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Không có';
  return date.toLocaleString('vi-VN');
}

function normalizeProducts(order) {
  if (Array.isArray(order.products)) return order.products;
  if (typeof order.products === 'string') {
    try {
      return JSON.parse(order.products);
    } catch {
      return [];
    }
  }
  return [];
}

const statusSteps = [
  { key: 'pending_payment', label: 'Đã đặt' },
  { key: 'payment_processing', label: 'Đang xử lý thanh toán' },
  { key: 'paid', label: 'Đã thanh toán' },
  { key: 'confirmed', label: 'Đã xác nhận' },
  { key: 'shipped', label: 'Đang giao' },
  { key: 'delivered', label: 'Đã giao' }
];

const statusLabels = {
  all: 'Tất cả',
  pending_payment: 'Chờ thanh toán',
  payment_processing: 'Đang xử lý thanh toán',
  paid: 'Đã thanh toán',
  confirmed: 'Đã xác nhận',
  shipped: 'Đang giao',
  delivered: 'Đã giao',
  payment_failed: 'Thanh toán thất bại',
  cancelled: 'Đã hủy'
};

function getStatusIndex(status) {
  if (!status) return 0;
  const normalized = status.toLowerCase();
  if (normalized === 'completed') return 5;
  const index = statusSteps.findIndex((step) => step.key === normalized);
  return index === -1 ? 0 : index;
}

export default function Orders({ embedded = false }) {
  const [orders, setOrders] = useState([]);
  const [activeStatus, setActiveStatus] = useState('all');
  const [expandedOrderId, setExpandedOrderId] = useState(null);
  const [disputeForm, setDisputeForm] = useState({});
  const [sepayQrByOrder, setSepayQrByOrder] = useState({});
  const [loadingQrOrderId, setLoadingQrOrderId] = useState(null);
  const { user } = useAuth();
  const { showToast } = useToast();
  const userId = user?.id || '';

  const load = () => {
    if (!userId) {
      setOrders([]);
      return;
    }
    api.get(`/orders/${userId}`).then((res) => setOrders(res.data)).catch(() => setOrders([]));
  };

  useEffect(() => {
    load();
  }, [userId]);

  async function cancel(id) {
    try {
      await api.post(`/orders/${id}/cancel`);
      showToast('Đã hủy đơn hàng. Hoàn tiền sẽ được trả về ví nếu đủ điều kiện.');
      load();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Hủy đơn hàng thất bại', 'error');
    }
  }

  async function createDispute(orderId) {
    const selectedOrder = orders.find((order) => String(order.id || order._id) === String(orderId));
    if (selectedOrder?.status !== 'delivered') {
      showToast('Chỉ có thể yêu cầu trả hàng khi đơn đã giao', 'error');
      return;
    }

    const current = disputeForm[orderId] || {};
    if (!current.reason) {
      showToast('Vui lòng chọn lý do khiếu nại', 'error');
      return;
    }

    try {
      await api.post(`/orders/${orderId}/disputes`, {
        reason: current.reason,
        note: current.note || '',
        evidenceText: current.evidenceText || ''
      });
      showToast('Đã gửi yêu cầu khiếu nại');
      setDisputeForm((prev) => ({ ...prev, [orderId]: { reason: '', note: '', evidenceText: '' } }));
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể gửi khiếu nại', 'error');
    }
  }

  async function continueBankTransferPayment(order) {
    const orderId = Number(order?.id || order?._id);
    const userId = user?.id;
    const amount = Number(order?.total_price || order?.total || 0);
    if (!Number.isFinite(orderId) || !userId || !Number.isFinite(amount) || amount <= 0) {
      showToast('Không đủ thông tin để tạo QR thanh toán', 'error');
      return;
    }

    setLoadingQrOrderId(orderId);
    try {
      const res = await api.post(`/payments/sepay/orders/${orderId}/qr`, { userId, amount });
      setSepayQrByOrder((prev) => ({ ...prev, [orderId]: res.data }));
      showToast('Đã tạo mã QR thanh toán');
      setExpandedOrderId(orderId);
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể tạo mã QR thanh toán', 'error');
    } finally {
      setLoadingQrOrderId(null);
    }
  }

  const statusFilters = ['all', 'pending_payment', 'payment_processing', 'paid', 'confirmed', 'shipped', 'delivered', 'payment_failed', 'cancelled'];
  const normalizedOrders = useMemo(
    () =>
      orders.map((order) => ({
        ...order,
        items: normalizeProducts(order)
      })),
    [orders]
  );

  const filteredOrders =
    activeStatus === 'all'
      ? normalizedOrders
      : normalizedOrders.filter((order) => order.status === activeStatus);

  const content = (
    <>
      <div className="section-header">
        <h2>Theo dõi đơn hàng</h2>
        <span className="section-link">{orders.length} đơn hàng</span>
      </div>

      <div className="orders-filters">
        {statusFilters.map((status) => (
          <button
            key={status}
            className={`btn ${activeStatus === status ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setActiveStatus(status)}
          >
            {statusLabels[status] || status}
          </button>
        ))}
      </div>

      <div className="orders-table">
        <div className="orders-row orders-head">
          <div>Mã đơn</div>
          <div>Sản phẩm</div>
          <div>Tổng tiền</div>
          <div>Thanh toán</div>
          <div>Giao đến</div>
          <div>Trạng thái</div>
          <div>Thao tác</div>
        </div>

        {filteredOrders.map((order) => {
          const orderId = order.id || order._id;
          const stepIndex = getStatusIndex(order.status);
          return (
            <div key={orderId}>
              <div
                className="orders-row clickable"
                onClick={() => setExpandedOrderId((prev) => (prev === orderId ? null : orderId))}
              >
                <div>#{orderId}</div>
                <div>{order.items?.length || 0} sản phẩm</div>
                <div>{formatPrice(order.total_price || order.total)}</div>
                <div>{order.payment_method || 'Không có'}</div>
                <div className="muted">{order.shipping_address?.line1 || order.shippingAddress?.line1 || 'Không có'}</div>
                <div className={`status ${order.status}`}>{statusLabels[order.status] || order.status}</div>
                <div>
                  {order.status !== 'cancelled' && order.status !== 'delivered' ? (
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={(event) => {
                        event.stopPropagation();
                        cancel(orderId);
                      }}
                    >
                      Hủy đơn
                    </button>
                  ) : (
                    <span className="muted">-</span>
                  )}
                  {order.status === 'payment_processing' && String(order.payment_method || '').toLowerCase() === 'bank_transfer' && (
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={(event) => {
                        event.stopPropagation();
                        continueBankTransferPayment(order);
                      }}
                      disabled={loadingQrOrderId === orderId}
                    >
                      {loadingQrOrderId === orderId ? 'Đang tạo QR...' : 'Tiếp tục thanh toán'}
                    </button>
                  )}
                </div>
              </div>

              {expandedOrderId === orderId && (
                <div className="order-detail">
                  <div className="order-detail-meta">
                    <div>
                      <span className="muted">Ngày đặt</span>
                      <strong>{formatDate(order.created_at || order.createdAt)}</strong>
                    </div>
                    <div>
                      <span className="muted">Thanh toán</span>
                      <strong>{order.payment_method || 'Không có'}</strong>
                    </div>
                    <div>
                      <span className="muted">Giao đến</span>
                      <strong>{order.shipping_address?.line1 || order.shippingAddress?.line1 || 'Không có'}</strong>
                    </div>
                    <div>
                      <span className="muted">Tổng tiền</span>
                      <strong>{formatPrice(order.total_price || order.total)}</strong>
                    </div>
                  </div>

                  {order.status === 'cancelled' ? (
                    <div className="order-cancelled">Đơn hàng đã hủy</div>
                  ) : (
                    <div className="order-progress">
                      {statusSteps.map((step, index) => {
                        const isCompleted = index < stepIndex;
                        const isActive = index === stepIndex;
                        return (
                          <div key={step.key} className={`order-step ${isCompleted ? 'completed' : ''} ${isActive ? 'active' : ''}`}>
                            <span className="dot" />
                            <span>{step.label}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {order.status === 'payment_processing' && String(order.payment_method || '').toLowerCase() === 'bank_transfer' && sepayQrByOrder[orderId] && (
                    <div className="sepay-qr-box">
                      <div className="sepay-qr-head">
                        <strong>Quét mã để thanh toán đơn #{orderId}</strong>
                        <span className="sepay-status pending">Hiệu lực 5 phút</span>
                      </div>
                      <div className="sepay-qr-grid">
                        <img src={sepayQrByOrder[orderId].qrUrl} alt={`SePay QR ${orderId}`} />
                        <div className="sepay-qr-meta">
                          <div><span className="muted">Số tiền</span><strong>{formatPrice(sepayQrByOrder[orderId].amount)}</strong></div>
                          <div><span className="muted">Ngân hàng</span><strong>{sepayQrByOrder[orderId].bankCode}</strong></div>
                          <div><span className="muted">Tài khoản</span><strong>{sepayQrByOrder[orderId].accountNumber}</strong></div>
                          <div><span className="muted">Nội dung</span><strong>{sepayQrByOrder[orderId].requestCode}</strong></div>
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="order-detail-head">Chi tiết mua hàng</div>
                  <div className="order-detail-row order-detail-labels">
                    <span>Sản phẩm</span>
                    <span>SL</span>
                    <span>Giá</span>
                    <span>Tạm tính</span>
                  </div>

                  {order.items?.map((item, idx) => (
                    <div key={`${orderId}-${idx}`} className="order-detail-row">
                      <span>{item.productName || item.productId}{item.variantName ? ` (${item.variantName})` : ''}</span>
                      <span>x{item.quantity}</span>
                      <span>{formatPrice(item.price)}</span>
                      <span>{formatPrice(Number(item.price || 0) * Number(item.quantity || 0))}</span>
                    </div>
                  ))}

                  {order.status === 'delivered' && (
                    <div className="order-dispute-box">
                      <div className="order-detail-head">Yêu cầu trả hàng</div>
                      <div className="form-grid">
                        <div>
                          <label>Lý do</label>
                          <select
                            value={disputeForm[orderId]?.reason || ''}
                            onChange={(event) =>
                              setDisputeForm((prev) => ({
                                ...prev,
                                [orderId]: { ...(prev[orderId] || {}), reason: event.target.value }
                              }))
                            }
                          >
                            <option value="">Chọn lý do</option>
                            <option value="missing_item">Thiếu sản phẩm</option>
                            <option value="damaged_item">Sản phẩm hư hỏng</option>
                            <option value="wrong_item">Giao sai sản phẩm</option>
                            <option value="late_delivery">Giao hàng trễ</option>
                          </select>
                        </div>
                        <div>
                          <label>Bằng chứng</label>
                          <input
                            placeholder="Thêm thông tin bằng chứng"
                            value={disputeForm[orderId]?.evidenceText || ''}
                            onChange={(event) =>
                              setDisputeForm((prev) => ({
                                ...prev,
                                [orderId]: { ...(prev[orderId] || {}), evidenceText: event.target.value }
                              }))
                            }
                          />
                        </div>
                      </div>
                      <textarea
                        placeholder="Mô tả vấn đề của bạn"
                        value={disputeForm[orderId]?.note || ''}
                        onChange={(event) =>
                          setDisputeForm((prev) => ({
                            ...prev,
                            [orderId]: { ...(prev[orderId] || {}), note: event.target.value }
                          }))
                        }
                      />
                      <div className="form-actions">
                        <button type="button" className="btn btn-outline" onClick={() => createDispute(orderId)}>
                          Gửi khiếu nại
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );

  if (embedded) {
    return content;
  }

  return <div className="container page-section">{content}</div>;
}
