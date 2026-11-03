import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import api, { getProductItems, resolveImageUrl } from '../services/api';
import { useCart } from '../context/CartContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import useShopMap from '../hooks/useShopMap';
import useInventoryMap, { getAvailableStock } from '../hooks/useInventoryMap';
import ChatWidget from '../components/ChatWidget.jsx';
import ProductGrid from '../components/ProductGrid.jsx';

const RECENTLY_VIEWED_KEY = 'recentlyViewedProducts';
const RELATED_STOP_WORDS = new Set([
  'va',
  'voi',
  'cho',
  'cua',
  'hang',
  'san',
  'pham',
  'loai',
  'mau',
  'size',
  'cao',
  'cap',
  'chinh',
  'hang'
]);

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

function getProductKeywords(name) {
  return String(name || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/đ/g, 'd')
    .split(/[^a-z0-9]+/)
    .filter((word) => word.length > 1 && !RELATED_STOP_WORDS.has(word));
}

function getPriceScore(basePrice, candidatePrice) {
  const base = Number(basePrice || 0);
  const candidate = Number(candidatePrice || 0);
  if (!base || !candidate) return 0;
  const differenceRatio = Math.abs(candidate - base) / base;
  return differenceRatio <= 0.25 ? 10 : 0;
}

export default function ProductDetail() {
  const { id } = useParams();
  const [product, setProduct] = useState(null);
  const [categories, setCategories] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [allProducts, setAllProducts] = useState([]);
  const [recentProducts, setRecentProducts] = useState([]);
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState('');
  const [canReview, setCanReview] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [isZoomOpen, setIsZoomOpen] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatHandoff, setChatHandoff] = useState(false);
  const [selectedVariantId, setSelectedVariantId] = useState('');
  const [vouchers, setVouchers] = useState([]);
  const [voucherLoading, setVoucherLoading] = useState(false);
  const [priceDetailOpen, setPriceDetailOpen] = useState(false);
  const [purchaseQuantity, setPurchaseQuantity] = useState(1);

  const { addItem } = useCart();
  const { showToast } = useToast();
  const { user } = useAuth();
  const navigate = useNavigate();
  const shopMap = useShopMap();

  useEffect(() => {
    api.get(`/products/${id}`).then((res) => setProduct(res.data)).catch(() => setProduct(null));
  }, [id]);

  useEffect(() => {
    api
      .get('/products', { params: { paginated: true, page: 1, limit: 48 } })
      .then((res) => setAllProducts(getProductItems(res.data)))
      .catch(() => setAllProducts([]));
  }, []);

  useEffect(() => {
    api.get('/categories').then((res) => setCategories(res.data)).catch(() => setCategories([]));
  }, []);

  const loadReviews = () => {
    if (!user?.id || (user.role !== 'buyer' && user.role !== 'admin')) {
      setReviews([]);
      return;
    }
    api.get(`/reviews/product/${id}`).then((res) => setReviews(res.data)).catch(() => setReviews([]));
  };

  useEffect(() => {
    loadReviews();
  }, [id, user?.id, user?.role]);

  useEffect(() => {
    if (!user?.id || user?.role !== 'buyer') {
      setCanReview(false);
      return;
    }

    api
      .get(`/orders/${user.id}`)
      .then((res) => {
        const orders = Array.isArray(res.data) ? res.data : [];
        const hasPurchased = orders.some((order) => {
          if (order.status === 'cancelled') return false;
          let items = [];

          if (Array.isArray(order.products)) {
            items = order.products;
          } else if (typeof order.products === 'string') {
            try {
              items = JSON.parse(order.products);
            } catch {
              items = [];
            }
          }

          return items.some((item) => String(item.productId) === String(id));
        });

        setCanReview(hasPurchased);
      })
      .catch(() => setCanReview(false));
  }, [id, user]);

  const selectedVariant = useMemo(() => {
    if (!Array.isArray(product?.variants) || product.variants.length === 0) return null;
    return product.variants.find((item) => String(item._id) === String(selectedVariantId)) || null;
  }, [product, selectedVariantId]);
  const inventoryProducts = useMemo(
    () => (product ? [product, ...allProducts, ...recentProducts] : [...allProducts, ...recentProducts]),
    [product, allProducts, recentProducts]
  );
  const inventoryMap = useInventoryMap(inventoryProducts);

  const effectivePrice = selectedVariant ? selectedVariant.price : product?.price;
  const effectiveStock = getAvailableStock(product, selectedVariant, inventoryMap);
  const productShopId = product?.shopId || product?.shop?._id || product?.shop?.id;

  const voucherItems = useMemo(() => {
    if (!product) return [];
    return [{
      productId: product._id || product.id,
      shopId: productShopId,
      quantity: 1,
      price: effectivePrice
    }];
  }, [product, productShopId, effectivePrice]);

  const categoryMap = useMemo(() => {
    const map = new Map();
    categories.forEach((category) => map.set(category._id || category.id, category));
    return map;
  }, [categories]);

  const resolvedImages = useMemo(() => {
    if (!product) return [];

    const activeVariant = Array.isArray(product?.variants)
      ? product.variants.find((item) => String(item._id) === String(selectedVariantId))
      : null;

    const productImages = product?.images?.length ? product.images : [product?.imageUrl].filter(Boolean);
    const selectedVariantImage = activeVariant?.imageUrl ? [activeVariant.imageUrl] : [];
    const uniqueImages = [...selectedVariantImage, ...productImages].filter(
      (src, index, arr) => Boolean(src) && arr.indexOf(src) === index
    );

    return uniqueImages.map((src) => resolveImageUrl(src)).filter(Boolean);
  }, [product, selectedVariantId]);

  const hero = resolvedImages[activeIndex] || resolvedImages[0];

  useEffect(() => {
    if (!resolvedImages.length) return;
    setActiveIndex(0);
  }, [resolvedImages]);

  useEffect(() => {
    setPurchaseQuantity(1);
    setPriceDetailOpen(false);
  }, [id, selectedVariantId]);

  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(RECENTLY_VIEWED_KEY) || '[]');
      setRecentProducts(Array.isArray(stored) ? stored : []);
    } catch {
      setRecentProducts([]);
    }
  }, []);

  useEffect(() => {
    if (!product) return;
    const viewedProduct = {
      _id: product._id || product.id,
      id: product._id || product.id,
      name: product.name,
      price: product.price,
      originalPrice: product.originalPrice,
      images: product.images,
      imageUrl: product.imageUrl,
      quantity: product.quantity,
      sold: product.sold,
      variants: product.variants,
      categoryId: product.categoryId,
      shopId: product.shopId,
      categoryName: categoryMap.get(product.categoryId)?.name || product.categoryName,
      shopName: shopMap.get(product.shopId)?.name || product.shopName
    };

    setRecentProducts((current) => {
      const next = [
        viewedProduct,
        ...current.filter((item) => String(item._id || item.id) !== String(viewedProduct.id))
      ].slice(0, 9);
      localStorage.setItem(RECENTLY_VIEWED_KEY, JSON.stringify(next));
      return next;
    });
  }, [product, categoryMap, shopMap]);

  useEffect(() => {
    if (!Array.isArray(product?.variants) || product.variants.length === 0) {
      setSelectedVariantId('');
      return;
    }
    const preferred = product.variants.find((item) => getAvailableStock(product, item, inventoryMap) > 0) || product.variants[0];
    setSelectedVariantId(String(preferred?._id || ''));
  }, [product, inventoryMap]);

  useEffect(() => {
    if (!user?.id || user?.role !== 'buyer' || voucherItems.length === 0 || !Number.isFinite(Number(effectivePrice))) {
      setVouchers([]);
      return;
    }

    let cancelled = false;
    setVoucherLoading(true);
    api
      .post('/vouchers/checkout', { userId: user.id, items: voucherItems })
      .then((res) => {
        if (!cancelled) setVouchers(Array.isArray(res.data) ? res.data : []);
      })
      .catch(() => {
        if (!cancelled) setVouchers([]);
      })
      .finally(() => {
        if (!cancelled) setVoucherLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [user?.id, user?.role, voucherItems, effectivePrice]);

  useEffect(() => {
    if (!isZoomOpen) return;
    function handleKey(event) {
      if (event.key === 'Escape') setIsZoomOpen(false);
    }
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isZoomOpen]);

  async function addToCart(targetProduct = product) {
    if (!targetProduct) return;
    if (!user?.id || user.role !== 'buyer') {
      showToast('Vui lòng đăng nhập để thêm sản phẩm vào giỏ hàng', 'error');
      navigate('/login');
      return;
    }
    const isCurrentProduct = String(targetProduct._id || targetProduct.id) === String(product?._id || product?.id);
    const targetVariant = isCurrentProduct ? selectedVariant : null;
    if (Array.isArray(targetProduct.variants) && targetProduct.variants.length > 0 && !targetVariant) {
      showToast('Vui lòng chọn biến thể trước khi thêm vào giỏ');
      navigate(`/product/${targetProduct._id || targetProduct.id}`);
      return;
    }
    const targetStock = isCurrentProduct
      ? effectiveStock
      : getAvailableStock(targetProduct, targetVariant, inventoryMap);
    if (Number(targetStock ?? 0) <= 0) {
      showToast('Hết hàng', 'error');
      return;
    }
    const quantity = isCurrentProduct ? currentQuantity : 1;
    await addItem(targetProduct._id || targetProduct.id, quantity, targetVariant ? targetVariant._id : null);
    showToast('Đã thêm vào giỏ hàng');
  }

  async function buyNow() {
    if (!product) return;
    if (!user?.id || user.role !== 'buyer') {
      showToast('Vui lòng đăng nhập để tiếp tục thanh toán', 'error');
      navigate('/login');
      return;
    }
    if (Array.isArray(product.variants) && product.variants.length > 0 && !selectedVariant) {
      showToast('Vui lòng chọn biến thể', 'error');
      return;
    }
    if (Number(effectiveStock ?? 0) <= 0) {
      showToast('Hết hàng', 'error');
      return;
    }

    const productId = product._id || product.id;
    const variantId = selectedVariant ? selectedVariant._id : null;
    const lineId = `${productId || ''}::${variantId || ''}`;

    try {
      await addItem(productId, currentQuantity, variantId);
      localStorage.setItem('checkoutSelection', JSON.stringify([lineId]));
      navigate('/checkout', { state: { selectedProductIds: [lineId] } });
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể mua ngay', 'error');
    }
  }

  const handleOpenChat = () => {
    setChatHandoff(false);
    setChatOpen(true);
  };

  // The shopping assistant asks for a human handoff after repeated clarifications.
  useEffect(() => {
    function handleHandoff() {
      setChatHandoff(true);
      setChatOpen(true);
    }
    window.addEventListener('assistant-handoff', handleHandoff);
    return () => window.removeEventListener('assistant-handoff', handleHandoff);
  }, []);

  function openZoom() {
    if (!hero) return;
    setZoomLevel(1);
    setIsZoomOpen(true);
  }

  function updateZoom(next) {
    const clamped = Math.min(3, Math.max(1, Number(next) || 1));
    setZoomLevel(clamped);
  }

  async function submitReview() {
    if (!user?.id) return;
    try {
      await api.post(`/reviews/product/${id}`, {
        userId: user.id,
        userName: user.email,
        rating,
        comment
      });
      showToast('Đã gửi đánh giá');
      setComment('');
      setRating(5);
      loadReviews();
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể gửi đánh giá', 'error');
    }
  }

  if (!product) {
    return <div className="container card">Không tìm thấy sản phẩm</div>;
  }

  const categoryName = categoryMap.get(product.categoryId)?.name || product.categoryName;
  const shopId = productShopId;
  const shopName = shopMap.get(shopId)?.name || product.shopName || 'Shop chính thức';
  const isOutOfStock = Number(effectiveStock ?? 0) <= 0;
  const sold = Number(product?.sold ?? 0);
  const reviewCount = reviews.length;
  const averageRating = reviewCount
    ? reviews.reduce((sum, item) => sum + Number(item.rating || 0), 0) / reviewCount
    : 0;
  const effectiveOriginalPrice = selectedVariant
    ? (selectedVariant.originalPrice ?? selectedVariant.price)
    : (product.originalPrice ?? product.price);
  const productDiscount = Math.max(Number(effectiveOriginalPrice || 0) - Number(effectivePrice || 0), 0);
  const eligibleVouchers = vouchers.filter((voucher) => voucher.eligible && Number(voucher.discountAmount || 0) > 0);
  const platformVoucher = eligibleVouchers
    .filter((voucher) => voucher.type === 'platform')
    .sort((a, b) => Number(b.discountAmount || 0) - Number(a.discountAmount || 0))[0];
  const shopVoucher = eligibleVouchers
    .filter((voucher) => voucher.type === 'shop' && String(voucher.shopId) === String(shopId))
    .sort((a, b) => Number(b.discountAmount || 0) - Number(a.discountAmount || 0))[0];
  const platformDiscount = Number(platformVoucher?.discountAmount || 0);
  const shopDiscount = Number(shopVoucher?.discountAmount || 0);
  const priceAfterVoucher = Math.max(Number(effectivePrice || 0) - platformDiscount - shopDiscount, 0);
  const decorateSuggestion = (item) => ({
    ...item,
    availableStock: getAvailableStock(item, null, inventoryMap),
    categoryName: categoryMap.get(item.categoryId)?.name || item.categoryName,
    shopName: shopMap.get(item.shopId)?.name || item.shopName
  });
  const currentKeywords = new Set(getProductKeywords(product.name));
  const maxSold = Math.max(...allProducts.map((item) => Number(item.sold || 0)), 0);
  const scoreRelatedProduct = (item) => {
    const candidateStock = getAvailableStock(item, null, inventoryMap);
    const matchedKeywordCount = getProductKeywords(item.name).filter((word) => currentKeywords.has(word)).length;
    const soldScore = maxSold > 0 ? Math.min(10, Math.round((Number(item.sold || 0) / maxSold) * 10)) : 0;

    return (
      (item.categoryId && product.categoryId && String(item.categoryId) === String(product.categoryId) ? 50 : 0) +
      (matchedKeywordCount > 0 ? 30 : 0) +
      (item.shopId && shopId && String(item.shopId) === String(shopId) ? 15 : 0) +
      getPriceScore(effectivePrice, item.price) +
      soldScore +
      (Number(candidateStock ?? 0) > 0 ? 10 : 0)
    );
  };
  const relatedProducts = allProducts
    .filter((item) => String(item._id || item.id) !== String(product._id || product.id))
    .map((item) => ({ item, score: scoreRelatedProduct(item) }))
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score || Number(b.item.sold || 0) - Number(a.item.sold || 0))
    .slice(0, 8)
    .map(({ item }) => decorateSuggestion(item));
  const viewedProducts = recentProducts
    .filter((item) => String(item._id || item.id) !== String(product._id || product.id))
    .slice(0, 8)
    .map(decorateSuggestion);
  const stockQuantity = Math.max(Number(effectiveStock ?? 0), 0);
  const currentQuantity = Math.min(purchaseQuantity, Math.max(stockQuantity, 1));
  const likedCount = Math.max(sold * 3 + reviewCount, 0);
  const selectedShopVoucher = shopVoucher || eligibleVouchers.find((voucher) => voucher.type === 'shop');
  const visibleVoucher = selectedShopVoucher;

  return (
    <div className="container page-section">
      <div className="product-detail">
        <div className="product-gallery">
          <div className="product-hero">
            {hero ? (
              <button type="button" className="hero-button" onClick={openZoom}>
                <img src={hero} alt={product.name} />
              </button>
            ) : (
              <div className="image-placeholder large" />
            )}
          </div>

          <div className="product-thumbs">
            {resolvedImages.map((src, index) => (
              <button
                key={`${src}-${index}`}
                type="button"
                className={`thumb ${index === activeIndex ? 'active' : ''}`}
                onClick={() => setActiveIndex(index)}
              >
                <img src={src} alt={`${product.name} ${index + 1}`} />
              </button>
            ))}
          </div>

          <div className="product-share-row">
            <span>Chia sẻ:</span>
            <button type="button">f</button>
            <button type="button">m</button>
            <button type="button">p</button>
            <span className="product-liked">♡ Đã thích ({likedCount.toLocaleString('vi-VN')})</span>
          </div>
        </div>

        <div className="product-info">
          <div className="product-title-badges">
            <span className="badge">Sàn thương mại</span>
            <span className="badge badge-danger">Mall</span>
            {isOutOfStock && <span className="badge badge-danger">Hết hàng</span>}
          </div>
          <h2>{product.name}</h2>

          <div className="product-rating-meta">
            <span>{averageRating ? averageRating.toFixed(1) : 'Chưa có'}</span>
            <span className="rating-stars-static">★★★★★</span>
            <span>{reviewCount.toLocaleString('vi-VN')} Đánh Giá</span>
            <span>Đã Bán {sold.toLocaleString('vi-VN')}</span>
          </div>

          <div className="product-price-panel">
            <div className="product-price-line">
              <div className="price">{formatPrice(effectivePrice)}</div>
              <button
                type="button"
                className="voucher-price-label"
                onClick={() => setPriceDetailOpen((current) => !current)}
              >
                Giá sau voucher
              </button>
            </div>
          </div>

          {Array.isArray(product.variants) && product.variants.length > 0 && (
            <div className="purchase-row">
              <span>Biến thể</span>
              <select value={selectedVariantId} onChange={(event) => setSelectedVariantId(event.target.value)}>
                {product.variants.map((variant) => (
                  <option key={variant._id} value={variant._id}>
                    {variant.name} - {formatPrice(variant.price)}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="purchase-row">
            <span>Mã Giảm Giá Của Shop</span>
            <strong>{selectedShopVoucher ? `Giảm ${Number(selectedShopVoucher.discountValue || 0)}%` : 'Chưa có mã'}</strong>
          </div>

          <div className="purchase-row">
            <span>Vận Chuyển</span>
            <strong>{isOutOfStock ? 'Không hỗ trợ' : 'Có hỗ trợ giao hàng'}</strong>
          </div>

          <div className="purchase-row">
            <span>An Tâm Mua Sắm</span>
            <strong>Shopee Xử Lý · Trả hàng miễn phí 15 ngày · Chính hãng 100%</strong>
          </div>

          <div className="purchase-row quantity-row">
            <span>Số Lượng</span>
            <div className="quantity-control">
              <button
                type="button"
                onClick={() => setPurchaseQuantity((value) => Math.max(1, value - 1))}
                disabled={currentQuantity <= 1}
              >
                -
              </button>
              <input
                type="number"
                min="1"
                max={stockQuantity || 1}
                value={currentQuantity}
                onChange={(event) => {
                  const next = Number(event.target.value || 1);
                  setPurchaseQuantity(Math.min(Math.max(next, 1), stockQuantity || 1));
                }}
              />
              <button
                type="button"
                onClick={() => setPurchaseQuantity((value) => Math.min(value + 1, stockQuantity || 1))}
                disabled={currentQuantity >= (stockQuantity || 1)}
              >
                +
              </button>
            </div>
            <span className="stock-text">{isOutOfStock ? 'Hết hàng' : `${stockQuantity.toLocaleString('vi-VN')} còn hàng`}</span>
          </div>

          <div className="product-actions">
            <button className="btn btn-primary" onClick={() => addToCart()} disabled={isOutOfStock}>
              Thêm vào giỏ
            </button>
            <button className="btn btn-outline" onClick={buyNow} disabled={isOutOfStock}>
              Mua với voucher
            </button>
            <button className="btn btn-ghost" onClick={handleOpenChat}>
              Chat với shop
            </button>
          </div>

          {priceDetailOpen && (
            <div className="price-detail-panel">
              <h4>Chi tiết giá</h4>
              <div className="price-detail-row">
                <span>Giá gốc</span>
                <strong>{formatPrice(effectiveOriginalPrice)}</strong>
              </div>
              <div className="price-detail-row">
                <span>Giảm giá sản phẩm</span>
                <strong className="discount-value">-{formatPrice(productDiscount)}</strong>
              </div>
              <div className="price-detail-divider" />
              <div className="price-detail-row stacked">
                <span>
                  Voucher Shopee
                  {platformVoucher && (
                    <small>
                      Mua từ {formatPrice(platformVoucher.minOrderAmount)} để được giảm {Number(platformVoucher.discountValue || 0)}%.
                      Số lượng Voucher có hạn.
                    </small>
                  )}
                </span>
                <strong className="discount-value">-{formatPrice(platformDiscount)}</strong>
              </div>
              <div className="price-detail-row stacked">
                <span>
                  Voucher của Shop
                  {shopVoucher && (
                    <small>
                      Mua từ {formatPrice(shopVoucher.minOrderAmount)} để được giảm {Number(shopVoucher.discountValue || 0)}%.
                      Số lượng Voucher có hạn.
                    </small>
                  )}
                </span>
                <strong className="discount-value">-{formatPrice(shopDiscount)}</strong>
              </div>
              <div className="price-detail-divider" />
              <div className="price-detail-total">
                <span>Giá sau voucher</span>
                <strong>{formatPrice(priceAfterVoucher)}</strong>
              </div>
              <p className="price-detail-note">
                {voucherLoading
                  ? 'Đang tải Voucher khả dụng.'
                  : '*Vui lòng thêm Voucher khả dụng ở bước thanh toán để được giá như trên'}
              </p>
            </div>
          )}

        </div>
      </div>

      <section className="shop-summary">
        <div className="shop-summary-main">
          <div className="shop-avatar">{shopName.slice(0, 2).toUpperCase()}</div>
          <div>
            <h3>{shopName}</h3>
            <p className="muted">Online 2 phút trước</p>
            <div className="shop-summary-actions">
              <button type="button" className="btn btn-outline" onClick={handleOpenChat}>Chat ngay</button>
              {shopId && <Link to={`/shop/${shopId}`} className="btn btn-ghost">Xem shop</Link>}
            </div>
          </div>
        </div>
        <div className="shop-summary-stats">
          <div><span>Đánh Giá</span><strong>{reviewCount.toLocaleString('vi-VN')}</strong></div>
          <div><span>Sản Phẩm</span><strong>{allProducts.filter((item) => String(item.shopId) === String(shopId)).length}</strong></div>
          <div><span>Tỉ Lệ Phản Hồi</span><strong>99%</strong></div>
          <div><span>Tham Gia</span><strong>4 năm trước</strong></div>
        </div>
      </section>

      <div className="product-content-layout">
        <div className="product-content-main">
          <section className="detail-block">
            <h3>Chi tiết sản phẩm</h3>
            <dl className="product-specs">
              <div>
                <dt>Danh mục</dt>
                <dd>{categoryName || 'Chưa phân loại'}</dd>
              </div>
              <div>
                <dt>Kho</dt>
                <dd>{isOutOfStock ? 'Hết hàng' : 'Còn hàng'}</dd>
              </div>
              <div>
                <dt>Cửa hàng</dt>
                <dd>{shopName}</dd>
              </div>
              <div>
                <dt>Đã bán</dt>
                <dd>{sold.toLocaleString('vi-VN')}</dd>
              </div>
              <div>
                <dt>Biến thể</dt>
                <dd>{Array.isArray(product.variants) && product.variants.length > 0 ? `${product.variants.length} lựa chọn` : 'Không có'}</dd>
              </div>
            </dl>
          </section>

          <section className="detail-block">
            <h3>Mô tả sản phẩm</h3>
            <p className="product-description">{product.description || product.detail || 'Chưa có mô tả.'}</p>
            {product.detail && product.detail !== product.description && (
              <p className="product-description">{product.specifications?.length > 0
                ? product.detail.split('\nThông số kỹ thuật:\n')[0]
                : product.detail}</p>
            )}
          </section>
          {product.specifications?.length > 0 && (
            <section className="detail-block">
              <h3>Thông số kỹ thuật</h3>
              <dl className="product-specs">
                {product.specifications.map((specification) => (
                  <div key={specification.name}>
                    <dt>{specification.name}</dt>
                    <dd>{specification.value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}
        </div>

        <aside className="product-content-side">
          <section className="shop-voucher-box">
            <h3>Mã giảm giá của Shop</h3>
            {visibleVoucher ? (
              <div className="shop-voucher-card">
                <strong>Giảm {Number(visibleVoucher.discountValue || 0)}%</strong>
                <span>Đơn tối thiểu {formatPrice(visibleVoucher.minOrderAmount || 0)}</span>
                <small>{Number(visibleVoucher.remaining ?? visibleVoucher.quantity ?? 0).toLocaleString('vi-VN')} mã còn lại</small>
                <button type="button">Lưu</button>
              </div>
            ) : (
              <p className="muted">Shop chưa có voucher khả dụng.</p>
            )}
          </section>
        </aside>
      </div>

      <div className="reviews">
        <div className="section-header">
          <h3>Đánh giá từ khách hàng</h3>
          <span className="section-link">{reviews.length} đánh giá</span>
        </div>

        {canReview ? (
          <div className="card review-form">
            <h4>Viết đánh giá</h4>
            <div className="rating-row">
              <span className="muted">Điểm của bạn</span>
              <div className="rating-stars">
                {[1, 2, 3, 4, 5].map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={`star ${rating >= value ? 'active' : ''}`}
                    onClick={() => setRating(value)}
                  >
                    {'\u2605'}
                  </button>
                ))}
              </div>
            </div>
            <label>Nội dung</label>
            <textarea
              placeholder="Chia sẻ trải nghiệm của bạn về sản phẩm này"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
            />
            <button className="btn btn-primary" onClick={submitReview}>Gửi đánh giá</button>
          </div>
        ) : !user?.id ? (
          <div className="card review-form muted">Vui lòng đăng nhập tài khoản người mua để xem và gửi đánh giá.</div>
        ) : (
          <div className="card review-form muted">Chỉ người mua đã mua sản phẩm này mới có thể đánh giá.</div>
        )}

        <div className="review-list">
          {reviews.length === 0 ? (
            <div className="empty-state">Chưa có đánh giá. Hãy là người đầu tiên chia sẻ nhận xét.</div>
          ) : (
            reviews.map((review) => (
              <div key={review._id || review.id} className="card review-card">
                <div className="review-header">
                  <div>
                    <strong>{review.userName || 'Ẩn danh'}</strong>
                    <div className="review-stars">
                      {[1, 2, 3, 4, 5].map((value) => (
                        <span key={value} className={review.rating >= value ? 'active' : ''}>{'\u2605'}</span>
                      ))}
                    </div>
                  </div>
                  <span className="muted">
                    {review.createdAt ? new Date(review.createdAt).toLocaleDateString('vi-VN') : ''}
                  </span>
                </div>
                <p>{review.comment || 'Không có bình luận.'}</p>
              </div>
            ))
          )}
        </div>
      </div>

      {relatedProducts.length > 0 && (
        <section className="product-suggestion-section">
          <div className="section-header">
            <h3>Sản phẩm liên quan</h3>
            <span className="section-link">{relatedProducts.length} sản phẩm</span>
          </div>
          <ProductGrid products={relatedProducts} onAdd={addToCart} detailBasePath="/product" />
        </section>
      )}

      {viewedProducts.length > 0 && (
        <section className="product-suggestion-section">
          <div className="section-header">
            <h3>Sản phẩm đã xem gần đây</h3>
            <span className="section-link">{viewedProducts.length} sản phẩm</span>
          </div>
          <ProductGrid products={viewedProducts} onAdd={addToCart} detailBasePath="/product" />
        </section>
      )}

      {isZoomOpen && hero && (
        <div className="image-modal" onClick={() => setIsZoomOpen(false)}>
          <div className="image-modal-content" onClick={(event) => event.stopPropagation()}>
            <div className="image-modal-toolbar">
              <span className="muted">Phóng to: {Math.round(zoomLevel * 100)}%</span>
              <div className="zoom-actions">
                <button type="button" className="zoom-btn" onClick={() => updateZoom(zoomLevel - 0.2)}>
                  -
                </button>
                <button type="button" className="zoom-btn" onClick={() => updateZoom(zoomLevel + 0.2)}>
                  +
                </button>
                <button type="button" className="zoom-btn ghost" onClick={() => updateZoom(1)}>
                  Đặt lại
                </button>
                <button type="button" className="zoom-btn close" onClick={() => setIsZoomOpen(false)}>
                  Đóng
                </button>
              </div>
            </div>
            <div className="image-modal-body">
              <img
                src={hero}
                alt={product.name}
                style={{ transform: `scale(${zoomLevel})` }}
                className="zoomed-image"
              />
            </div>
          </div>
        </div>
      )}

      {chatOpen && (
        <ChatWidget
          product={product}
          shopId={shopId}
          shopName={shopName}
          key={chatHandoff ? 'handoff' : 'assistant'}
          initialMode={chatHandoff ? 'human' : 'ai'}
          onClose={() => setChatOpen(false)}
        />
      )}
    </div>
  );
}
