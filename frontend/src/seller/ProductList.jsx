import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { resolveImageUrl } from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

export default function SellerProductList() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);

  const loadProducts = () => {
    const shopKey = user?.shopId || user?.id;
    if (!shopKey) {
      setProducts([]);
      return;
    }
    const url = `/products?shopId=${encodeURIComponent(shopKey)}`;
    api.get(url).then((res) => setProducts(res.data)).catch(() => setProducts([]));
  };

  useEffect(() => {
    loadProducts();
  }, [user]);

  useEffect(() => {
    api.get('/categories').then((res) => setCategories(res.data)).catch(() => setCategories([]));
  }, []);

  const categoryMap = useMemo(() => {
    const map = new Map();
    categories.forEach((category) => map.set(category._id || category.id, category));
    return map;
  }, [categories]);

  const shopProducts = useMemo(() => {
    if (!products.length) return [];
    const shopKey = user?.shopId || user?.id;
    if (shopKey) {
      return products.filter((p) => p.shopId === shopKey);
    }
    return products;
  }, [products, user]);

  const handleDelete = async (id) => {
    const shopKey = user?.shopId || user?.id;
    if (!shopKey) {
      showToast('Cần có thông tin shop trước khi xóa sản phẩm', 'error');
      return;
    }
    const url = `/products/${id}?shopId=${encodeURIComponent(shopKey)}`;
    await api.delete(url);
    showToast('Đã xóa sản phẩm');
    loadProducts();
  };

  return (
    <div className="container page-section">
      <div className="section-header">
        <h2>Sản phẩm của bạn</h2>
        <Link to="/seller/products/create" className="btn btn-primary">Tạo sản phẩm</Link>
      </div>
      <div className="seller-table">
        <div className="seller-table-row seller-table-head">
          <div>Ảnh</div>
          <div>Tên</div>
          <div>Giá</div>
          <div>Đã bán</div>
          <div>Tồn kho</div>
          <div>Danh mục</div>
          <div>Duyệt</div>
          <div>Sửa</div>
          <div>Xóa</div>
        </div>
        {shopProducts.map((product) => (
          <div key={product._id || product.id} className="seller-table-row">
            <div className="seller-thumb">
              {product.images?.[0] ? <img src={resolveImageUrl(product.images[0])} alt={product.name} /> : <div className="image-placeholder" />}
            </div>
            <div>{product.name}</div>
            <div>{formatPrice(product.price)}</div>
            <div>{Number(product.sold ?? 0)}</div>
            <div>{product.quantity ?? 0}</div>
            <div>{categoryMap.get(product.categoryId)?.name || '-'}</div>
            <div>{product.moderationStatus || 'pending'}</div>
            <div>
              <Link to={`/seller/products/edit/${product._id || product.id}`} className="btn btn-outline">Sửa</Link>
            </div>
            <div>
              <button className="btn btn-ghost" onClick={() => handleDelete(product._id || product.id)}>Xóa</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
