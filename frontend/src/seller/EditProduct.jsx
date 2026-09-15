import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import api, { resolveImageUrl } from '../services/api';
import { useToast } from '../context/ToastContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';

export default function EditProduct() {
  const { id } = useParams();
  const { showToast } = useToast();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [categories, setCategories] = useState([]);
  const [newImages, setNewImages] = useState(null);
  const [variantImageFiles, setVariantImageFiles] = useState([]);
  const [form, setForm] = useState({
    name: '',
    originalPrice: '',
    price: '',
    description: '',
    detail: '',
    categoryId: '',
    quantity: '',
    images: [],
    variants: []
  });

  useEffect(() => {
    const shopKey = user?.shopId || user?.id;
    if (!shopKey) {
      setCategories([]);
      return;
    }
    const url = `/categories?shopId=${encodeURIComponent(shopKey)}`;
    api.get(url).then((res) => setCategories(res.data)).catch(() => setCategories([]));
  }, [user]);

  useEffect(() => {
    api.get(`/products/${id}`).then((res) => {
      const product = res.data;
      setForm({
        name: product.name || '',
        originalPrice: product.originalPrice ?? product.price ?? '',
        price: product.price || '',
        description: product.description || '',
        detail: product.detail || '',
        categoryId: product.categoryId || '',
        quantity: product.quantity ?? '',
        images: product.images || [],
        variants: Array.isArray(product.variants)
          ? product.variants.map((variant) => ({
            _id: variant._id,
            name: variant.name || '',
            sku: variant.sku || '',
            imageUrl: variant.imageUrl || '',
            originalPrice: variant.originalPrice ?? variant.price ?? '',
            price: variant.price ?? '',
            quantity: variant.quantity ?? ''
          }))
          : []
      });
      setVariantImageFiles(Array.isArray(product.variants) ? product.variants.map(() => null) : []);
    });
  }, [id]);

  const removeImage = (src) => {
    setForm((prev) => ({ ...prev, images: prev.images.filter((image) => image !== src) }));
  };

  const update = async () => {
    const shopKey = user?.shopId || user?.id;
    if (!shopKey) {
      showToast('Cần có thông tin shop trước khi cập nhật sản phẩm', 'error');
      return;
    }

    const payload = new FormData();
    payload.append('name', form.name);
    payload.append('originalPrice', form.originalPrice);
    payload.append('price', form.price);
    payload.append('quantity', form.quantity || 0);
    payload.append('description', form.description);
    payload.append('detail', form.detail);
    payload.append('categoryId', form.categoryId);
    payload.append('shopId', shopKey);
    payload.append('existingImages', JSON.stringify(form.images || []));

    if (Array.isArray(form.variants) && form.variants.length > 0) {
      payload.append('variants', JSON.stringify(form.variants));
    }

    if (newImages) {
      for (const file of newImages) payload.append('images', file);
    }

    variantImageFiles.forEach((file, index) => {
      if (file) {
        payload.append(`variantImage_${index}`, file);
      }
    });

    const response = await api.put(`/products/${id}`, payload, { headers: { 'Content-Type': 'multipart/form-data' } });
    const saved = response.data || {};
    const savedVariants = Array.isArray(saved.variants) ? saved.variants : [];
    if (savedVariants.length > 0) {
      await Promise.all(
        savedVariants.map((variant) =>
          api.patch(`/inventory/products/${saved._id || saved.id}/variants/${variant._id}`, {
            shopId: shopKey,
            sku: variant.sku || '',
            stockOnHand: variant.quantity ?? 0
          })
        )
      );
    } else {
      await api.patch(`/inventory/products/${saved._id || saved.id}`, {
        shopId: shopKey,
        stockOnHand: saved.quantity ?? form.quantity ?? 0
      });
    }
    showToast('Đã cập nhật sản phẩm');
    navigate('/seller/products');
  };

  return (
    <div className="container page-section">
      <div className="section-header">
        <h2>Sửa sản phẩm</h2>
        <span className="section-link">Cập nhật thông tin sản phẩm</span>
      </div>

      <div className="card form-card">
        <div className="form-grid">
          <div>
            <label>Tên sản phẩm</label>
            <input placeholder="Tên sản phẩm" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div>
            <label>Giá gốc</label>
            <input
              placeholder="Giá gốc"
              type="number"
              value={form.originalPrice}
              onChange={(e) => setForm({ ...form, originalPrice: e.target.value })}
            />
          </div>
          <div>
            <label>Giá giảm</label>
            <input placeholder="Giá giảm" type="number" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} />
          </div>
          <div>
            <label>Số lượng</label>
            <input placeholder="Số lượng tồn" type="number" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
          </div>
          <div>
            <label>Danh mục</label>
            <select value={form.categoryId} onChange={(e) => setForm({ ...form, categoryId: e.target.value })}>
              <option value="">Chọn danh mục</option>
              {categories.map((category) => (
                <option key={category._id || category.id} value={category._id || category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label>Thêm hình mới</label>
            <input type="file" multiple onChange={(e) => setNewImages(e.target.files)} />
          </div>
        </div>

        <div className="product-section">
          <h4>Biến thể (tùy chọn)</h4>
          {form.variants?.map((variant, index) => (
            <div key={`variant-${variant._id || index}`} className="form-grid">
              <input
                placeholder="Tên biến thể"
                value={variant.name}
                onChange={(e) => {
                  const next = [...(form.variants || [])];
                  next[index] = { ...next[index], name: e.target.value };
                  setForm({ ...form, variants: next });
                }}
              />
              <input
                placeholder="SKU"
                value={variant.sku || ''}
                onChange={(e) => {
                  const next = [...(form.variants || [])];
                  next[index] = { ...next[index], sku: e.target.value };
                  setForm({ ...form, variants: next });
                }}
              />
              <input
                placeholder="Giá gốc"
                type="number"
                value={variant.originalPrice || ''}
                onChange={(e) => {
                  const next = [...(form.variants || [])];
                  next[index] = { ...next[index], originalPrice: e.target.value };
                  setForm({ ...form, variants: next });
                }}
              />
              <input
                placeholder="Giá giảm"
                type="number"
                value={variant.price}
                onChange={(e) => {
                  const next = [...(form.variants || [])];
                  next[index] = { ...next[index], price: e.target.value };
                  setForm({ ...form, variants: next });
                }}
              />
              <input
                placeholder="Tồn kho"
                type="number"
                value={variant.quantity}
                onChange={(e) => {
                  const next = [...(form.variants || [])];
                  next[index] = { ...next[index], quantity: e.target.value };
                  setForm({ ...form, variants: next });
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
                {variant.imageUrl && (
                  <div className="image-chip">
                    <img src={resolveImageUrl(variant.imageUrl)} alt={variant.name || 'Biến thể'} />
                    <button
                      type="button"
                      onClick={() => {
                        const next = [...(form.variants || [])];
                        next[index] = { ...next[index], imageUrl: '' };
                        setForm({ ...form, variants: next });
                      }}
                    >
                      Xóa
                    </button>
                  </div>
                )}
              </div>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  const next = (form.variants || []).filter((_, idx) => idx !== index);
                  setForm({ ...form, variants: next });
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
              setForm({
                ...form,
                variants: [
                  ...(form.variants || []),
                  { name: '', sku: '', imageUrl: '', originalPrice: '', price: '', quantity: '' }
                ]
              });
              setVariantImageFiles((prev) => [...prev, null]);
            }}
          >
            Thêm biến thể
          </button>
        </div>

        {form.images?.length > 0 && (
          <div className="image-list">
            {form.images.map((src) => (
              <div key={src} className="image-chip">
                <img src={resolveImageUrl(src)} alt="Sản phẩm hiện có" />
                <button type="button" onClick={() => removeImage(src)}>Xóa</button>
              </div>
            ))}
          </div>
        )}

        <label>Mô tả</label>
        <textarea placeholder="Mô tả" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        <label>Chi tiết</label>
        <textarea placeholder="Chi tiết" value={form.detail} onChange={(e) => setForm({ ...form, detail: e.target.value })} />
        <button className="btn btn-primary" onClick={update}>Lưu thay đổi</button>
      </div>
    </div>
  );
}
