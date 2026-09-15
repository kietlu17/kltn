import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Hls from 'hls.js';
import api, { resolveImageUrl } from '../services/api';
import { createLiveSocket } from '../services/realtime';
import { useAuth } from '../context/AuthContext.jsx';
import { useCart } from '../context/CartContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

function getVariantId(variant) {
  return variant?._id || variant?.id || variant?.variantId || '';
}

function getVariantStock(variant) {
  return Number(variant?.quantity ?? variant?.stock ?? variant?.stockSnapshot ?? 0);
}

function getAvailableVariants(product) {
  return (Array.isArray(product?.variants) ? product.variants : [])
    .map((variant) => ({
      ...variant,
      variantId: getVariantId(variant),
      stock: getVariantStock(variant)
    }))
    .filter((variant) => variant.variantId && variant.stock > 0);
}

function getHlsViewerId() {
  const key = 'live:hls-viewer-id';
  const nextId = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  try {
    const existing = localStorage.getItem(key);
    if (existing) return existing;
    localStorage.setItem(key, nextId);
  } catch {
    return nextId;
  }
  return nextId;
}

export default function BuyerLiveRoom() {
  const { liveId } = useParams();
  const { user } = useAuth();
  const { addItem, refreshCart } = useCart();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const videoRef = useRef(null);
  const socketRef = useRef(null);
  const hlsRef = useRef(null);
  const viewerIdRef = useRef(getHlsViewerId());

  const [live, setLive] = useState(null);
  const [pinnedProducts, setPinnedProducts] = useState([]);
  const [viewerCount, setViewerCount] = useState(0);
  const [chatPresenceCount, setChatPresenceCount] = useState(0);
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [connectError, setConnectError] = useState('');
  const [activeProductDetail, setActiveProductDetail] = useState(null);
  const [variantPicker, setVariantPicker] = useState(null);
  const [selectedVariantId, setSelectedVariantId] = useState('');

  const activeProduct = useMemo(
    () => pinnedProducts.find((item) => item.isActive) || pinnedProducts[0] || null,
    [pinnedProducts]
  );
  const hlsPlaybackUrl = live?.hlsPlaybackUrl || live?.playbackUrl || '';

  async function loadLive() {
    const [liveRes, pinnedRes] = await Promise.all([
      api.get(`/lives/${liveId}`),
      api.get(`/lives/${liveId}/pinned-products`)
    ]);
    setLive(liveRes.data || null);
    setPinnedProducts(pinnedRes.data || []);
  }

  useEffect(() => {
    loadLive().catch(() => {
      showToast('Không thể tải phòng live', 'error');
    });
  }, [liveId]);

  useEffect(() => {
    let active = true;
    if (!activeProduct?.productId) {
      setActiveProductDetail(null);
      return undefined;
    }
    api.get(`/products/${activeProduct.productId}`)
      .then((res) => {
        if (active) setActiveProductDetail(res.data || null);
      })
      .catch(() => {
        if (active) setActiveProductDetail(null);
      });
    return () => {
      active = false;
    };
  }, [activeProduct?.productId]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !hlsPlaybackUrl) return undefined;

    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    video.srcObject = null;
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = hlsPlaybackUrl;
      video.play().catch(() => {});
      return () => {
        video.removeAttribute('src');
        video.load();
      };
    }

    if (Hls.isSupported()) {
      const hls = new Hls({
        lowLatencyMode: true,
        backBufferLength: 30
      });
      hlsRef.current = hls;
      hls.loadSource(hlsPlaybackUrl);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {});
      });
      return () => {
        hls.destroy();
        hlsRef.current = null;
      };
    }

    return undefined;
  }, [hlsPlaybackUrl]);

  function handleLiveEvent(data) {
    if (!data?.type) return;

    if (data.type === 'live.chat.message' || data.type === 'live.intent.detected') {
      setChatMessages((prev) => [...prev.slice(-80), data]);
    }
    if (data.type === 'live.intent.variant_required' && (!data.buyerId || data.buyerId === user?.id)) {
      setChatMessages((prev) => [...prev.slice(-80), data]);
      setVariantPicker({
        source: 'ai',
        productId: data.productId,
        productName: data.productName,
        quantity: data.quantity || 1,
        variants: data.variantOptions || [],
        buyNow: false
      });
      setSelectedVariantId(data.variantOptions?.[0]?.variantId || '');
    }
    if (data.type === 'live.product.active_changed') {
      loadLive().catch(() => {});
    }
    if (data.type === 'live.cart.item_added' && (!data.buyerId || data.buyerId === user?.id)) {
      showToast('Đã thêm sản phẩm từ live vào giỏ hàng');
      refreshCart?.();
    }
    if (data.type === 'live.cart.item_add_failed' && (!data.buyerId || data.buyerId === user?.id)) {
      showToast(data.reply || 'Không thể thêm sản phẩm vào giỏ hàng', 'error');
    }
    if (data.type === 'live.ai.error') {
      showToast(data.message || 'Trợ lý AI chưa xử lý được tin nhắn', 'error');
    }
  }

  function connectRealtime() {
    if (!liveId || socketRef.current?.connected) return;
    if (!user?.id) {
      setConnectError('Vui lòng đăng nhập để chat trong live');
      return;
    }

    setConnecting(true);
    setConnectError('');
    const socket = createLiveSocket(liveId);
    socketRef.current = socket;

    socket.on('connect', () => {
      setConnected(true);
      setConnecting(false);
      setConnectError('');
    });
    socket.on('connect_error', (err) => {
      const message = err?.message || 'Không thể kết nối chat live';
      setConnected(false);
      setConnecting(false);
      setConnectError(message);
    });
    socket.on('disconnect', () => {
      setConnected(false);
    });
    socket.on('live:event', handleLiveEvent);
    socket.on('live:presence', (payload) => {
      setChatPresenceCount(Number(payload?.viewerCount || 0));
    });
  }

  useEffect(() => {
    connectRealtime();
    return () => {
      if (socketRef.current) {
        socketRef.current.disconnect();
        socketRef.current = null;
      }
    };
  }, [liveId, user?.id]);

  useEffect(() => () => {
    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!liveId || !hlsPlaybackUrl) return undefined;
    let disposed = false;

    async function sendHeartbeat() {
      try {
        const response = await api.post(`/lives/${liveId}/viewer-heartbeat`, {
          viewerId: viewerIdRef.current
        });
        if (!disposed) {
          setViewerCount(Number(response.data?.viewerCount || 0));
        }
      } catch {
        if (!disposed) setViewerCount((prev) => prev || 0);
      }
    }

    sendHeartbeat();
    const interval = window.setInterval(sendHeartbeat, 20000);
    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, [liveId, hlsPlaybackUrl]);

  function sendChatMessage() {
    const text = chatInput.trim();
    if (!text || !socketRef.current || !connected) return;
    const payload = {
      id: `msg-${Date.now()}`,
      liveId,
      shopId: live?.shopId,
      senderName: user?.email || 'Người mua',
      text,
      activePinnedProductId: activeProduct?.productId || live?.activePinnedProductId || null
    };
    socketRef.current.emit('live:chat:send', payload, (ack) => {
      if (!ack?.ok) {
        showToast(ack?.message || 'Không thể gửi chat live', 'error');
        return;
      }
      setChatInput('');
    });
  }

  async function loadProductDetail(productId) {
    if (activeProductDetail && String(activeProductDetail._id || activeProductDetail.id) === String(productId)) {
      return activeProductDetail;
    }
    const response = await api.get(`/products/${productId}`);
    setActiveProductDetail(response.data || null);
    return response.data || null;
  }

  function openVariantPicker({ product, productDetail, quantity = 1, buyNow = false, variants = null, source = 'button' }) {
    const options = variants || getAvailableVariants(productDetail);
    setVariantPicker({
      source,
      productId: product?.productId || productDetail?._id || productDetail?.id,
      productName: product?.nameSnapshot || productDetail?.name || 'Sản phẩm',
      quantity,
      variants: options,
      buyNow
    });
    setSelectedVariantId(options?.[0]?.variantId || '');
  }

  async function confirmVariantSelection() {
    if (!variantPicker?.productId || !selectedVariantId) {
      showToast('Vui lòng chọn biến thể', 'error');
      return;
    }
    const selectedVariant = variantPicker.variants.find((variant) => String(variant.variantId) === String(selectedVariantId));
    if (!selectedVariant || Number(selectedVariant.stock ?? 0) <= 0) {
      showToast('Biến thể đã hết hàng', 'error');
      return;
    }
    try {
      await addItem(variantPicker.productId, variantPicker.quantity || 1, selectedVariantId);
      showToast(`Đã thêm ${variantPicker.productName} (${selectedVariant.name}) vào giỏ hàng`);
      setVariantPicker(null);
      setSelectedVariantId('');
      if (variantPicker.buyNow) navigate('/cart');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể thêm biến thể vào giỏ hàng', 'error');
    }
  }

  async function addPinnedProductToCart(product, options = {}) {
    if (!product) return false;
    if (!user?.id || user.role !== 'buyer') {
      showToast('Vui lòng đăng nhập để mua sản phẩm trong live', 'error');
      navigate('/login');
      return false;
    }
    if (Number(product.stockSnapshot ?? 0) <= 0) {
      showToast('Sản phẩm đang hết hàng', 'error');
      return false;
    }
    try {
      const productDetail = await loadProductDetail(product.productId);
      const variants = getAvailableVariants(productDetail);
      if (Array.isArray(productDetail?.variants) && productDetail.variants.length > 0) {
        if (variants.length === 0) {
          showToast('Các biến thể đang hết hàng', 'error');
          return false;
        }
        if (variants.length > 1) {
          openVariantPicker({ product, productDetail, variants, buyNow: Boolean(options.buyNow) });
          return false;
        }
        await addItem(product.productId, 1, variants[0].variantId);
      } else {
        await addItem(product.productId, 1);
      }
      showToast(options.buyNow ? 'Đã thêm sản phẩm, chuyển sang giỏ hàng' : 'Đã thêm vào giỏ hàng');
      if (options.buyNow) navigate('/cart');
      return true;
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể thêm sản phẩm vào giỏ', 'error');
      return false;
    }
  }

  return (
    <div className="container page-section buyer-live-room">
      <div className="section-header">
        <h2>{live?.title || 'Livestream'}</h2>
        <span className="section-link">{viewerCount || chatPresenceCount} người xem</span>
      </div>

      <div className="live-room-layout">
        <section className="live-watch-surface">
          <div className="live-video-frame buyer">
            <video ref={videoRef} autoPlay playsInline controls muted={false} />
            {hlsPlaybackUrl ? <span className="live-playback-badge">HLS/CDN</span> : null}
            {!hlsPlaybackUrl ? (
              <div className="live-watch-status">
                <span>Luồng HLS chưa sẵn sàng, vui lòng chờ shop bắt đầu phát.</span>
              </div>
            ) : null}
          </div>
        </section>

        <aside className="live-side-panel">
          <div className="card">
            <h3>Sản phẩm đang ghim</h3>
            {activeProduct ? (
              <div className="live-active-product">
                {activeProduct.imageSnapshot ? <img src={resolveImageUrl(activeProduct.imageSnapshot)} alt={activeProduct.nameSnapshot} /> : <div />}
                <strong>{activeProduct.nameSnapshot}</strong>
                <span>{formatPrice(activeProduct.priceSnapshot)}</span>
                <span className="muted">Tồn {activeProduct.stockSnapshot}</span>
                <div className="live-product-actions">
                  <button
                    type="button"
                    className="btn btn-outline live-add-button"
                    onClick={() => addPinnedProductToCart(activeProduct)}
                    aria-label="Thêm vào giỏ hàng"
                    title="Thêm vào giỏ hàng"
                  >
                    +
                  </button>
                  <button type="button" className="btn btn-primary" onClick={() => addPinnedProductToCart(activeProduct, { buyNow: true })}>
                    Mua ngay
                  </button>
                </div>
              </div>
            ) : (
              <p className="muted">Cửa hàng chưa ghim sản phẩm.</p>
            )}
          </div>

          <div className="card">
            <h3>Trò chuyện live</h3>
            <div className="live-chat-list">
              {chatMessages.length === 0 ? (
                <p className="muted">Chưa có tin nhắn.</p>
              ) : (
                chatMessages.map((msg, index) => (
                  <div key={msg.id || `${msg.senderId}-${index}`} className="live-chat-line">
                    <strong>{msg.senderName || msg.senderRole || 'người xem'}</strong>
                    <span>{msg.text || msg.reply}</span>
                  </div>
                ))
              )}
            </div>
            <div className="chat-widget-input">
              <input
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') sendChatMessage();
                }}
                placeholder={connected ? 'Ví dụ: tôi muốn mua sản phẩm này' : connectError || 'Đang kết nối chat...'}
                disabled={!connected}
              />
              <button type="button" className="btn btn-primary" onClick={sendChatMessage} disabled={!connected || !chatInput.trim()}>
                Gửi
              </button>
            </div>
          </div>
        </aside>
      </div>

      {variantPicker ? (
        <div className="live-variant-sheet" role="dialog" aria-modal="true" aria-label="Chọn biến thể sản phẩm">
          <div className="live-variant-panel">
            <div className="seller-live-card-header">
              <div>
                <h3>Chọn biến thể</h3>
                <span className="muted">{variantPicker.productName}</span>
              </div>
              <button type="button" className="btn btn-ghost" onClick={() => setVariantPicker(null)}>
                Đóng
              </button>
            </div>
            <div className="live-variant-options">
              {variantPicker.variants.map((variant) => (
                <button
                  key={variant.variantId}
                  type="button"
                  className={`live-variant-option ${String(selectedVariantId) === String(variant.variantId) ? 'active' : ''}`}
                  onClick={() => setSelectedVariantId(variant.variantId)}
                >
                  <span>{variant.name}</span>
                  <small>Tồn {variant.stock}</small>
                </button>
              ))}
            </div>
            <div className="live-product-actions">
              <button type="button" className="btn btn-outline" onClick={() => setVariantPicker(null)}>
                Hủy
              </button>
              <button type="button" className="btn btn-primary" onClick={confirmVariantSelection}>
                Thêm vào giỏ
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
