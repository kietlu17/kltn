import { useEffect, useState } from 'react';
import api from '../services/api';
import { useToast } from '../context/ToastContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';

export default function SellerCategories() {
  const { showToast } = useToast();
  const { user } = useAuth();
  const [categories, setCategories] = useState([]);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState({ name: '', description: '' });

  const loadCategories = () => {
    const shopKey = user?.shopId || user?.id;
    if (!shopKey) {
      setCategories([]);
      return;
    }
    const url = `/categories?shopId=${encodeURIComponent(shopKey)}`;
    api.get(url).then((res) => setCategories(res.data)).catch(() => setCategories([]));
  };

  useEffect(() => {
    loadCategories();
  }, [user]);

  const resetForm = () => {
    setForm({ name: '', description: '' });
    setEditingId(null);
  };

  const submit = async () => {
    if (!form.name.trim()) {
      showToast('Tên danh mục là bắt buộc', 'error');
      return;
    }

    const shopKey = user?.shopId || user?.id;
    if (!shopKey) {
      showToast('Cần có thông tin shop trước khi quản lý danh mục', 'error');
      return;
    }

    if (editingId) {
      await api.put(`/categories/${editingId}`, { ...form, shopId: shopKey });
      showToast('Đã cập nhật danh mục');
    } else {
      await api.post('/categories', { ...form, shopId: shopKey });
      showToast('Đã tạo danh mục');
    }

    resetForm();
    loadCategories();
  };

  const editCategory = (category) => {
    setEditingId(category._id || category.id);
    setForm({ name: category.name || '', description: category.description || '' });
  };

  const deleteCategory = async (id) => {
    const shopKey = user?.shopId || user?.id;
    if (!shopKey) {
      showToast('Cần có thông tin shop trước khi xóa danh mục', 'error');
      return;
    }
    const url = `/categories/${id}?shopId=${encodeURIComponent(shopKey)}`;
    await api.delete(url);
    showToast('Đã xóa danh mục');
    loadCategories();
  };

  return (
    <div className="container page-section">
      <div className="section-header">
        <h2>Danh mục sản phẩm</h2>
        <span className="section-link">{categories.length} danh mục</span>
      </div>

      <div className="card form-card">
        <div className="form-grid">
          <div>
            <label>Tên danh mục</label>
            <input
              placeholder="Tên danh mục"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </div>
          <div>
            <label>Mô tả</label>
            <input
              placeholder="Mô tả ngắn"
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
            />
          </div>
        </div>

        <div className="form-actions">
          <button className="btn btn-primary" onClick={submit}>
            {editingId ? 'Cập nhật danh mục' : 'Tạo danh mục'}
          </button>
          {editingId && <button className="btn btn-ghost" onClick={resetForm}>Hủy</button>}
        </div>
      </div>

      <div className="seller-table">
        <div className="seller-table-row seller-table-head seller-category-row">
          <div>Tên</div>
          <div>Mô tả</div>
          <div>Sửa</div>
          <div>Xóa</div>
        </div>
        {categories.map((category) => (
          <div key={category._id || category.id} className="seller-table-row seller-category-row">
            <div>{category.name}</div>
            <div className="muted">{category.description || '-'}</div>
            <div>
              <button className="btn btn-outline" onClick={() => editCategory(category)}>Sửa</button>
            </div>
            <div>
              <button className="btn btn-ghost" onClick={() => deleteCategory(category._id || category.id)}>Xóa</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
