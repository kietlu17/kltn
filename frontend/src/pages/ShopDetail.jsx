import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import api, { getProductItems } from '../services/api';
import ProductGrid from '../components/ProductGrid.jsx';
import Pagination from '../components/Pagination.jsx';
import { useCart } from '../context/CartContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import useInventoryMap, { getAvailableStock } from '../hooks/useInventoryMap';

export default function ShopDetail() {
  const { id } = useParams();
  const { addItem } = useCart();
  const { user } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [shop, setShop] = useState(null);
  const [loading, setLoading] = useState(true);
  const [categories, setCategories] = useState([]);
  const [products, setProducts] = useState([]);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState(null);
  const [selectedCategoryId, setSelectedCategoryId] = useState('all');
  const inventoryMap = useInventoryMap(products);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    api
      .get(`/shops/${id}`)
      .then((res) => setShop(res.data))
      .catch(() => setShop(null))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (!id) return;
    api
      .get(`/categories?shopId=${encodeURIComponent(id)}`)
      .then((res) => setCategories(res.data))
      .catch(() => setCategories([]));
  }, [id]);

  useEffect(() => {
    if (!id) return;
    setPage(1);
  }, [id]);

  useEffect(() => {
    if (!id) return;
    api
      .get('/products', { params: { shopId: id, paginated: true, page, limit: 24 } })
      .then((res) => {
        setProducts(getProductItems(res.data));
        setPagination(res.data?.pagination || null);
      })
      .catch(() => {
        setProducts([]);
        setPagination(null);
      });
  }, [id, page]);

  async function addToCart(product) {
    if (!product) return;
    if (!user?.id || user.role !== 'buyer') {
      showToast('Vui lòng đăng nhập để thêm sản phẩm vào giỏ hàng', 'error');
      navigate('/login');
      return;
    }
    if (Array.isArray(product.variants) && product.variants.length > 0) {
      showToast('Vui lòng chọn biến thể trước khi thêm vào giỏ');
      navigate(`/product/${product._id || product.id}`);
      return;
    }
    if (Number(product.availableStock ?? product.quantity ?? 0) <= 0) {
      showToast('Hết hàng', 'error');
      return;
    }
    try {
      await addItem(product._id || product.id, 1);
      showToast('Đã thêm vào giỏ hàng');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể thêm vào giỏ', 'error');
    }
  }

  const categoryMap = useMemo(() => {
    const map = new Map();
    categories.forEach((category) => map.set(category._id || category.id, category));
    return map;
  }, [categories]);

  const decoratedProducts = useMemo(
    () =>
      products.map((product) => ({
        ...product,
        availableStock: getAvailableStock(product, null, inventoryMap),
        categoryName: categoryMap.get(product.categoryId)?.name || product.categoryName,
        shopName: shop?.name || product.shopName
      })),
    [products, categoryMap, shop, inventoryMap]
  );

  const filteredProducts = useMemo(() => {
    if (selectedCategoryId === 'all') return decoratedProducts;
    return decoratedProducts.filter(
      (product) => String(product.categoryId) === String(selectedCategoryId)
    );
  }, [decoratedProducts, selectedCategoryId]);

  if (loading) {
    return (
      <div className="container card page-section">
        <h3>Đang tải cửa hàng</h3>
        <p className="muted">Đang tải thông tin cửa hàng và sản phẩm.</p>
      </div>
    );
  }

  if (!shop) {
    return (
      <div className="container card page-section">
        <h3>Không tìm thấy cửa hàng</h3>
        <p className="muted">Shop này có thể đã bị xóa.</p>
      </div>
    );
  }

  return (
    <div className="container page-section shop-detail">
      <div className="card shop-hero">
        <div>
          <h2>{shop?.name || 'Shop'}</h2>
          <p className="muted">{shop?.description || 'Chưa có mô tả.'}</p>
        </div>
        <div className="shop-meta">
          <span className="badge">Shop xác minh</span>
        </div>
      </div>

      <div className="shop-categories">
        <button
          className={`chip ${selectedCategoryId === 'all' ? 'active' : ''}`}
          onClick={() => setSelectedCategoryId('all')}
        >
          Tất cả
        </button>
        {categories.map((category) => (
          <button
            key={category._id || category.id}
            className={`chip ${String(selectedCategoryId) === String(category._id || category.id) ? 'active' : ''}`}
            onClick={() => setSelectedCategoryId(category._id || category.id)}
          >
            {category.name}
          </button>
        ))}
      </div>

      <ProductGrid products={filteredProducts} onAdd={addToCart} detailBasePath="/product" />
      {selectedCategoryId === 'all' && (
        <Pagination page={pagination?.page} totalPages={pagination?.totalPages} onPageChange={setPage} />
      )}
    </div>
  );
}
