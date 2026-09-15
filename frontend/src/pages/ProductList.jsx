import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import api, { getProductItems } from '../services/api';
import ProductGrid from '../components/ProductGrid.jsx';
import Pagination from '../components/Pagination.jsx';
import { useCart } from '../context/CartContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import useShopMap from '../hooks/useShopMap';
import useInventoryMap, { getAvailableStock } from '../hooks/useInventoryMap';

export default function ProductList() {
  const [products, setProducts] = useState([]);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState(null);
  const [categories, setCategories] = useState([]);
  const { addItem } = useCart();
  const { user } = useAuth();
  const { showToast } = useToast();
  const shopMap = useShopMap();
  const navigate = useNavigate();
  const location = useLocation();
  const inventoryMap = useInventoryMap(products);

  const queryParams = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const selectedCategoryId = queryParams.get('categoryId') || '';
  const searchQuery = queryParams.get('q') || '';
  const sort = queryParams.get('sort') || 'newest';
  const minPrice = queryParams.get('minPrice') || '';
  const maxPrice = queryParams.get('maxPrice') || '';
  const filtersKey = `${selectedCategoryId}|${searchQuery}|${sort}|${minPrice}|${maxPrice}`;
  const [priceDraft, setPriceDraft] = useState({ minPrice, maxPrice });

  useEffect(() => {
    api.get('/categories').then((res) => setCategories(res.data)).catch(() => setCategories([]));
  }, []);

  useEffect(() => {
    setPriceDraft({ minPrice, maxPrice });
  }, [minPrice, maxPrice]);

  useEffect(() => {
    setPage(1);
  }, [filtersKey]);

  useEffect(() => {
    api
      .get('/products', {
        params: {
          paginated: true,
          page,
          limit: 24,
          categoryId: selectedCategoryId || undefined,
          q: searchQuery || undefined,
          sort,
          minPrice: minPrice || undefined,
          maxPrice: maxPrice || undefined
        }
      })
      .then((res) => {
        setProducts(getProductItems(res.data));
        setPagination(res.data?.pagination || null);
      })
      .catch(() => {
        setProducts([]);
        setPagination(null);
      });
  }, [page, filtersKey]);

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
    await addItem(product._id || product.id, 1);
    showToast('Đã thêm vào giỏ hàng');
  }

  const categoryMap = useMemo(() => {
    const map = new Map();
    categories.forEach((category) => map.set(category._id || category.id, category));
    return map;
  }, [categories]);

  const selectedCategory = useMemo(
    () => categoryMap.get(selectedCategoryId) || null,
    [categoryMap, selectedCategoryId]
  );

  const decoratedProducts = useMemo(
    () =>
      products.map((product) => ({
        ...product,
        availableStock: getAvailableStock(product, null, inventoryMap),
        categoryName: categoryMap.get(product.categoryId)?.name || product.categoryName,
        shopName: shopMap.get(product.shopId)?.name || product.shopName
      })),
    [products, categoryMap, shopMap, inventoryMap]
  );

  function updateFilters(nextValues) {
    const params = new URLSearchParams(location.search);
    Object.entries(nextValues).forEach(([key, value]) => {
      if (value == null || value === '') {
        params.delete(key);
      } else {
        params.set(key, String(value));
      }
    });
    const queryString = params.toString();
    navigate(queryString ? `/products?${queryString}` : '/products');
  }

  function applyPriceFilter(event) {
    event.preventDefault();
    updateFilters({
      minPrice: priceDraft.minPrice.trim(),
      maxPrice: priceDraft.maxPrice.trim()
    });
  }

  function clearFilters() {
    setPriceDraft({ minPrice: '', maxPrice: '' });
    navigate('/products');
  }

  return (
    <div className="container page-section product-list-page">
      <div className="section-header product-list-header">
        <div>
          <h2>{selectedCategory?.name || (searchQuery ? `Tìm kiếm "${searchQuery}"` : 'Sàn thương mại')}</h2>
          <p className="muted">Lọc theo danh mục, khoảng giá và thứ tự hiển thị.</p>
        </div>
        <span className="section-link">{pagination?.total ?? decoratedProducts.length} sản phẩm</span>
      </div>

      <section className="product-filter-panel">
        <div className="filter-field">
          <label>Danh mục</label>
          <select
            value={selectedCategoryId}
            onChange={(event) => updateFilters({ categoryId: event.target.value })}
          >
            <option value="">Tất cả danh mục</option>
            {categories.map((category) => (
              <option key={category._id || category.id} value={category._id || category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-field">
          <label>Sắp xếp</label>
          <select value={sort} onChange={(event) => updateFilters({ sort: event.target.value })}>
            <option value="newest">Mới nhất</option>
            <option value="price_asc">Giá từ thấp đến cao</option>
            <option value="price_desc">Giá từ cao đến thấp</option>
            <option value="sold_desc">Bán chạy</option>
          </select>
        </div>

        <form className="price-filter-form" onSubmit={applyPriceFilter}>
          <div className="filter-field">
            <label>Giá từ</label>
            <input
              inputMode="numeric"
              value={priceDraft.minPrice}
              onChange={(event) => setPriceDraft((current) => ({ ...current, minPrice: event.target.value }))}
              placeholder="0"
            />
          </div>
          <div className="filter-field">
            <label>Đến</label>
            <input
              inputMode="numeric"
              value={priceDraft.maxPrice}
              onChange={(event) => setPriceDraft((current) => ({ ...current, maxPrice: event.target.value }))}
              placeholder="1.000.000"
            />
          </div>
          <button type="submit" className="btn btn-primary">Áp dụng</button>
        </form>

        <button type="button" className="btn btn-outline" onClick={clearFilters}>
          Xóa lọc
        </button>
      </section>

      <ProductGrid products={decoratedProducts} onAdd={addToCart} detailBasePath="/product" />
      <Pagination page={pagination?.page} totalPages={pagination?.totalPages} onPageChange={setPage} />
    </div>
  );
}
