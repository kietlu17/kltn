import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import api, { getProductItems } from '../services/api';
import CartItem from '../components/CartItem.jsx';
import { useCart } from '../context/CartContext.jsx';
import useShopMap from '../hooks/useShopMap';
import { useToast } from '../context/ToastContext.jsx';
import Orders from './Orders.jsx';
import useInventoryMap, { getAvailableStock } from '../hooks/useInventoryMap';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

function getLineId(item) {
  return `${item?.productId || ''}::${item?.variantId || ''}`;
}

export default function Cart() {
  const { cartProducts, removeItem, updateItem, refreshCart } = useCart();
  const [products, setProducts] = useState([]);
  const shopMap = useShopMap();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [activeTab, setActiveTab] = useState(() => {
    const tab = new URLSearchParams(location.search).get('tab');
    return tab === 'orders' ? 'orders' : 'cart';
  });
  const [selectedIds, setSelectedIds] = useState(() => {
    try {
      const stored = JSON.parse(localStorage.getItem('checkoutSelection') || '[]');
      return Array.isArray(stored) ? stored : [];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    refreshCart();
  }, [refreshCart]);

  useEffect(() => {
    const productIds = [...new Set(cartProducts.map((item) => item.productId).filter(Boolean))];
    if (!productIds.length) {
      setProducts([]);
      return;
    }
    api
      .get('/products/batch', { params: { ids: productIds.join(',') } })
      .then((res) => setProducts(getProductItems(res.data)))
      .catch(() => setProducts([]));
  }, [cartProducts]);

  useEffect(() => {
    const tab = new URLSearchParams(location.search).get('tab');
    setActiveTab(tab === 'orders' ? 'orders' : 'cart');
  }, [location.search]);

  useEffect(() => {
    setSelectedIds((prev) => prev.filter((id) => cartProducts.some((item) => getLineId(item) === id)));
  }, [cartProducts]);

  useEffect(() => {
    localStorage.setItem('checkoutSelection', JSON.stringify(selectedIds));
  }, [selectedIds]);

  const productMap = useMemo(() => {
    const map = new Map();
    products.forEach((p) => map.set(p._id || p.id, p));
    return map;
  }, [products]);
  const inventoryMap = useInventoryMap(products);

  const enrichedProducts = cartProducts.map((item) => {
    const product = productMap.get(item.productId);
    const variants = Array.isArray(product?.variants) ? product.variants : [];
    const selectedVariant = variants.find((variant) => String(variant._id) === String(item.variantId || ''));
    const hasVariants = variants.length > 0;
    const unitPrice = selectedVariant ? selectedVariant.price : product?.price;
    const availableQty = getAvailableStock(product, selectedVariant, inventoryMap);
    return {
      ...item,
      lineId: getLineId(item),
      name: product?.name,
      price: unitPrice,
      image: product?.images?.[0] || product?.imageUrl,
      shopId: product?.shopId,
      shopName: shopMap.get(product?.shopId)?.name || product?.shopName,
      variantName: selectedVariant?.name || (hasVariants ? 'Biến thể không khả dụng' : ''),
      availableQty,
      inStock: Number(availableQty) >= Number(item.quantity || 0)
    };
  });

  const groupedProducts = useMemo(() => {
    const groups = new Map();
    enrichedProducts.forEach((item) => {
      const key = item.shopId || item.shopName || 'unknown';
      if (!groups.has(key)) {
        groups.set(key, { shopId: item.shopId || key, shopName: item.shopName || 'Cửa hàng', items: [] });
      }
      groups.get(key).items.push(item);
    });
    return Array.from(groups.entries()).map(([, value]) => value);
  }, [enrichedProducts]);

  const selectedProducts = enrichedProducts.filter((item) => selectedIds.includes(item.lineId));
  const total = selectedProducts.reduce(
    (sum, item) => sum + Number(item?.price || 0) * Number(item?.quantity || 0),
    0
  );

  const allSelected = cartProducts.length > 0 && selectedIds.length === cartProducts.length;

  const toggleSelect = (productId) => {
    if (!productId) return;
    setSelectedIds((prev) =>
      prev.includes(productId) ? prev.filter((id) => id !== productId) : [...prev, productId]
    );
  };

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds([]);
      return;
    }
    setSelectedIds(cartProducts.map((item) => getLineId(item)));
  };

  const handleCheckout = () => {
    if (selectedIds.length === 0) {
      showToast('Vui lòng chọn ít nhất một sản phẩm để thanh toán', 'error');
      return;
    }
    const insufficient = selectedProducts.find((item) => Number(item.availableQty) < Number(item.quantity || 0));
    if (insufficient) {
      showToast(`"${insufficient.name || 'Sản phẩm'}" không đủ số lượng tồn kho`, 'error');
      return;
    }
    navigate('/checkout', { state: { selectedProductIds: selectedIds } });
  };

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    if (tab === 'orders') {
      navigate('/cart?tab=orders');
    } else {
      navigate('/cart');
    }
  };

  return (
    <div className="container page-section">
      <div className="tab-bar">
        <button
          type="button"
          className={`tab-button ${activeTab === 'cart' ? 'active' : ''}`}
          onClick={() => handleTabChange('cart')}
        >
          Giỏ hàng
        </button>
        <button
          type="button"
          className={`tab-button ${activeTab === 'orders' ? 'active' : ''}`}
          onClick={() => handleTabChange('orders')}
        >
          Đơn hàng
        </button>
      </div>

      {activeTab === 'orders' ? (
        <div className="orders-embedded">
          <Orders embedded />
        </div>
      ) : (
        <div className="cart-page">
          <div className="cart-panel">
            <div className="section-header">
              <h2>Giỏ hàng</h2>
              <span className="section-link">{cartProducts.length} sản phẩm</span>
            </div>
            {enrichedProducts.length === 0 ? (
              <div className="empty-state">
                <h3>Giỏ hàng của bạn đang trống</h3>
                <p>Hãy thêm sản phẩm để bắt đầu mua sắm.</p>
                <Link to="/products" className="btn btn-primary">Xem sản phẩm</Link>
              </div>
            ) : (
              <div className="cart-table">
                <div className="cart-select-row">
                  <label className="select-all">
                    <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} />
                    Chọn tất cả
                  </label>
                  <span className="muted">Đã chọn {selectedIds.length}</span>
                </div>
                <div className="cart-row cart-head">
                  <div className="cart-cell">Sản phẩm</div>
                  <div className="cart-cell">Giá</div>
                  <div className="cart-cell">Số lượng</div>
                  <div className="cart-cell">Tạm tính</div>
                  <div className="cart-cell">Thao tác</div>
                </div>
                {groupedProducts.map((group) => (
                  <div key={group.shopId || group.shopName} className="cart-group">
                    <div className="cart-shop-row">
                      <span>{group.shopName}</span>
                      <span className="muted">{group.items.length} sản phẩm</span>
                    </div>
                    {group.items.map((p) => (
                      <CartItem
                        key={p.lineId || p.productId || p.id}
                        item={p}
                        onRemove={removeItem}
                        onUpdate={updateItem}
                        selected={selectedIds.includes(p.lineId)}
                        onSelect={toggleSelect}
                      />
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>

          <aside className="cart-summary">
            <h3>Tóm tắt đơn hàng</h3>
            <div className="summary-row">
              <span>Tạm tính</span>
              <strong>{formatPrice(total)}</strong>
            </div>
            <div className="summary-row">
              <span>Phí vận chuyển</span>
              <strong>0</strong>
            </div>
            <div className="summary-row total">
              <span>Tổng cộng</span>
              <strong>{formatPrice(total)}</strong>
            </div>
            <button className="btn btn-primary btn-full" onClick={handleCheckout} disabled={selectedIds.length === 0}>
              Thanh toán
            </button>
          </aside>
        </div>
      )}
    </div>
  );
}
