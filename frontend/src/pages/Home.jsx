import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, Link } from 'react-router-dom';
import api from '../services/api';
import ProductGrid from '../components/ProductGrid.jsx';
import { useCart } from '../context/CartContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import useShopMap from '../hooks/useShopMap';
import useInventoryMap, { getAvailableStock } from '../hooks/useInventoryMap';

const defaultCategories = [
  'Khuyến mãi sốc',
  'Điện tử',
  'Nhà cửa & đời sống',
  'Thời trang',
  'Làm đẹp',
  'Thể thao',
  'Đồ chơi',
  'Tạp hóa'
];

export default function Home() {
  const [products, setProducts] = useState([]);
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
    const url = query ? `/products?q=${encodeURIComponent(query)}` : '/products';
    api.get(url).then((res) => setProducts(res.data)).catch(() => setProducts([]));
  }, [query]);

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

  const matchingShops = useMemo(() => {
    if (!query) return [];
    const normalized = query.toLowerCase();
    return Array.from(shopMap.values()).filter((shop) => shop?.name?.toLowerCase().includes(normalized));
  }, [query, shopMap]);

  const categoryChips = categories.length ? categories.map((c) => c.name) : defaultCategories;

  return (
    <div className="home">
      <section className="category-bar container">
        {categoryChips.map((category) => (
          <button key={category} className="chip">{category}</button>
        ))}
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
              <button className="btn btn-primary">Mua ngay</button>
              <button className="btn btn-outline">Xem voucher</button>
            </div>
          </div>
          <div className="banner-image" >
                      <img src="../dist/assets/sp.webp" alt="" />
            </div>

        </div>
        <div className="banner-strip">
          <div>
            <h4>Miễn phí vận chuyển</h4>
            <p>Cho đơn hàng từ 200.000 VNĐ</p>
          </div>
          <div>
            <h4>Shop uy tín</h4>
            <p>Người bán đã xác minh</p>
          </div>
          <div>
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
            {query && <span className="section-link">{decoratedProducts.length} sản phẩm</span>}
          </div>
          <ProductGrid products={decoratedProducts} onAdd={addToCart} detailBasePath="/product" />
        </div>
      </section>
    </div>
  );
}
