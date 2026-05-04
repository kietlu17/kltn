import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import api, { resolveImageUrl } from '../services/api';
import { useCart } from '../context/CartContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import useShopMap from '../hooks/useShopMap';
import ChatWidget from '../components/ChatWidget.jsx';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

export default function ProductDetail() {
  const { id } = useParams();
  const [product, setProduct] = useState(null);
  const [categories, setCategories] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState('');
  const [canReview, setCanReview] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [isZoomOpen, setIsZoomOpen] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [chatOpen, setChatOpen] = useState(false);
  const [selectedVariantId, setSelectedVariantId] = useState('');

  const { addItem } = useCart();
  const { showToast } = useToast();
  const { user } = useAuth();
  const navigate = useNavigate();
  const shopMap = useShopMap();

  useEffect(() => {
    api.get(`/products/${id}`).then((res) => setProduct(res.data)).catch(() => setProduct(null));
  }, [id]);

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

  const effectivePrice = selectedVariant ? selectedVariant.price : product?.price;
  const effectiveStock = selectedVariant ? selectedVariant.quantity : product?.quantity;

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
    if (!Array.isArray(product?.variants) || product.variants.length === 0) {
      setSelectedVariantId('');
      return;
    }
    const preferred = product.variants.find((item) => Number(item.quantity || 0) > 0) || product.variants[0];
    setSelectedVariantId(String(preferred?._id || ''));
  }, [product]);

  useEffect(() => {
    if (!isZoomOpen) return;
    function handleKey(event) {
      if (event.key === 'Escape') setIsZoomOpen(false);
    }
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isZoomOpen]);

  async function addToCart() {
    if (!product) return;
    if (Array.isArray(product.variants) && product.variants.length > 0 && !selectedVariant) {
      showToast('Vui lòng chọn biến thể', 'error');
      return;
    }
    if (Number(effectiveStock ?? 0) <= 0) {
      showToast('Hết hàng', 'error');
      return;
    }
    await addItem(product._id || product.id, 1, selectedVariant ? selectedVariant._id : null);
    showToast('Đã thêm vào giỏ hàng');
  }

  async function buyNow() {
    if (!product) return;
    if (!user?.id) {
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
      await addItem(productId, 1, variantId);
      localStorage.setItem('checkoutSelection', JSON.stringify([lineId]));
      navigate('/checkout', { state: { selectedProductIds: [lineId] } });
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể mua ngay', 'error');
    }
  }

  const handleOpenChat = () => {
    if (!user?.id || user?.role !== 'buyer') {
      showToast('Vui lòng đăng nhập tài khoản người mua để chat', 'error');
      navigate('/login');
      return;
    }
    setChatOpen(true);
  };

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
  const shopId = product?.shopId || product?.shop?._id || product?.shop?.id;
  const shopName = shopMap.get(shopId)?.name || product.shopName || 'Shop chính thức';
  const isOutOfStock = Number(effectiveStock ?? 0) <= 0;
  const sold = Number(product?.sold ?? 0);

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
        </div>

        <div className="product-info">
          <span className="badge">Sàn thương mại</span>
          {isOutOfStock && <span className="badge badge-danger">Hết hàng</span>}
          <h2>{product.name}</h2>
          <div className="price">{formatPrice(effectivePrice)}</div>
          <p className="muted">
            {shopId ? <Link to={`/shop/${shopId}`} className="shop-link">{shopName}</Link> : shopName}
          </p>
          <p className="muted">Đã bán: {sold}</p>
          <p className="muted">Tồn kho: {effectiveStock ?? 0}</p>

          {Array.isArray(product.variants) && product.variants.length > 0 && (
            <div className="product-section">
              <h4>Biến thể</h4>
              <select value={selectedVariantId} onChange={(event) => setSelectedVariantId(event.target.value)}>
                {product.variants.map((variant) => (
                  <option key={variant._id} value={variant._id}>
                    {variant.name} - {formatPrice(variant.price)} - Tồn kho: {variant.quantity}
                  </option>
                ))}
              </select>
            </div>
          )}

          {categoryName && <p className="muted">Danh mục: {categoryName}</p>}

          <div className="product-actions">
            <button className="btn btn-primary" onClick={addToCart} disabled={isOutOfStock}>
              Thêm vào giỏ
            </button>
            <button className="btn btn-outline" onClick={buyNow} disabled={isOutOfStock}>
              Mua ngay
            </button>
            <button className="btn btn-ghost" onClick={handleOpenChat}>
              Chat với shop
            </button>
          </div>

          <div className="product-section">
            <h4>Mô tả</h4>
            <p>{product.description || 'Chưa có mô tả.'}</p>
          </div>

          <div className="product-section">
            <h4>Chi tiết</h4>
            <p>{product.detail || 'Chưa có thông tin chi tiết.'}</p>
          </div>
        </div>
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
          onClose={() => setChatOpen(false)}
        />
      )}
    </div>
  );
}
