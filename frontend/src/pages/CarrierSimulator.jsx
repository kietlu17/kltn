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
          </div>
        </div>
      )}
    </div>
  );
}
