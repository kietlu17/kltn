import { useEffect, useMemo, useState } from 'react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

function formatDate(value) {
  if (!value) return 'Không có';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Không có';
  return date.toLocaleString('vi-VN');
}

export default function Profile() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const [profile, setProfile] = useState(null);
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [wallet, setWallet] = useState(null);
  const [walletTxs, setWalletTxs] = useState([]);
  const [topupAmount, setTopupAmount] = useState('50');
  const [topupLoading, setTopupLoading] = useState(false);
  const [sepayTopupRequest, setSepayTopupRequest] = useState(null);
  const [sepayLoading, setSepayLoading] = useState(false);

  function formatMoney(value) {
    return Number(value || 0).toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
  }

  function loadWallet() {
    if (!user?.id) return;
    api.get(`/payments/wallet/${user.id}`).then((res) => setWallet(res.data)).catch(() => setWallet(null));
    api.get(`/payments/wallet/${user.id}/transactions?limit=8`).then((res) => setWalletTxs(res.data || [])).catch(() => setWalletTxs([]));
  }

  useEffect(() => {
    if (!user?.id) {
      setProfile(null);
      setName('');
      return;
    }

    setLoading(true);
    api
      .get(`/users/${user.id}`)
      .then((res) => {
        setProfile(res.data);
        setName(res.data?.name || '');
      })
      .catch(() => {
        setProfile(null);
        setName('');
      })
      .finally(() => setLoading(false));
  }, [user?.id]);

  useEffect(() => {
    loadWallet();
  }, [user?.id]);

  const initials = useMemo(() => {
    const base = name || user?.email || 'Người dùng';
    return base.slice(0, 2).toUpperCase();
  }, [name, user?.email]);

  async function saveProfile() {
    if (!user?.id) return;
    const trimmed = name.trim();
    if (!trimmed) {
      showToast('Vui lòng nhập tên hiển thị', 'error');
      return;
    }

    try {
      let response;
      try {
        response = await api.put(`/users/${user.id}`, { name: trimmed });
      } catch (err) {
        if (err?.response?.status === 404) {
          response = await api.post('/users', { userId: user.id, name: trimmed });
        } else {
          throw err;
        }
      }
      setProfile(response.data);
      setName(response.data?.name || trimmed);
      showToast('Cập nhật hồ sơ thành công');
      window.dispatchEvent(new Event('buyer-profile-updated'));
    } catch (err) {
      const message = err?.response?.data?.message || 'Không thể cập nhật hồ sơ';
      showToast(message, 'error');
    }
  }

  async function topupWallet() {
    if (!user?.id) return;
    const amount = Number(topupAmount);
    if (!Number.isFinite(amount) || amount <= 0) {
      showToast('Số tiền nạp phải lớn hơn 0', 'error');
      return;
    }
    setTopupLoading(true);
    try {
      await api.post(`/payments/wallet/${user.id}/topup`, { amount, source: 'profile' });
      showToast('Nạp ví thành công');
      loadWallet();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Nạp ví thất bại', 'error');
    } finally {
      setTopupLoading(false);
    }
  }

  async function createSepayTopupQr() {
    if (!user?.id) return;
    const amount = Number(topupAmount);
    if (!Number.isFinite(amount) || amount <= 0) {
      showToast('Số tiền nạp phải lớn hơn 0', 'error');
      return;
    }
    setSepayLoading(true);
    try {
      const res = await api.post(`/payments/wallet/${user.id}/topup/sepay-qr`, { amount });
      setSepayTopupRequest(res.data || null);
      showToast('Đã tạo mã QR SePay');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể tạo mã QR SePay', 'error');
    } finally {
      setSepayLoading(false);
    }
  }

  useEffect(() => {
    const requestId = sepayTopupRequest?.id;
    if (!requestId || sepayTopupRequest?.status === 'paid') return undefined;
    let timer;
    async function check() {
      try {
        const res = await api.get(`/payments/sepay/requests/${requestId}`);
        const next = res.data || null;
        setSepayTopupRequest(next);
        if (next?.status === 'paid') {
          showToast('Nạp ví qua SePay thành công');
          loadWallet();
          return;
        }
      } catch {
        // no-op
      }
      timer = setTimeout(check, 3000);
    }
    check();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [sepayTopupRequest?.id, sepayTopupRequest?.status]);

  return (
    <div className="container page-section">
      <div className="section-header">
        <h2>Hồ sơ người mua</h2>
        <span className="section-link">Quản lý tài khoản</span>
      </div>

      <div className="profile-grid">
        <div className="card profile-card">
          <div className="profile-header">
            <span className="avatar large">{initials}</span>
            <div>
              <h3>{name || user?.email || 'Người mua'}</h3>
              <p className="muted">Thông tin tài khoản người mua</p>
            </div>
          </div>
          <div className="profile-meta">
            <div>
              <span className="muted">Email</span>
              <strong>{user?.email || 'Không có'}</strong>
            </div>
            <div>
              <span className="muted">Ngày tạo</span>
              <strong>{formatDate(profile?.createdAt || profile?.created_at)}</strong>
            </div>
            <div>
              <span className="muted">Cập nhật gần nhất</span>
              <strong>{formatDate(profile?.updatedAt || profile?.updated_at)}</strong>
            </div>
          </div>
        </div>

        <div className="card form-card profile-form">
          <h3>Cập nhật tên hiển thị</h3>
          <p className="muted">Tên này sẽ hiển thị trên đơn hàng và đánh giá của bạn.</p>
          <label>Tên hiển thị</label>
          <input
            placeholder="Nhập tên hiển thị"
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={loading}
          />
          <div className="form-actions">
            <button className="btn btn-primary" onClick={saveProfile} disabled={loading}>
              Lưu thay đổi
            </button>
            <button className="btn btn-ghost" onClick={() => setName(profile?.name || '')} disabled={loading}>
              Đặt lại
            </button>
          </div>
        </div>

        <div className="card form-card profile-form">
          <h3>Ví</h3>
          <p className="muted">Dùng ví để thanh toán và nhận hoàn tiền cho các đơn đủ điều kiện.</p>
          <div>
            <span className="muted">Số dư hiện tại</span>
            <h2>{formatMoney(wallet?.balance || 0)}</h2>
          </div>
          <div className="form-actions">
            <input
              type="number"
              min="1"
              step="1"
              value={topupAmount}
              onChange={(event) => setTopupAmount(event.target.value)}
              placeholder="Số tiền nạp"
            />
            <button className="btn btn-primary" onClick={topupWallet} disabled={topupLoading}>
              {topupLoading ? 'Đang xử lý...' : 'Nạp tiền'}
            </button>
            <button className="btn btn-outline" onClick={createSepayTopupQr} disabled={sepayLoading}>
              {sepayLoading ? 'Đang tạo QR...' : 'Nạp qua SePay QR'}
            </button>
          </div>

          {sepayTopupRequest && (
            <div className="sepay-qr-box">
              <div className="sepay-qr-head">
                <strong>Nạp ví qua SePay</strong>
                <span className={`sepay-status ${sepayTopupRequest.status || 'pending'}`}>
                  {sepayTopupRequest.status === 'paid' ? 'Đã thanh toán' : 'Chờ thanh toán'}
                </span>
              </div>
              <div className="sepay-qr-grid">
                <img src={sepayTopupRequest.qrUrl} alt="SePay QR nạp ví" />
                <div className="sepay-qr-meta">
                  <div><span className="muted">Số tiền</span><strong>{formatMoney(sepayTopupRequest.amount)}</strong></div>
                  <div><span className="muted">Ngân hàng</span><strong>{sepayTopupRequest.bankCode}</strong></div>
                  <div><span className="muted">Tài khoản</span><strong>{sepayTopupRequest.accountNumber}</strong></div>
                  <div><span className="muted">Nội dung</span><strong>{sepayTopupRequest.requestCode}</strong></div>
                </div>
              </div>
            </div>
          )}

          <div>
            <label>Giao dịch gần đây</label>
            {walletTxs.length === 0 ? (
              <div className="muted">Chưa có giao dịch.</div>
            ) : (
              walletTxs.map((tx) => (
                <div key={tx.id} className="checkout-row">
                  <span>{tx.type} ({tx.status})</span>
                  <strong>{formatMoney(tx.amount)}</strong>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
