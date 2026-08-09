import { useEffect, useMemo, useState } from 'react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import { formatVoucherStatus } from '../utils/statusLabels';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

function toDateInput(value) {
  if (!value) return '';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  const offsetDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return offsetDate.toISOString().slice(0, 16);
}

function getInitialForm(role, shopId) {
  const now = new Date();
  const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  return {
    code: '',
    name: '',
    type: role === 'admin' ? 'platform' : 'shop',
    shopId: role === 'seller' ? shopId || '' : '',
    discountValue: 10,
    maxDiscountAmount: '',
    minOrderAmount: 0,
    quantity: 100,
    usageLimitPerUser: 1,
    startAt: toDateInput(now),
    endAt: toDateInput(tomorrow),
    status: 'active'
  };
}

export default function VoucherManager({ title = 'Quản lý mã giảm giá' }) {
  const { user } = useAuth();
  const { showToast } = useToast();
  const role = user?.role || '';
  const shopId = user?.shopId || user?.id || '';
  const [vouchers, setVouchers] = useState([]);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(() => getInitialForm(role, shopId));

  const isSeller = role === 'seller';
  const rows = useMemo(
    () => vouchers.map((voucher) => ({
      ...voucher,
      remaining: Math.max(Number(voucher.quantity || 0) - Number(voucher.used_count || 0), 0)
    })),
    [vouchers]
  );

  function loadVouchers() {
    api.get('/vouchers').then((res) => setVouchers(res.data || [])).catch(() => setVouchers([]));
  }

  useEffect(() => {
    setForm(getInitialForm(role, shopId));
    loadVouchers();
  }, [role, shopId]);

  function updateField(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function resetForm() {
    setEditingId(null);
    setForm(getInitialForm(role, shopId));
  }

  function editVoucher(voucher) {
    setEditingId(voucher.id);
    setForm({
      code: voucher.code || '',
      name: voucher.name || '',
      type: voucher.type || 'shop',
      shopId: voucher.shop_id || voucher.shopId || '',
      discountValue: Number(voucher.discount_value ?? voucher.discountValue ?? 0),
      maxDiscountAmount: voucher.max_discount_amount ?? voucher.maxDiscountAmount ?? '',
      minOrderAmount: Number(voucher.min_order_amount ?? voucher.minOrderAmount ?? 0),
      quantity: Number(voucher.quantity || 0),
      usageLimitPerUser: Number(voucher.usage_limit_per_user ?? voucher.usageLimitPerUser ?? 1),
      startAt: toDateInput(voucher.start_at || voucher.startAt),
      endAt: toDateInput(voucher.end_at || voucher.endAt),
      status: voucher.status || 'active'
    });
  }

  async function submitVoucher(event) {
    event.preventDefault();
    const payload = {
      ...form,
      type: isSeller ? 'shop' : form.type,
      shopId: isSeller ? shopId : form.shopId,
      discountType: 'percent',
      discountValue: Number(form.discountValue),
      maxDiscountAmount: form.maxDiscountAmount === '' ? null : Number(form.maxDiscountAmount),
      minOrderAmount: Number(form.minOrderAmount),
      quantity: Number(form.quantity),
      usageLimitPerUser: Number(form.usageLimitPerUser),
      startAt: form.startAt,
      endAt: form.endAt
    };
    try {
      if (editingId) {
        await api.put(`/vouchers/${editingId}`, payload);
        showToast('Đã cập nhật mã giảm giá');
      } else {
        await api.post('/vouchers', payload);
        showToast('Đã tạo mã giảm giá');
      }
      resetForm();
      loadVouchers();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Lưu mã giảm giá thất bại', 'error');
    }
  }

  async function toggleVoucher(voucher) {
    try {
      await api.put(`/vouchers/${voucher.id}`, {
        ...voucher,
        status: voucher.status === 'active' ? 'inactive' : 'active'
      });
      showToast(`Đã ${voucher.status === 'active' ? 'tắt' : 'bật'} mã giảm giá`);
      loadVouchers();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Cập nhật mã thất bại', 'error');
    }
  }

  return (
    <div className="container page-section">
      <div className="section-header">
        <h2>{title}</h2>
        <span className="section-link">{rows.length} mã</span>
      </div>

      <form className="card voucher-form" onSubmit={submitVoucher}>
        <div className="form-grid">
          <label>
            Mã
            <input value={form.code} onChange={(event) => updateField('code', event.target.value)} required />
          </label>
          <label>
            Tên
            <input value={form.name} onChange={(event) => updateField('name', event.target.value)} required />
          </label>
          {!isSeller && (
            <label>
              Loại
              <select value={form.type} onChange={(event) => updateField('type', event.target.value)}>
                <option value="platform">Mã của sàn</option>
                <option value="shop">Mã của shop</option>
              </select>
            </label>
          )}
          {(!isSeller && form.type === 'shop') && (
            <label>
              Shop ID
              <input value={form.shopId} onChange={(event) => updateField('shopId', event.target.value)} required />
            </label>
          )}
          <label>
            % giảm
            <input type="number" min="1" max="100" value={form.discountValue} onChange={(event) => updateField('discountValue', event.target.value)} required />
          </label>
          <label>
            Giảm tối đa
            <input type="number" min="0" value={form.maxDiscountAmount} onChange={(event) => updateField('maxDiscountAmount', event.target.value)} />
          </label>
          <label>
            Đơn tối thiểu
            <input type="number" min="0" value={form.minOrderAmount} onChange={(event) => updateField('minOrderAmount', event.target.value)} />
          </label>
          <label>
            Số lượng
            <input type="number" min="1" value={form.quantity} onChange={(event) => updateField('quantity', event.target.value)} required />
          </label>
          <label>
            Mỗi user
            <input type="number" min="1" value={form.usageLimitPerUser} onChange={(event) => updateField('usageLimitPerUser', event.target.value)} required />
          </label>
          <label>
            Bắt đầu
            <input type="datetime-local" value={form.startAt} onChange={(event) => updateField('startAt', event.target.value)} required />
          </label>
          <label>
            Kết thúc
            <input type="datetime-local" value={form.endAt} onChange={(event) => updateField('endAt', event.target.value)} required />
          </label>
          <label>
            Trạng thái
            <select value={form.status} onChange={(event) => updateField('status', event.target.value)}>
              <option value="active">{formatVoucherStatus('active')}</option>
              <option value="inactive">{formatVoucherStatus('inactive')}</option>
            </select>
          </label>
        </div>
        <div className="form-actions">
          <button className="btn btn-primary" type="submit">{editingId ? 'Lưu mã' : 'Tạo mã'}</button>
          {editingId && <button className="btn btn-outline" type="button" onClick={resetForm}>Hủy sửa</button>}
        </div>
      </form>

      <div className="seller-table voucher-table">
        <div className="seller-table-row seller-table-head">
          <div>Mã</div>
          <div>Loại</div>
          <div>Giảm</div>
          <div>Điều kiện</div>
          <div>Còn lại</div>
          <div>Thời hạn</div>
          <div>Trạng thái</div>
          <div>Thao tác</div>
        </div>
        {rows.map((voucher) => (
          <div key={voucher.id} className="seller-table-row">
            <div>
              <strong>{voucher.code}</strong>
              <span className="muted">{voucher.name}</span>
            </div>
            <div>{voucher.type === 'shop' ? 'Shop' : 'Sàn'}</div>
            <div>
              {Number(voucher.discount_value || 0)}%
              {Number(voucher.max_discount_amount || 0) > 0 ? ` tối đa ${formatPrice(voucher.max_discount_amount)}` : ''}
            </div>
            <div>Từ {formatPrice(voucher.min_order_amount)}</div>
            <div>{voucher.remaining}/{voucher.quantity}</div>
            <div>{new Date(voucher.start_at).toLocaleDateString('vi-VN')} - {new Date(voucher.end_at).toLocaleDateString('vi-VN')}</div>
            <div>{formatVoucherStatus(voucher.status)}</div>
            <div className="admin-actions">
              <button type="button" className="btn btn-outline" onClick={() => editVoucher(voucher)}>Sửa</button>
              <button type="button" className="btn btn-ghost" onClick={() => toggleVoucher(voucher)}>
                {voucher.status === 'active' ? 'Tắt' : 'Bật'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
