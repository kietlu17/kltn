import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import api from '../services/api';
import { useToast } from '../context/ToastContext.jsx';
import { formatOrderStatus } from '../utils/statusLabels';

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('vi-VN');
}

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

function parseOrderItems(order) {
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

function getPrimaryShopId(order) {
  return parseOrderItems(order).find((item) => item?.shopId)?.shopId || order?.shopId || '';
}

function statusText(status) {
  const labels = {
    requested: 'Đã nhận yêu cầu',
    handed_over: 'Cửa hàng đã bàn giao',
    picked_up: 'Đơn vị vận chuyển đã nhận hàng',
    in_transit: 'Đang vận chuyển',
    delivered: 'Đã giao',
    failed: 'Giao thất bại'
  };
  return labels[String(status || '').toLowerCase()] || '-';
}

export default function CarrierSimulator() {
  const [searchParams] = useSearchParams();
  const { showToast } = useToast();
  const initialTrackingCode = useMemo(() => searchParams.get('trackingCode') || '', [searchParams]);
  const [trackingCode, setTrackingCode] = useState(initialTrackingCode);
  const [lastResult, setLastResult] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState('');
  const [remittanceLoading, setRemittanceLoading] = useState(false);

  async function sendCallback(status) {
    const code = trackingCode.trim();
    if (!code) {
      showToast('Vui long nhap ma van don', 'error');
      return;
    }
    setLoadingStatus(status);
    try {
      const res = await api.post('/orders/shipping/callback', {
        trackingCode: code,
        status,
        eventTime: new Date().toISOString()
      });
      setLastResult(res.data || null);
      showToast(status === 'delivered' ? 'Đã gửi tín hiệu giao thành công' : 'Đã gửi tín hiệu đơn vị vận chuyển nhận hàng');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Gửi tín hiệu thất bại', 'error');
    } finally {
      setLoadingStatus('');
    }
  }

  const order = lastResult?.order;
  const shipment = lastResult?.shipment;
  const isCodDelivered =
    String(order?.payment_method || '').toLowerCase() === 'cod' &&
    String(order?.status || '').toLowerCase() === 'delivered';
  const codAmount = Number(order?.total_price || order?.totalPrice || 0);

  async function remitCod() {
    const shopId = getPrimaryShopId(order);
    if (!order?.id || !shopId || !Number.isFinite(codAmount) || codAmount <= 0) {
      showToast('Không đủ thông tin nộp COD', 'error');
      return;
    }
    setRemittanceLoading(true);
    try {
      const res = await api.post('/payments/wallet/cod-remittances', {
        orderId: order.id,
        shopId,
        amount: codAmount,
        carrier: shipment?.carrier || 'mock_carrier',
        referenceId: `carrier:${shipment?.tracking_code || trackingCode}:cod`
      });
      setLastResult((prev) => ({
        ...(prev || {}),
        codRemittance: res.data,
        order: prev?.order
          ? { ...prev.order, settlement_status: 'pending' }
          : prev?.order
      }));
      showToast('Đã nộp tiền COD về sàn, chờ tác vụ nền chuyển tiền cho cửa hàng');
    } catch (err) {
      showToast(err?.response?.data?.error || err?.response?.data?.message || 'Nộp COD thất bại, thử lại sau', 'error');
    } finally {
      setRemittanceLoading(false);
    }
  }

  return (
    <div className="container page-section carrier-page">
      <div className="section-header">
        <h2>Giả lập vận chuyển</h2>
        <span className="section-link">Giả lập bên vận chuyển thứ ba</span>
      </div>

      <div className="card carrier-card">
        <label>Mã vận đơn</label>
        <input
          value={trackingCode}
          onChange={(event) => setTrackingCode(event.target.value)}
          placeholder="Ví dụ: MOCK-123-ABCDEF"
        />
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => sendCallback('picked_up')}
            disabled={Boolean(loadingStatus)}
          >
            {loadingStatus === 'picked_up' ? 'Đang gửi...' : 'Đã nhận hàng'}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => sendCallback('delivered')}
            disabled={Boolean(loadingStatus)}
          >
            {loadingStatus === 'delivered' ? 'Đang gửi...' : 'Đã giao hàng'}
          </button>
        </div>
      </div>

      {lastResult && (
        <div className="card carrier-card">
          <div className="order-detail-meta">
            <div>
              <span className="muted">Kết quả</span>
              <strong>{lastResult.ok ? 'Tín hiệu đã được chấp nhận' : 'Tín hiệu đã gửi'}</strong>
            </div>
            <div>
              <span className="muted">Mã đơn</span>
              <strong>{order?.id ? `#${order.id}` : '-'}</strong>
            </div>
            <div>
              <span className="muted">Trạng thái đơn</span>
              <strong>{formatOrderStatus(order?.status)}</strong>
            </div>
            <div>
              <span className="muted">Trạng thái vận chuyển</span>
              <strong>{statusText(shipment?.status)}</strong>
            </div>
            <div>
              <span className="muted">Đơn vị vận chuyển</span>
              <strong>{shipment?.carrier || '-'}</strong>
            </div>
            <div>
              <span className="muted">Cập nhật lúc</span>
              <strong>{formatDate(shipment?.updated_at || shipment?.updatedAt)}</strong>
            </div>
            {isCodDelivered && (
              <div>
                <span className="muted">Tiền COD cần nộp</span>
                <strong>{formatPrice(codAmount)}</strong>
              </div>
            )}
          </div>
          {isCodDelivered && order?.settlement_status !== 'settled' && (
            <div className="form-actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={remitCod}
                disabled={remittanceLoading}
              >
                {remittanceLoading ? 'Đang nộp COD...' : 'Nộp tiền COD về sàn'}
              </button>
            </div>
          )}
          {lastResult.codRemittance && (
            <div className="checkout-row">
              <span>Nộp tiền COD</span>
              <strong>{lastResult.codRemittance.ok ? 'Đã chấp nhận' : 'Đã gửi'}</strong>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
