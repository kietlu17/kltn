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
    requested: 'Da nhan yeu cau',
    handed_over: 'Shop da ban giao',
    picked_up: 'Carrier da nhan hang',
    in_transit: 'Dang van chuyen',
    delivered: 'Da giao',
    failed: 'Giao that bai'
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
      showToast(status === 'delivered' ? 'Da gui callback giao thanh cong' : 'Da gui callback carrier nhan hang');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Gui callback that bai', 'error');
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
      showToast('Khong du thong tin nop COD', 'error');
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
      showToast('Da nop tien COD ve san, cho worker chuyen tien shop');
    } catch (err) {
      showToast(err?.response?.data?.error || err?.response?.data?.message || 'Nop COD that bai, thu lai sau', 'error');
    } finally {
      setRemittanceLoading(false);
    }
  }

  return (
    <div className="container page-section carrier-page">
      <div className="section-header">
        <h2>Mock Carrier</h2>
        <span className="section-link">Gia lap ben van chuyen thu 3</span>
      </div>

      <div className="card carrier-card">
        <label>Ma van don</label>
        <input
          value={trackingCode}
          onChange={(event) => setTrackingCode(event.target.value)}
          placeholder="Vi du: MOCK-123-ABCDEF"
        />
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => sendCallback('picked_up')}
            disabled={Boolean(loadingStatus)}
          >
            {loadingStatus === 'picked_up' ? 'Dang gui...' : 'Da nhan hang'}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => sendCallback('delivered')}
            disabled={Boolean(loadingStatus)}
          >
            {loadingStatus === 'delivered' ? 'Dang gui...' : 'Da giao hang'}
          </button>
        </div>
      </div>

      {lastResult && (
        <div className="card carrier-card">
          <div className="order-detail-meta">
            <div>
              <span className="muted">Ket qua</span>
              <strong>{lastResult.ok ? 'Callback accepted' : 'Callback sent'}</strong>
            </div>
            <div>
              <span className="muted">Ma don</span>
              <strong>{order?.id ? `#${order.id}` : '-'}</strong>
            </div>
            <div>
              <span className="muted">Trang thai don</span>
              <strong>{formatOrderStatus(order?.status)}</strong>
            </div>
            <div>
              <span className="muted">Trang thai van chuyen</span>
              <strong>{statusText(shipment?.status)}</strong>
            </div>
            <div>
              <span className="muted">Carrier</span>
              <strong>{shipment?.carrier || '-'}</strong>
            </div>
            <div>
              <span className="muted">Cap nhat luc</span>
              <strong>{formatDate(shipment?.updated_at || shipment?.updatedAt)}</strong>
            </div>
            {isCodDelivered && (
              <div>
                <span className="muted">Tien COD can nop</span>
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
                {remittanceLoading ? 'Dang nop COD...' : 'Nop tien COD ve san'}
              </button>
            </div>
          )}
          {lastResult.codRemittance && (
            <div className="checkout-row">
              <span>COD remittance</span>
              <strong>{lastResult.codRemittance.ok ? 'Accepted' : 'Sent'}</strong>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
