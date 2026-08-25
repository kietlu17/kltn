import { useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useCart } from '../context/CartContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import useShopMap from '../hooks/useShopMap';
import useInventoryMap, { getAvailableStock } from '../hooks/useInventoryMap';
import { formatOrderStatus } from '../utils/statusLabels';

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
  const [walletBalance, setWalletBalance] = useState(null);
  const [walletAvailable, setWalletAvailable] = useState(false);
  const [walletLoading, setWalletLoading] = useState(false);
  const [walletError, setWalletError] = useState('');
  const [bankQrRequests, setBankQrRequests] = useState([]);
  const [vouchers, setVouchers] = useState([]);
  const [selectedVoucherCode, setSelectedVoucherCode] = useState('');
  const [voucherLoading, setVoucherLoading] = useState(false);
  const [checkoutProgress, setCheckoutProgress] = useState(null);
  const [invoiceRequested, setInvoiceRequested] = useState(false);
  const [invoiceInfo, setInvoiceInfo] = useState({
    targetType: 'company',
    buyerName: '',
    taxCode: '',
    address: '',
    email: '',
    note: ''
  });

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

  async function loadWallet({ silent = false } = {}) {
    if (!user?.id) {
      setWalletBalance(null);
      setWalletAvailable(false);
      setWalletError('');
      return { available: false, balance: null };
    }
    if (!silent) setWalletLoading(true);
    try {
      const res = await api.get(`/payments/wallet/${user.id}`);
      const balance = Number(res.data?.balance || 0);
      setWalletBalance(balance);
      setWalletAvailable(true);
      setWalletError('');
      return { available: true, balance };
    } catch {
      setWalletBalance(null);
      setWalletAvailable(false);
      setWalletError('Ví đang không khả dụng. Vui lòng chọn COD hoặc SePay QR.');
      return { available: false, balance: null };
    } finally {
      if (!silent) setWalletLoading(false);
    }
  }

  useEffect(() => {
    loadWallet();
  }, [user?.id]);

  useEffect(() => {
    if (paymentMethod === 'wallet' && walletError) {
      setPaymentMethod('cod');
      showToast('Ví đang không khả dụng. Vui lòng chọn phương thức khác.', 'error');
    }
  }, [paymentMethod, walletError, showToast]);

  const productMap = useMemo(() => {
    const map = new Map();
    products.forEach((p) => map.set(p._id || p.id, p));
    return map;
  }, [products]);
  const inventoryMap = useInventoryMap(products);

  const filteredCartProducts = useMemo(
    () => (selectedIds.length ? cartProducts.filter((item) => selectedIds.includes(getLineId(item))) : []),
    [cartProducts, selectedIds]
  );

  const enrichedProducts = useMemo(
    () =>
      filteredCartProducts.map((item) => {
        const product = productMap.get(item.productId);
        const selectedVariant = (product?.variants || []).find((variant) => String(variant._id) === String(item.variantId || ''));
        const effectivePrice = selectedVariant ? selectedVariant.price : product?.price;
        const effectiveStock = getAvailableStock(product, selectedVariant, inventoryMap);
        return {
          ...item,
          lineId: getLineId(item),
          name: product?.name,
          price: effectivePrice,
          variantName: selectedVariant?.name || '',
          shopId: product?.shopId,
          shopName: shopMap.get(product?.shopId)?.name || product?.shopName,
          availableQty: effectiveStock,
          inStock: Number(effectiveStock ?? 0) >= Number(item.quantity || 0)
        };
      }),
    [filteredCartProducts, productMap, shopMap, inventoryMap]
  );

  const hasOutOfStock = enrichedProducts.some((item) => !item.inStock);
  const invoiceShopModes = useMemo(() => {
    const modes = new Map();
    enrichedProducts.forEach((item) => {
      const shopId = item.shopId;
      if (!shopId || modes.has(shopId)) return;
      const shop = shopMap.get(shopId);
      const mode = shop?.invoiceEligible === false ? 'off' : (shop?.invoiceRequestMode || 'chat_required');
      modes.set(shopId, {
        shopId,
        shopName: shop?.name || item.shopName || 'Shop',
        mode
      });
    });
    return [...modes.values()];
  }, [enrichedProducts, shopMap]);
  const checkoutInvoiceShops = invoiceShopModes.filter((shop) => shop.mode === 'checkout_form');
  const canRequestInvoiceAtCheckout = checkoutInvoiceShops.length > 0;

  useEffect(() => {
    if (!canRequestInvoiceAtCheckout && invoiceRequested) {
      setInvoiceRequested(false);
    }
  }, [canRequestInvoiceAtCheckout, invoiceRequested]);

  useEffect(() => {
    if (hasOutOfStock) {
      showToast('Một số sản phẩm đã hết hàng. Vui lòng xóa trước khi tiếp tục.', 'error');
    }
  }, [hasOutOfStock, showToast]);

  const total = enrichedProducts.reduce(
    (sum, item) => sum + Number(item?.price || 0) * Number(item?.quantity || 0),
    0
  );
  const voucherItems = useMemo(
    () =>
      enrichedProducts
        .filter((item) => item.productId && item.shopId)
        .map((item) => ({
          productId: item.productId,
          shopId: item.shopId,
          quantity: item.quantity,
          price: item.price
        })),
    [enrichedProducts]
  );
  const selectedVoucher = vouchers.find((voucher) => voucher.code === selectedVoucherCode && voucher.eligible);
  const discountAmount = selectedVoucher ? Math.min(Number(selectedVoucher.discountAmount || 0), total) : 0;
  const payableTotal = Math.max(total - discountAmount, 0);

  function isPaidStatus(status) {
    return ['paid', 'confirmed', 'shipped', 'delivered'].includes(String(status || '').toLowerCase());
  }

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitForPaidOrders(orderIds) {
    for (let attempt = 0; attempt < 15; attempt += 1) {
      const res = await api.get(`/orders/${user.id}`);
      const rows = Array.isArray(res.data) ? res.data : [];
      const statusById = new Map(rows.map((row) => [Number(row.id || row._id), row.status]));
      const allPaid = orderIds.every((id) => isPaidStatus(statusById.get(Number(id))));
      if (allPaid) return true;
      await delay(1000);
    }
    return false;
  }

  function buildInvoiceRequest() {
    if (!invoiceRequested) return null;
    return {
      requested: true,
      targetType: invoiceInfo.targetType,
      buyerName: invoiceInfo.buyerName.trim(),
      taxCode: invoiceInfo.taxCode.trim(),
      address: invoiceInfo.address.trim(),
      email: invoiceInfo.email.trim(),
      note: invoiceInfo.note.trim(),
      priceIncludesVat: true
    };
  }

  useEffect(() => {
    if (!user?.id || bankQrRequests.length === 0) return undefined;
    const orderIds = bankQrRequests.map((item) => Number(item.orderId)).filter((id) => Number.isFinite(id));
    if (!orderIds.length) return undefined;

    let timer;
    async function checkOrderPayments() {
      try {
        const res = await api.get(`/orders/${user.id}`);
        const rows = Array.isArray(res.data) ? res.data : [];
        const statusById = new Map(rows.map((row) => [Number(row.id || row._id), row.status]));
        setBankQrRequests((prev) =>
          prev.map((item) => ({
            ...item,
            orderStatus: statusById.get(Number(item.orderId)) || item.orderStatus || 'pending_payment'
          }))
        );
        const allPaid = orderIds.every((id) => isPaidStatus(statusById.get(id)));
        if (allPaid) {
          setBankQrRequests([]);
          showToast('Thanh toán SePay thành công. Đơn hàng đã được ghi nhận.');
          navigate('/orders');
          return;
        }
      } catch {
        // no-op
      }
      timer = setTimeout(checkOrderPayments, 3000);
    }

    checkOrderPayments();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [bankQrRequests.length, user?.id, showToast, navigate]);

  useEffect(() => {
    if (!user?.id || voucherItems.length === 0) {
      setVouchers([]);
      setSelectedVoucherCode('');
      return;
    }
    let cancelled = false;
    setVoucherLoading(true);
    api
      .post('/vouchers/checkout', { userId: user.id, items: voucherItems })
      .then((res) => {
        if (cancelled) return;
        const rows = Array.isArray(res.data) ? res.data : [];
        setVouchers(rows);
        setSelectedVoucherCode((current) => {
          if (current && rows.some((voucher) => voucher.code === current && voucher.eligible)) return current;
          return '';
        });
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
  }, [user?.id, voucherItems]);

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
    if (invoiceRequested && !canRequestInvoiceAtCheckout) {
      showToast('Các shop đã chọn đang nhận yêu cầu hóa đơn qua chat', 'error');
      return;
    }
    if (paymentMethod === 'wallet') {
      if (!walletAvailable) {
        showToast('Ví đang không khả dụng. Vui lòng chọn COD hoặc SePay QR.', 'error');
        return;
      }
      const walletState = await loadWallet({ silent: true });
      if (!walletState.available) {
        showToast('Ví đang không khả dụng. Đơn hàng chưa được tạo, vui lòng chọn phương thức khác.', 'error');
        return;
      }
      if (payableTotal > Number(walletState.balance || 0)) {
        showToast('Số dư ví không đủ. Vui lòng nạp thêm tiền.', 'error');
        return;
      }
    }
    const invoiceRequest = buildInvoiceRequest();
    if (invoiceRequest) {
      if (!invoiceRequest.buyerName || !invoiceRequest.address || !invoiceRequest.email) {
        showToast('Vui lòng nhập đủ tên, địa chỉ và email nhận hóa đơn', 'error');
        return;
      }
      if (invoiceRequest.targetType !== 'personal' && !invoiceRequest.taxCode) {
        showToast('Vui lòng nhập mã số thuế để xuất hóa đơn công ty/hộ kinh doanh', 'error');
        return;
      }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(invoiceRequest.email)) {
        showToast('Email nhận hóa đơn không hợp lệ', 'error');
        return;
      }
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
      const availableQty = getAvailableStock(product, selectedVariant, inventoryMap);
      if (Number(availableQty) < Number(p.quantity || 0)) {
        showToast(`"${product?.name || 'Sản phẩm'}" không đủ số lượng tồn kho`, 'error');
        return;
      }
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
    if (selectedVoucher?.type === 'platform' && ordersByShop.size > 1) {
      showToast('Mã của sàn hiện chỉ áp dụng khi các sản phẩm được tạo trong cùng một đơn hàng', 'error');
      return;
    }

    const userId = user.id;
    const selectedAddress = addresses.find(
      (address) => String(address._id || address.id) === String(selectedAddressId)
    );

    setCheckoutProgress({ step: 'creating', label: 'Đang tạo đơn hàng' });
    const createdOrders = [];
    try {
      for (const [shopId, items] of ordersByShop.entries()) {
        const shopInvoiceMode = invoiceShopModes.find((shop) => String(shop.shopId) === String(shopId))?.mode || 'chat_required';
        const shouldApplyVoucher =
          selectedVoucher &&
          (
            selectedVoucher.type === 'platform' ||
            String(selectedVoucher.shopId) === String(shopId)
          );
        const created = await api.post('/orders', {
          userId,
          products: items,
          shippingAddress: selectedAddress,
          paymentMethod,
          voucherCode: shouldApplyVoucher ? selectedVoucher.code : null,
          invoiceRequest: shopInvoiceMode === 'checkout_form' ? invoiceRequest : null
        });
        createdOrders.push(created.data);
      }
    } catch (err) {
      const message = err?.response?.data?.message || 'Đặt hàng thất bại';
      showToast(message, 'error');
      setCheckoutProgress(null);
      return;
    }

    setCheckoutProgress({ step: 'cleaning', label: 'Đang cập nhật giỏ hàng' });
    await Promise.all(
      checkoutProducts.map((item) =>
        api.post('/cart/remove', { userId, productId: item.productId, variantId: item.variantId || null })
      )
    );

    if (user?.id) {
      try {
        await loadWallet({ silent: true });
      } catch {
        // no-op
      }
    }

    localStorage.removeItem('checkoutSelection');
    await refreshCart();

    if (paymentMethod === 'bank_transfer') {
      try {
        const qrResponses = [];
        for (const order of createdOrders) {
          const orderId = Number(order?.id || order?._id);
        const amount = Number(order?.total_price || order?.totalPrice || 0);
          if (!Number.isFinite(orderId) || !Number.isFinite(amount) || amount <= 0) continue;
          const qr = await api.post(`/payments/sepay/orders/${orderId}/qr`, {
            userId,
            amount
          });
          qrResponses.push({
            ...qr.data,
            orderId,
            orderStatus: order?.status || 'pending_payment'
          });
        }
        if (qrResponses.length === 0) {
          showToast('Không thể tạo mã QR thanh toán cho đơn hàng', 'error');
          navigate('/orders');
          return;
        }
        setBankQrRequests(qrResponses);
        showToast('Đơn hàng đã tạo. Vui lòng quét QR SePay để thanh toán.');
        setCheckoutProgress(null);
        return;
      } catch (err) {
        showToast(err?.response?.data?.message || 'Không thể tạo QR SePay cho đơn hàng', 'error');
        navigate('/orders');
        setCheckoutProgress(null);
        return;
      }
    }

    if (paymentMethod === 'wallet') {
      setCheckoutProgress({ step: 'wallet', label: 'Đang xác nhận thanh toán ví' });
      try {
        const orderIds = createdOrders.map((order) => Number(order?.id || order?._id)).filter((id) => Number.isFinite(id));
        const paid = await waitForPaidOrders(orderIds);
        showToast(paid ? 'Thanh toán ví thành công. Đơn hàng đã được ghi nhận.' : 'Đơn hàng đang xử lý thanh toán ví.');
      } catch {
        showToast('Đơn hàng đang xử lý thanh toán ví.');
      }
      setCheckoutProgress(null);
      navigate('/orders');
      return;
    }

    setCheckoutProgress(null);
    showToast('Đặt hàng thành công');
    navigate('/orders');
  }

  return (
    <div className="container page-section checkout-page">
      {checkoutProgress && (
        <div className="checkout-processing" role="status" aria-live="polite">
          <div className="checkout-spinner" />
          <div>
            <strong>{checkoutProgress.label}</strong>
            <span>Vui lòng giữ trang trong giây lát.</span>
          </div>
        </div>
      )}
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

        {canRequestInvoiceAtCheckout && (
          <div className="checkout-section invoice-box">
            <label className="checkbox-field invoice-toggle">
              <input
                type="checkbox"
                checked={invoiceRequested}
                onChange={(event) => setInvoiceRequested(event.target.checked)}
              />
              Yêu cầu hóa đơn điện tử
            </label>
            <div className="muted">
              Form này áp dụng cho: {checkoutInvoiceShops.map((shop) => shop.shopName).join(', ')}
            </div>
            {invoiceRequested && (
              <div className="invoice-form">
                <div className="invoice-price-note">
                  Giá sản phẩm hiển thị đã bao gồm VAT nếu hàng hóa thuộc diện chịu thuế.
                </div>
                <div className="form-grid">
                  <div>
                    <label>Đối tượng nhận hóa đơn</label>
                    <select
                      value={invoiceInfo.targetType}
                      onChange={(event) =>
                        setInvoiceInfo((prev) => ({ ...prev, targetType: event.target.value }))
                      }
                    >
                      <option value="company">Công ty</option>
                      <option value="business_household">Hộ kinh doanh</option>
                      <option value="personal">Cá nhân</option>
                    </select>
                  </div>
                  <div>
                    <label>Email nhận hóa đơn</label>
                    <input
                      value={invoiceInfo.email}
                      onChange={(event) => setInvoiceInfo((prev) => ({ ...prev, email: event.target.value }))}
                      placeholder="billing@example.com"
                    />
                  </div>
                </div>
                <div className="form-grid">
                  <div>
                    <label>Tên công ty/cá nhân</label>
                    <input
                      value={invoiceInfo.buyerName}
                      onChange={(event) => setInvoiceInfo((prev) => ({ ...prev, buyerName: event.target.value }))}
                      placeholder="Tên trên hóa đơn"
                    />
                  </div>
                  <div>
                    <label>Mã số thuế</label>
                    <input
                      value={invoiceInfo.taxCode}
                      onChange={(event) => setInvoiceInfo((prev) => ({ ...prev, taxCode: event.target.value }))}
                      placeholder={invoiceInfo.targetType === 'personal' ? 'Không bắt buộc' : 'Bắt buộc'}
                    />
                  </div>
                </div>
                <div>
                  <label>Địa chỉ xuất hóa đơn</label>
                  <input
                    value={invoiceInfo.address}
                    onChange={(event) => setInvoiceInfo((prev) => ({ ...prev, address: event.target.value }))}
                    placeholder="Địa chỉ theo thông tin thuế"
                  />
                </div>
                <div>
                  <label>Ghi chú cho shop</label>
                  <textarea
                    value={invoiceInfo.note}
                    onChange={(event) => setInvoiceInfo((prev) => ({ ...prev, note: event.target.value }))}
                    placeholder="Ví dụ: vui lòng xuất hóa đơn sau khi đơn hoàn tất"
                  />
                </div>
              </div>
            )}
          </div>
        )}

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
        {discountAmount > 0 && (
          <>
            <div className="checkout-total checkout-discount">
              <span>Mã giảm giá</span>
              <strong>-{formatPrice(discountAmount)}</strong>
            </div>
            <div className="checkout-total">
              <span>Cần thanh toán</span>
              <strong>{formatPrice(payableTotal)}</strong>
            </div>
          </>
        )}

        <button
          className="btn btn-primary btn-full"
          onClick={checkout}
          disabled={
            hasOutOfStock ||
            selectedIds.length === 0 ||
            Boolean(checkoutProgress) ||
            (paymentMethod === 'wallet' && (walletLoading || !walletAvailable))
          }
        >
          {checkoutProgress ? 'Đang xử lý...' : 'Đặt hàng'}
        </button>
      </div>

      <div className="card checkout-card">
        <h3>Thanh toán</h3>
        <p className="muted">Hỗ trợ thanh toán ví và SePay QR.</p>
        <div className="muted">
          Số dư ví: <strong>{walletLoading ? 'Đang tải...' : (walletAvailable ? formatPrice(walletBalance) : 'Ví đang không khả dụng')}</strong>
        </div>
        {walletError && <div className="muted">{walletError}</div>}
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
            Chuyển khoản ngân hàng qua SePay QR
          </label>
          <label className={`radio-field ${!walletAvailable ? 'disabled' : ''}`}>
            <input
              type="radio"
              name="payment"
              value="wallet"
              checked={paymentMethod === 'wallet'}
              disabled={walletLoading || !walletAvailable}
              onChange={(event) => setPaymentMethod(event.target.value)}
            />
            Ví {!walletAvailable && !walletLoading ? '(đang không khả dụng)' : ''}
          </label>
        </div>
        <div className="voucher-picker">
          <div className="voucher-picker-head">
            <strong>Mã giảm giá</strong>
            <span className="muted">{voucherLoading ? 'Đang tải...' : `${vouchers.length} mã`}</span>
          </div>
          {vouchers.length === 0 ? (
            <div className="muted">Chưa có mã phù hợp với giỏ hàng.</div>
          ) : (
            vouchers.map((voucher) => (
              <label key={voucher.id} className={`voucher-option ${!voucher.eligible ? 'disabled' : ''}`}>
                <input
                  type="radio"
                  name="voucher"
                  value={voucher.code}
                  checked={selectedVoucherCode === voucher.code}
                  disabled={!voucher.eligible}
                  onChange={(event) => setSelectedVoucherCode(event.target.value)}
                />
                <span>
                  <strong>{voucher.code}</strong>
                  <small>
                    {voucher.type === 'shop' ? 'Shop' : 'Sàn'} - giảm {Number(voucher.discountValue || 0)}%
                    {Number(voucher.maxDiscountAmount || 0) > 0 ? ` tối đa ${formatPrice(voucher.maxDiscountAmount)}` : ''}
                  </small>
                  {!voucher.eligible && <small>{voucher.reason}</small>}
                </span>
                <b>{voucher.eligible ? `-${formatPrice(voucher.discountAmount)}` : 'Không áp dụng'}</b>
              </label>
            ))
          )}
          {selectedVoucherCode && (
            <button type="button" className="btn btn-ghost btn-full" onClick={() => setSelectedVoucherCode('')}>
              Bỏ chọn mã
            </button>
          )}
        </div>

        {bankQrRequests.length > 0 && (
          <div className="sepay-qr-box">
            <div className="sepay-qr-head">
              <strong>Thanh toán đơn hàng bằng SePay</strong>
              <button className="btn btn-ghost" onClick={() => navigate('/orders')}>
                Xem đơn hàng
              </button>
            </div>
            {bankQrRequests.map((item) => (
              <div key={`${item.id}-${item.orderId}`} className="sepay-qr-order">
                <div className="sepay-qr-grid">
                  <img src={item.qrUrl} alt={`SePay QR order ${item.orderId}`} />
                  <div className="sepay-qr-meta">
                    <div><span className="muted">Đơn hàng</span><strong>#{item.orderId}</strong></div>
                    <div><span className="muted">Số tiền</span><strong>{formatPrice(item.amount)}</strong></div>
                    <div><span className="muted">Ngân hàng</span><strong>{item.bankCode}</strong></div>
                    <div><span className="muted">Tài khoản</span><strong>{item.accountNumber}</strong></div>
                    <div><span className="muted">Nội dung</span><strong>{item.requestCode}</strong></div>
                    <div>
                      <span className="muted">Trạng thái đơn</span>
                      <strong>{formatOrderStatus(item.orderStatus || 'pending_payment')}</strong>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
