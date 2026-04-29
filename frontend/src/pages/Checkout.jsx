import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useCart } from '../context/CartContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import useShopMap from '../hooks/useShopMap';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

function getLineId(item) {
  return `${item?.productId || ''}::${item?.variantId || ''}`;
}

export default function Checkout() {
  const { cartProducts, refreshCart } = useCart();
  const { showToast } = useToast();
  const { user } = useAuth();
  const shopMap = useShopMap();
  const location = useLocation();
  const navigate = useNavigate();

  const [selectedIds, setSelectedIds] = useState(() => {
    const stateIds = location.state?.selectedProductIds;
    if (Array.isArray(stateIds)) return stateIds;
    try {
      const stored = JSON.parse(localStorage.getItem('checkoutSelection') || '[]');
      return Array.isArray(stored) ? stored : [];
    } catch {
      return [];
    }
  });

  const [products, setProducts] = useState([]);
  const [addresses, setAddresses] = useState([]);
  const [selectedAddressId, setSelectedAddressId] = useState('');
  const [paymentMethod, setPaymentMethod] = useState('cod');
  const [walletBalance, setWalletBalance] = useState(0);
  const [walletLoading, setWalletLoading] = useState(false);

  useEffect(() => {
    refreshCart();
    api.get('/products').then((res) => setProducts(res.data)).catch(() => setProducts([]));
  }, [refreshCart]);

  useEffect(() => {
    const stateIds = location.state?.selectedProductIds;
    if (Array.isArray(stateIds)) {
      setSelectedIds(stateIds);
      localStorage.setItem('checkoutSelection', JSON.stringify(stateIds));
    }
  }, [location.state]);

  useEffect(() => {
    if (!user?.id) {
      setAddresses([]);
      setSelectedAddressId('');
      return;
    }

    api
      .get(`/users/${user.id}/addresses`)
      .then((res) => {
        const data = res.data || [];
        setAddresses(data);
        const defaultAddress = data.find((item) => item.isDefault);
        setSelectedAddressId(defaultAddress?._id || defaultAddress?.id || '');
      })
      .catch(() => setAddresses([]));
  }, [user]);

  useEffect(() => {
    if (!user?.id) {
      setWalletBalance(0);
      return;
    }
    setWalletLoading(true);
    api
      .get(`/payments/wallet/${user.id}`)
      .then((res) => setWalletBalance(Number(res.data?.balance || 0)))
      .catch(() => setWalletBalance(0))
      .finally(() => setWalletLoading(false));
  }, [user?.id]);

  const productMap = useMemo(() => {
    const map = new Map();
    products.forEach((p) => map.set(p._id || p.id, p));
    return map;
  }, [products]);

  const filteredCartProducts = selectedIds.length
    ? cartProducts.filter((item) => selectedIds.includes(getLineId(item)))
    : [];

  const enrichedProducts = filteredCartProducts.map((item) => {
    const product = productMap.get(item.productId);
    const selectedVariant = (product?.variants || []).find((variant) => String(variant._id) === String(item.variantId || ''));
    const effectivePrice = selectedVariant ? selectedVariant.price : product?.price;
    const effectiveStock = selectedVariant ? selectedVariant.quantity : product?.quantity;
    return {
      ...item,
      lineId: getLineId(item),
      name: product?.name,
      price: effectivePrice,
      variantName: selectedVariant?.name || '',
      shopName: shopMap.get(product?.shopId)?.name || product?.shopName,
      inStock: Number(effectiveStock ?? 0) > 0
    };
  });

  const hasOutOfStock = enrichedProducts.some((item) => !item.inStock);

  useEffect(() => {
    if (hasOutOfStock) {
      showToast('Một số sản phẩm đã hết hàng. Vui lòng xóa trước khi tiếp tục.', 'error');
    }
  }, [hasOutOfStock, showToast]);

  const total = enrichedProducts.reduce(
    (sum, item) => sum + Number(item?.price || 0) * Number(item?.quantity || 0),
    0
  );

  async function checkout() {
    if (!user?.id) {
      showToast('Vui lòng đăng nhập để tiếp tục thanh toán', 'error');
      navigate('/login');
      return;
    }
    if (selectedIds.length === 0) {
      showToast('Chưa có sản phẩm nào được chọn để thanh toán', 'error');
      return;
    }
    if (hasOutOfStock) {
      showToast('Một số sản phẩm đã hết hàng. Vui lòng xóa trước khi tiếp tục.', 'error');
      return;
    }
    if (!selectedAddressId) {
      showToast('Vui lòng chọn địa chỉ giao hàng', 'error');
      return;
    }
    if (!paymentMethod) {
      showToast('Vui lòng chọn phương thức thanh toán', 'error');
      return;
    }
    if (paymentMethod === 'wallet' && total > walletBalance) {
      showToast('Số dư ví không đủ. Vui lòng nạp thêm tiền.', 'error');
      return;
    }

    const checkoutProducts = cartProducts.filter((item) => selectedIds.includes(getLineId(item)));
    const orderProducts = [];

    for (const p of checkoutProducts) {
      const product = productMap.get(p.productId);
      const variants = Array.isArray(product?.variants) ? product.variants : [];
      const hasVariants = variants.length > 0;

      if (hasVariants && !p.variantId) {
        showToast(`Vui lòng thêm lại "${product?.name || 'sản phẩm'}" và chọn biến thể`, 'error');
        return;
      }

      const selectedVariant = variants.find((item) => String(item._id) === String(p.variantId || ''));
      if (hasVariants && !selectedVariant) {
        showToast(`Biến thể đã chọn của "${product?.name || 'sản phẩm'}" không còn khả dụng`, 'error');
        return;
      }

      const linePrice = selectedVariant ? selectedVariant.price : (product?.price || 0);
      orderProducts.push({
        productId: p.productId,
        variantId: p.variantId || null,
        variantName: selectedVariant?.name || null,
        quantity: p.quantity,
        price: linePrice,
        shopId: product?.shopId,
        productName: product?.name
      });
    }

    const missingShop = orderProducts.some((item) => !item.shopId);
    if (missingShop) {
      showToast('Một số sản phẩm thiếu thông tin cửa hàng', 'error');
      return;
    }

    const ordersByShop = new Map();
    orderProducts.forEach((item) => {
      const key = item.shopId;
      if (!ordersByShop.has(key)) ordersByShop.set(key, []);
      ordersByShop.get(key).push(item);
    });

    const userId = user.id;
    const selectedAddress = addresses.find(
      (address) => String(address._id || address.id) === String(selectedAddressId)
    );

    try {
      for (const [, items] of ordersByShop.entries()) {
        await api.post('/orders', {
          userId,
          products: items,
          shippingAddress: selectedAddress,
          paymentMethod
        });
      }
    } catch (err) {
      const message = err?.response?.data?.message || 'Đặt hàng thất bại';
      showToast(message, 'error');
      return;
    }

    await Promise.all(
      checkoutProducts.map((item) =>
        api.post('/cart/remove', { userId, productId: item.productId, variantId: item.variantId || null })
      )
    );

    if (user?.id) {
      try {
        const wallet = await api.get(`/payments/wallet/${user.id}`);
        setWalletBalance(Number(wallet.data?.balance || 0));
      } catch {
        // no-op
      }
    }

    localStorage.removeItem('checkoutSelection');
    await refreshCart();
    showToast(paymentMethod === 'wallet' ? 'Đặt hàng thành công. Đã thanh toán bằng ví.' : 'Đặt hàng thành công');
    navigate('/cart?tab=orders');
  }

  return (
    <div className="container page-section checkout-page">
      <div className="card checkout-card">
        <h2>Thanh toán</h2>
        <div className="checkout-section">
          <h4>Địa chỉ giao hàng</h4>
          {addresses.length === 0 ? (
            <div className="muted">
              Chưa có địa chỉ. <Link to="/addresses">Thêm địa chỉ giao hàng</Link>
            </div>
          ) : (
            <select value={selectedAddressId} onChange={(event) => setSelectedAddressId(event.target.value)}>
              <option value="">Chọn địa chỉ</option>
              {addresses.map((address) => (
                <option key={address._id || address.id} value={address._id || address.id}>
                  {[address.label, address.line1, address.city].filter(Boolean).join(' - ')}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="checkout-items">
          {enrichedProducts.length === 0 ? (
            <div className="muted">Chưa có sản phẩm được chọn để thanh toán.</div>
          ) : (
            enrichedProducts.map((item) => (
              <div key={item.lineId || item.productId} className="checkout-row">
                <span>
                  {item.name || 'Sản phẩm chưa đặt tên'}
                  {item.variantName ? ` (${item.variantName})` : ''}
                  {!item.inStock && <span className="stock-inline">Hết hàng</span>}
                </span>
                <span>x{item.quantity}</span>
              </div>
            ))
          )}
        </div>

        <div className="checkout-total">
          <span>Tổng cộng</span>
          <strong>{formatPrice(total)}</strong>
        </div>

        <button className="btn btn-primary btn-full" onClick={checkout} disabled={hasOutOfStock || selectedIds.length === 0}>
          Đặt hàng
        </button>
      </div>

      <div className="card checkout-card">
        <h3>Thanh toán</h3>
        <p className="muted">Mô phỏng thanh toán trong bản demo.</p>
        <div className="muted">
          Số dư ví: <strong>{walletLoading ? 'Đang tải...' : formatPrice(walletBalance)}</strong>
        </div>
        <div className="payment-options">
          <label className="radio-field">
            <input
              type="radio"
              name="payment"
              value="cod"
              checked={paymentMethod === 'cod'}
              onChange={(event) => setPaymentMethod(event.target.value)}
            />
            Thanh toán khi nhận hàng
          </label>
          <label className="radio-field">
            <input
              type="radio"
              name="payment"
              value="bank_transfer"
              checked={paymentMethod === 'bank_transfer'}
              onChange={(event) => setPaymentMethod(event.target.value)}
            />
            Chuyển khoản ngân hàng (thủ công)
          </label>
          <label className="radio-field">
            <input
              type="radio"
              name="payment"
              value="wallet"
              checked={paymentMethod === 'wallet'}
              onChange={(event) => setPaymentMethod(event.target.value)}
            />
            Ví
          </label>
        </div>
        <button className="btn btn-outline btn-full">Áp dụng mã giảm giá</button>
      </div>
    </div>
  );
}
