import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

export default function CreateProduct() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [price, setPrice] = useState('');
  const [description, setDescription] = useState('');
  const [detail, setDetail] = useState('');
  const [images, setImages] = useState(null);
  const [categories, setCategories] = useState([]);
  const [categoryId, setCategoryId] = useState('');
  const [quantity, setQuantity] = useState('');
  const [variants, setVariants] = useState([]);
  const [variantImageFiles, setVariantImageFiles] = useState([]);

  useEffect(() => {
    const shopKey = user?.shopId || user?.id;
    if (!shopKey) {
      setCategories([]);
      return;
    }
    const url = `/categories?shopId=${encodeURIComponent(shopKey)}`;
    api.get(url).then((res) => setCategories(res.data)).catch(() => setCategories([]));
  }, [user]);

  async function submit() {
    const shopKey = user?.shopId || user?.id;
    if (!shopKey) {
      showToast('Cần có thông tin shop trước khi tạo sản phẩm', 'error');
      return;
    }

    const form = new FormData();
    form.append('name', name);
    form.append('price', price);
    form.append('quantity', quantity || 0);
    form.append('description', description);
    form.append('detail', detail);
    if (categoryId) {
      form.append('categoryId', categoryId);
    }
    if (variants.length > 0) {
      form.append('variants', JSON.stringify(variants));
    }
    form.append('shopId', shopKey);

    if (images) {
      for (const file of images) {
        form.append('images', file);
      }
    }

    variantImageFiles.forEach((file, index) => {
      if (file) {
        form.append(`variantImage_${index}`, file);
      }
    });

    const response = await api.post('/products', form, { headers: { 'Content-Type': 'multipart/form-data' } });
    try {
      await api.post('/inventory/sync-product', response.data);
    } catch {
      // Kafka product.created will also seed inventory; this keeps create flow responsive when available.
    }
    showToast('Đã tạo sản phẩm');
    navigate('/seller/products');
  }

  return (
    <div className="container page-section">
      <div className="section-header">
        <h2>Tạo sản phẩm</h2>
        <span className="section-link">Thêm sản phẩm mới</span>
      </div>
      <div className="card form-card">
        <div className="form-grid">
          <div>
            <label>Tên sản phẩm</label>
            <input placeholder="Tên sản phẩm" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label>Giá</label>
            <input placeholder="Giá" type="number" value={price} onChange={(e) => setPrice(e.target.value)} />
          </div>
          <div>
            <label>Số lượng</label>
            <input
              placeholder="Số lượng tồn"
              type="number"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </div>
          <div>
            <label>Danh mục</label>
            <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
              <option value="">Chọn danh mục</option>
              {categories.map((category) => (
                <option key={category._id || category.id} value={category._id || category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label>Hình ảnh</label>
            <input type="file" multiple onChange={(e) => setImages(e.target.files)} />
          </div>
        </div>

        <div className="product-section">
          <h4>Biến thể (tùy chọn)</h4>
          <p className="muted">Nếu có biến thể, giá và tồn kho sẽ lấy theo từng biến thể.</p>
          {variants.map((variant, index) => (
            <div key={`variant-${index}`} className="form-grid">
              <input
                placeholder="Tên biến thể (VD: Size M / Đỏ)"
                value={variant.name}
                onChange={(e) => {
                  const next = [...variants];
                  next[index] = { ...next[index], name: e.target.value };
                  setVariants(next);
                }}
              />
              <input
                placeholder="SKU"
                value={variant.sku || ''}
                onChange={(e) => {
                  const next = [...variants];
                  next[index] = { ...next[index], sku: e.target.value };
                  setVariants(next);
                }}
              />
              <input
                placeholder="Giá"
                type="number"
                value={variant.price}
                onChange={(e) => {
                  const next = [...variants];
                  next[index] = { ...next[index], price: e.target.value };
                  setVariants(next);
                }}
              />
              <input
                placeholder="Tồn kho"
                type="number"
                value={variant.quantity}
                onChange={(e) => {
                  const next = [...variants];
                  next[index] = { ...next[index], quantity: e.target.value };
                  setVariants(next);
                }}
              />
              <div>
                <label>Ảnh biến thể</label>
                <input
                  type="file"
                  accept="image/*"
                  onChange={(e) => {
                    const file = e.target.files?.[0] || null;
                    setVariantImageFiles((prev) => {
                      const next = [...prev];
                      next[index] = file;
                      return next;
                    });
                  }}
                />
              </div>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setVariants((prev) => prev.filter((_, idx) => idx !== index));
                  setVariantImageFiles((prev) => prev.filter((_, idx) => idx !== index));
                }}
              >
                Xóa biến thể
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => {
              setVariants((prev) => [...prev, { name: '', sku: '', imageUrl: '', price: '', quantity: '' }]);
              setVariantImageFiles((prev) => [...prev, null]);
            }}
          >
            Thêm biến thể
          </button>
        </div>

        <label>Mô tả</label>
        <textarea placeholder="Mô tả" value={description} onChange={(e) => setDescription(e.target.value)} />
        <label>Chi tiết</label>
        <textarea placeholder="Chi tiết" value={detail} onChange={(e) => setDetail(e.target.value)} />
        <button className="btn btn-primary" onClick={submit}>Tạo sản phẩm</button>
      </div>
    </div>
  );
}
