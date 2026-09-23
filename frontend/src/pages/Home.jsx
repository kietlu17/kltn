import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, Link } from 'react-router-dom';
import api, { getProductItems, resolveImageUrl } from '../services/api';
import ProductGrid from '../components/ProductGrid.jsx';
import Pagination from '../components/Pagination.jsx';
import { useCart } from '../context/CartContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import useShopMap from '../hooks/useShopMap';
import useInventoryMap, { getAvailableStock } from '../hooks/useInventoryMap';

const defaultCategories = [
  { id: 'deal', name: 'Khuyến mãi sốc' },
  { id: 'electronics', name: 'Điện tử' },
  { id: 'home-life', name: 'Nhà cửa & đời sống' },
  { id: 'fashion', name: 'Thời trang' },
  { id: 'beauty', name: 'Làm đẹp' },
  { id: 'sport', name: 'Thể thao' },
  { id: 'toy', name: 'Đồ chơi' },
  { id: 'grocery', name: 'Tạp hóa' }
];

export default function Home() {
  const [products, setProducts] = useState([]);
  const [productTotal, setProductTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState(null);
  const [categories, setCategories] = useState([]);
  const { addItem } = useCart();
  const { user } = useAuth();
  const { showToast } = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const query = useMemo(() => new URLSearchParams(location.search).get('q') || '', [location.search]);
  const shopMap = useShopMap();
  const inventoryMap = useInventoryMap(products);

  useEffect(() => {
    setPage(1);
  }, [query]);

  useEffect(() => {
    api
      .get('/products', { params: { paginated: true, page, limit: 24, q: query || undefined } })
      .then((res) => {
        const items = getProductItems(res.data);
        setProducts(items);
        setProductTotal(Number(res.data?.pagination?.total ?? items.length));
        setPagination(res.data?.pagination || null);
      })
      .catch(() => {
        setProducts([]);
        setProductTotal(0);
        setPagination(null);
      });
  }, [query, page]);

  useEffect(() => {
    api.get('/categories').then((res) => setCategories(res.data)).catch(() => setCategories([]));
  }, []);

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

  const featuredBannerProducts = useMemo(
    () => decoratedProducts.filter((product) => product?.images?.[0] || product?.imageUrl).slice(0, 3),
    [decoratedProducts]
  );

  const matchingShops = useMemo(() => {
    if (!query) return [];
    const normalized = query.toLowerCase();
    return Array.from(shopMap.values()).filter((shop) => shop?.name?.toLowerCase().includes(normalized));
  }, [query, shopMap]);

  const categoryItems = categories.length
    ? categories.map((category) => ({ id: category._id || category.id, name: category.name }))
    : defaultCategories;

  function openCategory(category) {
    if (!category?.id || defaultCategories.some((item) => item.id === category.id)) {
      navigate(`/products?q=${encodeURIComponent(category?.name || '')}`);
      return;
    }
    navigate(`/products?categoryId=${encodeURIComponent(category.id)}`);
  }

  return (
    <div className="home">
      <section className="container category-section">
        <div className="section-header compact">
          <h3>Danh mục</h3>
          <button type="button" className="section-link as-button" onClick={() => navigate('/products')}>
            Tất cả
          </button>
        </div>
        <div className="category-bar">
          {categoryItems.map((category) => (
            <button
              key={category.id || category.name}
              type="button"
              className="category-tile"
              onClick={() => openCategory(category)}
              title={category.name}
            >
              <span>{category.name}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="banner container">
        <div className="banner-main">
          <div>
            <p className="banner-tag">Ưu đãi nổi bật hôm nay</p>
            <h1>Mua sắm sản phẩm nổi bật từ các shop uy tín</h1>
            <p className="banner-subtitle">
              Đổi trả miễn phí, giao nhanh và voucher độc quyền tại Shopee Lite.
            </p>
            <div className="banner-actions">
              <button type="button" className="btn btn-primary" onClick={() => navigate('/products?sort=sold_desc')}>
                Mua ngay
              </button>
              <button type="button" className="btn btn-outline" onClick={() => navigate('/products?sort=price_asc')}>
                Xem voucher
              </button>
            </div>
          </div>
          <div className="banner-visual" aria-hidden="true">
            <div className="banner-visual-glow" />
            {featuredBannerProducts.length > 0 ? (
              featuredBannerProducts.map((product, index) => (
                <div key={product._id || product.id || index} className={`banner-product banner-product-${index + 1}`}>
                  <img
                    src={resolveImageUrl(product.images?.[0] || product.imageUrl)}
                    alt=""
                  />
                  <span>{index === 0 ? 'Hot deal' : index === 1 ? 'Giá tốt' : 'Bán chạy'}</span>
                </div>
              ))
            ) : (
              <div className="banner-product banner-product-fallback">
                <span>Hot deal</span>
              </div>
            )}
            <div className="banner-deal-card">
              <strong>Flash sale</strong>
              <span>Giảm đến 50%</span>
            </div>
          </div>
        </div>
        <div className="banner-strip">
          <div>
            <span className="banner-strip-icon">GH</span>
            <h4>Miễn phí vận chuyển</h4>
            <p>Cho đơn hàng từ 200.000 VNĐ</p>
          </div>
          <div>
            <span className="banner-strip-icon">XM</span>
            <h4>Shop uy tín</h4>
            <p>Người bán đã xác minh</p>
          </div>
          <div>
            <span className="banner-strip-icon">FS</span>
            <h4>Flash sale mỗi ngày</h4>
            <p>Ưu đãi mới mỗi giờ</p>
          </div>
        </div>
      </section>

      <section className="container">
        <div className="section-header">
          <h2>{query ? `Kết quả cho "${query}"` : 'Gợi ý dành cho bạn'}</h2>
          <span className="section-link">Xem tất cả</span>
        </div>

        {query && (
          <div className="search-section-block">
            <div className="section-header">
              <h3>Cửa hàng</h3>
              <span className="section-link">{matchingShops.length} cửa hàng</span>
            </div>
            {matchingShops.length === 0 ? (
              <div className="empty-state">
                <h3>Không tìm thấy cửa hàng</h3>
                <p>Thử từ khóa khác để khám phá thêm cửa hàng.</p>
              </div>
            ) : (
              <div className="shop-grid">
                {matchingShops.map((shop) => (
                  <Link
                    key={shop._id || shop.id}
                    to={`/shop/${shop._id || shop.id}`}
                    className="shop-card"
                  >
                    <div>
                      <h4>{shop.name}</h4>
                      <p className="muted">{shop.description || 'Chưa có mô tả.'}</p>
                    </div>
                    <span className="shop-link-text">Xem cửa hàng</span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="search-section-block">
          <div className="section-header">
            <h3>Sản phẩm</h3>
            {query && <span className="section-link">{productTotal} sản phẩm</span>}
          </div>
          <ProductGrid products={decoratedProducts} onAdd={addToCart} detailBasePath="/product" />
          <Pagination page={pagination?.page} totalPages={pagination?.totalPages} onPageChange={setPage} />
        </div>
      </section>
    </div>
  );
}
