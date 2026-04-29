import { useEffect, useMemo, useRef, useState } from 'react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import useShopMap from '../hooks/useShopMap';

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

export default function SellerOrders() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const shopMap = useShopMap();
  const [orders, setOrders] = useState([]);
  const [buyers, setBuyers] = useState([]);
  const [expandedOrderId, setExpandedOrderId] = useState(null);
  const [printOrder, setPrintOrder] = useState(null);
  const [printBatch, setPrintBatch] = useState([]);
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
      setOrders((prev) => prev.map((order) => (order.id === orderId ? { ...order, status: response.data?.status || 'confirmed' } : order)));
      showToast('Đã xác nhận đơn');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể xác nhận đơn', 'error');
    }
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
    const pendingOrders = normalizedOrders.filter((order) => order.status === 'paid');
    if (!pendingOrders.length) {
      showToast('Không có đơn đã thanh toán để xác nhận');
      return;
    }
    try {
      await Promise.all(pendingOrders.map((order) => api.post(`/orders/${getOrderId(order)}/confirm`)));
      setOrders((prev) => prev.map((order) => (order.status === 'paid' ? { ...order, status: 'confirmed' } : order)));
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
                <div>{order.payment_method || 'Không có'}</div>
                <div className="muted">{order.shipping_address?.line1 || order.shippingAddress?.line1 || 'Không có'}</div>
                <div className={`status ${order.status}`}>{order.status}</div>
                <div>
                  {order.status === 'paid' ? (
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
                  <div>{order.payment_method || 'Không có'}</div>
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
