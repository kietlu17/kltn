import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { getProductItems, resolveImageUrl } from '../services/api';
import Pagination from '../components/Pagination.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import useInventoryMap, { getAvailableStock } from '../hooks/useInventoryMap';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

export default function SellerProductList() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const [products, setProducts] = useState([]);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState(null);
  const [categories, setCategories] = useState([]);
  const inventoryMap = useInventoryMap(products);

  const loadProducts = () => {
    const shopKey = user?.shopId || user?.id;
    if (!shopKey) {
      setProducts([]);
      return;
    }
    api
      .get('/products', { params: { shopId: shopKey, paginated: true, page, limit: 20 } })
      .then((res) => {
        setProducts(getProductItems(res.data));
        setPagination(res.data?.pagination || null);
      })
      .catch(() => {
        setProducts([]);
        setPagination(null);
      });
  };

  useEffect(() => {
    setPage(1);
  }, [user?.shopId, user?.id]);

  useEffect(() => {
    loadProducts();
  }, [user, page]);

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
      return products
        .filter((p) => p.shopId === shopKey)
        .map((product) => ({ ...product, availableStock: getAvailableStock(product, null, inventoryMap) }));
    }
    return products.map((product) => ({ ...product, availableStock: getAvailableStock(product, null, inventoryMap) }));
  }, [products, user, inventoryMap]);

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
        <div className="form-actions">
          <span className="section-link">{pagination?.total ?? shopProducts.length} sản phẩm</span>
          <Link to="/seller/products/create" className="btn btn-primary">Tạo sản phẩm</Link>
        </div>
      </div>
      <div className="seller-table seller-products-table">
        <div className="seller-table-row seller-table-head">
          <div>Ảnh</div>
          <div>Tên</div>
          <div>Giá gốc</div>
          <div>Giá giảm</div>
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
            <div>{formatPrice(product.originalPrice ?? product.price)}</div>
            <div>{formatPrice(product.price)}</div>
            <div>{Number(product.sold ?? 0)}</div>
            <div>{product.availableStock ?? product.quantity ?? 0}</div>
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
      <Pagination page={pagination?.page} totalPages={pagination?.totalPages} onPageChange={setPage} />
    </div>
  );
}
