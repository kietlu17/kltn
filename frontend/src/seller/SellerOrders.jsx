import { useEffect, useMemo, useRef, useState } from 'react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import useShopMap from '../hooks/useShopMap';
import { formatOrderStatus, formatPaymentMethod } from '../utils/statusLabels';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
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

function getOrderId(order) {
  return order?.id || order?._id;
}

function canSellerConfirmOrder(order) {
  const method = String(order?.payment_method || '').toLowerCase();
  const status = String(order?.status || '').toLowerCase();
  if (['cancelled', 'payment_failed', 'confirmed', 'shipped', 'delivered', 'refund_processing', 'refunded'].includes(status)) return false;
  if (method === 'cod') {
    return ['pending_payment', 'payment_processing', 'paid'].includes(status);
  }
  return status === 'paid';
}

function canSellerHandoffOrder(order) {
  return String(order?.status || '').toLowerCase() === 'confirmed' && !order?.shipment_tracking_code;
}

function toLocalDateKey(date) {
  const value = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(value.getTime())) return '';
  const year = value.getFullYear();
  const month = `${value.getMonth() + 1}`.padStart(2, '0');
  const day = `${value.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function isToday(value) {
  if (!value) return false;
  const todayKey = toLocalDateKey(new Date());
  return toLocalDateKey(value) === todayKey;
}

function formatInvoiceTarget(type) {
  if (type === 'business_household') return 'Hộ kinh doanh';
  if (type === 'personal') return 'Cá nhân';
  return 'Công ty';
}

export default function SellerOrders() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const shopMap = useShopMap();
  const [orders, setOrders] = useState([]);
  const [buyers, setBuyers] = useState([]);
  const [expandedOrderId, setExpandedOrderId] = useState(null);
  const [printOrder, setPrintOrder] = useState(null);
  const [printBatch, setPrintBatch] = useState([]);
  const [invoiceForms, setInvoiceForms] = useState({});
  const pendingPrintIds = useRef([]);
  const marketplaceName = 'Shopee Lite';

  useEffect(() => {
    const shopKey = user?.shopId || user?.id;
    if (!shopKey) {
      setOrders([]);
      return;
    }
    api.get(`/orders/seller/${shopKey}`).then((res) => setOrders(res.data)).catch(() => setOrders([]));
  }, [user]);

  useEffect(() => {
    api.get('/users').then((res) => setBuyers(res.data)).catch(() => setBuyers([]));
  }, []);

  const buyerMap = useMemo(() => {
    const map = new Map();
    buyers.forEach((buyer) => {
      map.set(buyer.userId || buyer._id || buyer.id, buyer);
    });
    return map;
  }, [buyers]);

  const normalizedOrders = useMemo(
    () => orders.map((order) => ({ ...order, items: normalizeProducts(order) })),
    [orders]
  );

  const shopId = user?.shopId || user?.id;
  const shopName = shopMap.get(shopId)?.name || user?.shopName || 'Shop';

  const printKey = useMemo(() => {
    if (!shopId) return '';
    return `printed_orders_${shopId}_${toLocalDateKey(new Date())}`;
  }, [shopId]);

  const printedOrderIds = useMemo(() => {
    if (!printKey) return new Set();
    try {
      const raw = localStorage.getItem(printKey);
      const parsed = raw ? JSON.parse(raw) : [];
      return new Set(Array.isArray(parsed) ? parsed : []);
    } catch {
      return new Set();
    }
  }, [printKey, printOrder, printBatch]);

  const markPrinted = (ids) => {
    if (!printKey || !ids?.length) return;
    const next = new Set(printedOrderIds);
    ids.forEach((id) => next.add(id));
    localStorage.setItem(printKey, JSON.stringify([...next]));
  };

  useEffect(() => {
    if (!printOrder && printBatch.length === 0) return undefined;
    const ids = printOrder ? [getOrderId(printOrder)] : printBatch.map((order) => getOrderId(order));
    pendingPrintIds.current = ids.filter(Boolean);

    function handleAfterPrint() {
      markPrinted(pendingPrintIds.current);
      pendingPrintIds.current = [];
      setPrintOrder(null);
      setPrintBatch([]);
    }

    window.addEventListener('afterprint', handleAfterPrint);
    const timer = setTimeout(() => window.print(), 50);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('afterprint', handleAfterPrint);
    };
  }, [printOrder, printBatch]);

  async function confirmOrder(orderId) {
    try {
      const response = await api.post(`/orders/${orderId}/confirm`);
      setOrders((prev) =>
        prev.map((order) =>
          (String(getOrderId(order)) === String(orderId)
            ? {
                ...order,
                status: response.data?.status || 'confirmed',
                shipment_tracking_code: response.data?.shipment_tracking_code || order.shipment_tracking_code
              }
            : order)
        )
      );
      showToast('Đã xác nhận đơn. Vui lòng bàn giao cho vận chuyển.');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể xác nhận đơn', 'error');
    }
  }

  async function handoffShipment(orderId) {
    try {
      const response = await api.post(`/orders/${orderId}/shipments`, { carrier: 'mock_carrier' });
      setOrders((prev) =>
        prev.map((order) =>
          (String(getOrderId(order)) === String(orderId)
            ? {
                ...order,
                status: response.data?.order?.status || 'shipped',
                shipment_tracking_code: response.data?.shipment?.tracking_code
              }
            : order)
        )
      );
      showToast('Đã gửi yêu cầu vận chuyển');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể bàn giao vận chuyển', 'error');
    }
  }

  async function issueInvoice(orderId) {
    const form = invoiceForms[orderId] || {};
    if (!form.invoiceNumber?.trim()) {
      showToast('Vui lòng nhập số hóa đơn', 'error');
      return;
    }
    try {
      const response = await api.patch(`/orders/${orderId}/invoice`, {
        invoiceNumber: form.invoiceNumber,
        lookupUrl: form.lookupUrl || '',
        note: form.note || ''
      });
      setOrders((prev) =>
        prev.map((order) => (String(getOrderId(order)) === String(orderId) ? response.data : order))
      );
      setInvoiceForms((prev) => ({ ...prev, [orderId]: { invoiceNumber: '', lookupUrl: '', note: '' } }));
      showToast('Đã cập nhật trạng thái hóa đơn');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể cập nhật hóa đơn', 'error');
    }
  }

  function updateInvoiceForm(orderId, field, value) {
    setInvoiceForms((prev) => ({
      ...prev,
      [orderId]: {
        invoiceNumber: '',
        lookupUrl: '',
        note: '',
        ...(prev[orderId] || {}),
        [field]: value
      }
    }));
  }

  const handlePrintToday = () => {
    const todayOrders = normalizedOrders.filter((order) => isToday(order.created_at || order.createdAt));
    const printable = todayOrders.filter((order) => !printedOrderIds.has(getOrderId(order)));
    if (!printable.length) {
      showToast('Hôm nay không còn đơn chưa in');
      return;
    }
    setPrintBatch(printable);
  };

  const handleConfirmAll = async () => {
    const pendingOrders = normalizedOrders.filter((order) => canSellerConfirmOrder(order));
    if (!pendingOrders.length) {
      showToast('Không có đơn đủ điều kiện để xác nhận');
      return;
    }
    try {
      await Promise.all(pendingOrders.map((order) => api.post(`/orders/${getOrderId(order)}/confirm`)));
      const confirmedIds = new Set(pendingOrders.map((order) => order.id || order._id).filter(Boolean));
      setOrders((prev) => prev.map((order) => (confirmedIds.has(order.id || order._id) ? { ...order, status: 'confirmed' } : order)));
      showToast(`Đã xác nhận ${pendingOrders.length} đơn`);
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể xác nhận tất cả đơn', 'error');
    }
  };

  function getRecipient(order) {
    return (
      buyerMap.get(order.user_id || order.userId)?.name
      || order.shipping_address?.fullName
      || order.shippingAddress?.fullName
      || 'Người mua chưa rõ'
    );
  }

  function getAddress(order) {
    const address = order.shipping_address || order.shippingAddress || {};
    const parts = [address.line1, address.line2, address.ward, address.district, address.city, address.state, address.postalCode].filter(Boolean);
    return parts.length ? parts.join(', ') : 'Không có';
  }

  return (
    <div className="container page-section">
      <div className="section-header">
        <h2>Đơn hàng người bán</h2>
        <div className="section-actions">
          <span className="section-link">{orders.length} đơn</span>
          <button type="button" className="btn btn-ghost" onClick={handleConfirmAll}>Xác nhận tất cả</button>
          <button type="button" className="btn btn-outline" onClick={handlePrintToday}>In hôm nay</button>
        </div>
      </div>

      <div className="orders-table">
        <div className="orders-row orders-head seller-orders-row">
          <div>Mã đơn</div>
          <div>Sản phẩm</div>
          <div>Tổng tiền</div>
          <div>Người mua</div>
          <div>Thanh toán</div>
          <div>Giao hàng</div>
          <div>Trạng thái</div>
          <div>Thao tác</div>
        </div>

        {normalizedOrders.map((order) => {
          const orderId = order.id || order._id;
          return (
            <div key={orderId}>
              <div className="orders-row seller-orders-row clickable" onClick={() => setExpandedOrderId((prev) => (prev === orderId ? null : orderId))}>
                <div>#{orderId}</div>
                <div className="muted">{order.items.map((item) => `${item.productName || item.productId} x${item.quantity}`).join(', ')}</div>
                <div>{formatPrice(order.total_price || order.total)}</div>
                <div>{getRecipient(order)}</div>
                <div>{formatPaymentMethod(order.payment_method)}</div>
                <div className="muted">{order.shipping_address?.line1 || order.shippingAddress?.line1 || 'Không có'}</div>
                <div className={`status ${order.status}`}>{formatOrderStatus(order.status)}</div>
                <div>
                  {canSellerConfirmOrder(order) ? (
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={(event) => {
                        event.stopPropagation();
                        confirmOrder(orderId);
                      }}
                    >
                      Xác nhận
                    </button>
                  ) : canSellerHandoffOrder(order) ? (
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={(event) => {
                        event.stopPropagation();
                        handoffShipment(orderId);
                      }}
                    >
                      Tạo vận đơn
                    </button>
                  ) : (
                    <span className="muted">-</span>
                  )}
                </div>
              </div>

              {expandedOrderId === orderId && (
                <div className="order-detail">
                  <div className="order-detail-meta">
                    <div>
                      <span className="muted">Shop</span>
                      <strong>{shopName}</strong>
                    </div>
                    <div>
                      <span className="muted">Người nhận</span>
                      <strong>{getRecipient(order)}</strong>
                    </div>
                    <div>
                      <span className="muted">Địa chỉ</span>
                      <strong>{getAddress(order)}</strong>
                    </div>
                    <div>
                      <span className="muted">Sàn thương mại</span>
                      <strong>{marketplaceName}</strong>
                    </div>
                    <div>
                      <span className="muted">Vận đơn</span>
                      <strong>{order.shipment_tracking_code || 'Chưa tạo vận đơn'}</strong>
                    </div>
                  </div>

                  <div className="order-detail-head">Sản phẩm trong đơn</div>
                  <div className="order-detail-row order-detail-labels">
                    <span>Sản phẩm</span>
                    <span>SL</span>
                    <span>Giá</span>
                    <span>Tạm tính</span>
                  </div>

                  {order.items.map((item, idx) => (
                    <div key={`${order.id}-${idx}`} className="order-detail-row">
                      <span>{item.productName || item.productId}</span>
                      <span>x{item.quantity}</span>
                      <span>{formatPrice(item.price)}</span>
                      <span>{formatPrice(Number(item.price || 0) * Number(item.quantity || 0))}</span>
                    </div>
                  ))}

                  {order.invoice_request?.requested && (
                    <div className="invoice-summary">
                      <div className="order-detail-head">Yêu cầu hóa đơn điện tử</div>
                      <div className="order-detail-meta">
                        <div>
                          <span className="muted">Đối tượng</span>
                          <strong>{formatInvoiceTarget(order.invoice_request.targetType)}</strong>
                        </div>
                        <div>
                          <span className="muted">Tên trên hóa đơn</span>
                          <strong>{order.invoice_request.buyerName}</strong>
                        </div>
                        <div>
                          <span className="muted">Mã số thuế</span>
                          <strong>{order.invoice_request.taxCode || 'Không có'}</strong>
                        </div>
                        <div>
                          <span className="muted">Email nhận</span>
                          <strong>{order.invoice_request.email}</strong>
                        </div>
                        <div>
                          <span className="muted">Địa chỉ hóa đơn</span>
                          <strong>{order.invoice_request.address}</strong>
                        </div>
                        <div>
                          <span className="muted">Giá VAT</span>
                          <strong>Giá đã bao gồm VAT nếu áp dụng</strong>
                        </div>
                        <div>
                          <span className="muted">Trạng thái</span>
                          <strong>{order.invoice_request.status === 'issued' ? 'Đã xuất hóa đơn' : 'Chờ xuất hóa đơn'}</strong>
                        </div>
                        {order.invoice_request.invoiceNumber && (
                          <div>
                            <span className="muted">Số hóa đơn</span>
                            <strong>{order.invoice_request.invoiceNumber}</strong>
                          </div>
                        )}
                      </div>
                      {order.invoice_request.note && <div className="muted">Ghi chú: {order.invoice_request.note}</div>}
                      {order.invoice_request.status === 'issued' ? (
                        order.invoice_request.lookupUrl && (
                          <a className="section-link" href={order.invoice_request.lookupUrl} target="_blank" rel="noreferrer">
                            Mở link tra cứu hóa đơn
                          </a>
                        )
                      ) : (
                        <div className="invoice-issue-form">
                          <input
                            value={invoiceForms[orderId]?.invoiceNumber || ''}
                            onChange={(event) => updateInvoiceForm(orderId, 'invoiceNumber', event.target.value)}
                            placeholder="Số hóa đơn"
                          />
                          <input
                            value={invoiceForms[orderId]?.lookupUrl || ''}
                            onChange={(event) => updateInvoiceForm(orderId, 'lookupUrl', event.target.value)}
                            placeholder="Link tra cứu nếu có"
                          />
                          <input
                            value={invoiceForms[orderId]?.note || ''}
                            onChange={(event) => updateInvoiceForm(orderId, 'note', event.target.value)}
                            placeholder="Ghi chú nội bộ"
                          />
                          <button type="button" className="btn btn-outline" onClick={() => issueInvoice(orderId)}>
                            Đánh dấu đã xuất
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="order-detail-actions">
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={() => {
                        const id = getOrderId(order);
                        if (printedOrderIds.has(id)) {
                          showToast('Đơn đã được in hôm nay');
                          return;
                        }
                        setPrintOrder(order);
                      }}
                    >
                      In đơn
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {printOrder && (
        <div className="print-area">
          <div className="print-page">
            <div className="print-header">
              <div>
                <h2>Đơn #{printOrder.id || printOrder._id}</h2>
                <div className="muted">
                  {printOrder.created_at || printOrder.createdAt ? new Date(printOrder.created_at || printOrder.createdAt).toLocaleString('vi-VN') : ''}
                </div>
              </div>
              <div className="print-brand">{marketplaceName}</div>
            </div>
            <div className="print-section">
              <div>
                <strong>Shop</strong>
                <div>{shopName}</div>
              </div>
              <div>
                <strong>Người nhận</strong>
                <div>{getRecipient(printOrder)}</div>
              </div>
              <div>
                <strong>Địa chỉ</strong>
                <div>{getAddress(printOrder)}</div>
              </div>
            </div>
            <div className="print-section">
              <strong>Sản phẩm trong đơn</strong>
              <div className="print-items">
                <div className="print-row print-head">
                  <span>Sản phẩm</span>
                  <span>SL</span>
                  <span>Giá</span>
                  <span>Tạm tính</span>
                </div>
                {normalizeProducts(printOrder).map((item, idx) => (
                  <div key={`print-${printOrder.id || printOrder._id}-${idx}`} className="print-row">
                    <span>{item.productName || item.productId}</span>
                    <span>x{item.quantity}</span>
                    <span>{formatPrice(item.price)}</span>
                    <span>{formatPrice(Number(item.price || 0) * Number(item.quantity || 0))}</span>
                  </div>
                ))}
              </div>
              <div className="print-total">Tổng: {formatPrice(printOrder.total_price || printOrder.total)}</div>
            </div>
          </div>
        </div>
      )}

      {printBatch.length > 0 && (
        <div className="print-area">
          {printBatch.map((order) => (
            <div key={`batch-${getOrderId(order)}`} className="print-page">
              <div className="print-header">
                <div>
                  <h2>Đơn #{getOrderId(order)}</h2>
                  <div className="muted">{new Date().toLocaleDateString('vi-VN')}</div>
                </div>
                <div className="print-brand">{marketplaceName}</div>
              </div>
              <div className="print-section">
                <div>
                  <strong>Shop</strong>
                  <div>{shopName}</div>
                </div>
                <div>
                  <strong>Người nhận</strong>
                  <div>{getRecipient(order)}</div>
                </div>
                <div>
                  <strong>Địa chỉ</strong>
                  <div>{getAddress(order)}</div>
                </div>
                <div>
                  <strong>Thanh toán</strong>
                  <div>{formatPaymentMethod(order.payment_method)}</div>
                </div>
              </div>
              <div className="print-section">
                <strong>Sản phẩm trong đơn</strong>
                <div className="print-items">
                  <div className="print-row print-head">
                    <span>Sản phẩm</span>
                    <span>SL</span>
                    <span>Giá</span>
                    <span>Tạm tính</span>
                  </div>
                  {normalizeProducts(order).map((item, idx) => (
                    <div key={`batch-${getOrderId(order)}-${idx}`} className="print-row">
                      <span>{item.productName || item.productId}</span>
                      <span>x{item.quantity}</span>
                      <span>{formatPrice(item.price)}</span>
                      <span>{formatPrice(Number(item.price || 0) * Number(item.quantity || 0))}</span>
                    </div>
                  ))}
                </div>
                <div className="print-total">Tổng: {formatPrice(order.total_price || order.total)}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
