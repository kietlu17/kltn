import { useEffect, useState } from 'react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

const emptyForm = {
  label: '',
  fullName: '',
  phone: '',
  line1: '',
  line2: '',
  city: '',
  state: '',
  postalCode: '',
  country: '',
  isDefault: false
};

export default function Addresses() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const [addresses, setAddresses] = useState([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);

  const loadAddresses = () => {
    if (!user?.id) {
      setAddresses([]);
      return;
    }

    api
      .get(`/users/${user.id}/addresses`)
      .then((res) => setAddresses(res.data))
      .catch(() => setAddresses([]));
  };

  useEffect(() => {
    loadAddresses();
  }, [user]);

  const reset = () => {
    setForm(emptyForm);
    setEditingId(null);
  };

  const submit = async () => {
    if (!user?.id) return;

    if (!form.line1.trim()) {
      showToast('Vui lòng nhập địa chỉ dòng 1', 'error');
      return;
    }

    try {
      if (editingId) {
        await api.put(`/users/${user.id}/addresses/${editingId}`, form);
        showToast('Cập nhật địa chỉ thành công');
      } else {
        await api.post(`/users/${user.id}/addresses`, form);
        showToast('Thêm địa chỉ thành công');
      }
      reset();
      loadAddresses();
    } catch (err) {
      const message = err?.response?.data?.message || 'Cập nhật địa chỉ thất bại';
      showToast(message, 'error');
    }
  };

  const edit = (address) => {
    setEditingId(address._id || address.id);
    setForm({
      label: address.label || '',
      fullName: address.fullName || '',
      phone: address.phone || '',
      line1: address.line1 || '',
      line2: address.line2 || '',
      city: address.city || '',
      state: address.state || '',
      postalCode: address.postalCode || '',
      country: address.country || '',
      isDefault: address.isDefault || false
    });
  };

  const remove = async (id) => {
    if (!user?.id) return;
    try {
      await api.delete(`/users/${user.id}/addresses/${id}`);
      showToast('Xóa địa chỉ thành công');
      loadAddresses();
    } catch (err) {
      const message = err?.response?.data?.message || 'Xóa địa chỉ thất bại';
      showToast(message, 'error');
    }
  };

  const setDefault = async (id) => {
    if (!user?.id) return;
    try {
      await api.put(`/users/${user.id}/addresses/${id}/default`);
      showToast('Đã cập nhật địa chỉ mặc định');
      loadAddresses();
    } catch (err) {
      const message = err?.response?.data?.message || 'Đặt địa chỉ mặc định thất bại';
      showToast(message, 'error');
    }
  };

  return (
    <div className="container page-section">
      <div className="section-header">
        <h2>Địa chỉ giao hàng</h2>
        <span className="section-link">{addresses.length} địa chỉ đã lưu</span>
      </div>

      <div className="card form-card">
        <div className="form-grid">
          <div>
            <label>Nhãn</label>
            <input
              placeholder="Nhà, công ty, ..."
              value={form.label}
              onChange={(event) => setForm({ ...form, label: event.target.value })}
            />
          </div>
          <div>
            <label>Họ và tên</label>
            <input
              placeholder="Tên người nhận"
              value={form.fullName}
              onChange={(event) => setForm({ ...form, fullName: event.target.value })}
            />
          </div>
          <div>
            <label>Số điện thoại</label>
            <input
              placeholder="Số liên hệ"
              value={form.phone}
              onChange={(event) => setForm({ ...form, phone: event.target.value })}
            />
          </div>
          <div>
            <label>Quốc gia</label>
            <input
              placeholder="Quốc gia"
              value={form.country}
              onChange={(event) => setForm({ ...form, country: event.target.value })}
            />
          </div>
        </div>

        <label>Địa chỉ dòng 1</label>
        <input
          placeholder="Địa chỉ đường/phố"
          value={form.line1}
          onChange={(event) => setForm({ ...form, line1: event.target.value })}
        />

        <label>Địa chỉ dòng 2</label>
        <input
          placeholder="Căn hộ, tòa nhà, ..."
          value={form.line2}
          onChange={(event) => setForm({ ...form, line2: event.target.value })}
        />

        <div className="form-grid">
          <div>
            <label>Thành phố</label>
            <input
              placeholder="Thành phố"
              value={form.city}
              onChange={(event) => setForm({ ...form, city: event.target.value })}
            />
          </div>
          <div>
            <label>Tỉnh/Bang</label>
            <input
              placeholder="Tỉnh/Bang"
              value={form.state}
              onChange={(event) => setForm({ ...form, state: event.target.value })}
            />
          </div>
          <div>
            <label>Mã bưu chính</label>
            <input
              placeholder="Mã bưu chính"
              value={form.postalCode}
              onChange={(event) => setForm({ ...form, postalCode: event.target.value })}
            />
          </div>
        </div>

        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={form.isDefault}
            onChange={(event) => setForm({ ...form, isDefault: event.target.checked })}
          />
          Đặt làm địa chỉ mặc định
        </label>

        <div className="form-actions">
          <button className="btn btn-primary" onClick={submit}>
            {editingId ? 'Cập nhật địa chỉ' : 'Thêm địa chỉ'}
          </button>
          {editingId && (
            <button className="btn btn-ghost" onClick={reset}>Hủy</button>
          )}
        </div>
      </div>

      <div className="seller-table">
        <div className="seller-table-row seller-table-head address-row">
          <div>Nhãn</div>
          <div>Địa chỉ</div>
          <div>Mặc định</div>
          <div>Sửa</div>
          <div>Xóa</div>
        </div>

        {addresses.map((address) => (
          <div key={address._id || address.id} className="seller-table-row address-row">
            <div>{address.label || 'Địa chỉ'}</div>
            <div className="muted">
              {[address.line1, address.line2, address.city, address.state, address.postalCode, address.country]
                .filter(Boolean)
                .join(', ')}
            </div>
            <div>{address.isDefault ? 'Có' : 'Không'}</div>
            <div>
              <button className="btn btn-outline" onClick={() => edit(address)}>Sửa</button>
              {!address.isDefault && (
                <button className="btn btn-ghost" onClick={() => setDefault(address._id || address.id)}>
                  Đặt mặc định
                </button>
              )}
            </div>
            <div>
              <button className="btn btn-ghost" onClick={() => remove(address._id || address.id)}>
                Xóa
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
