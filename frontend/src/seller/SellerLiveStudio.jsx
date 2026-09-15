import { useEffect, useMemo, useRef, useState } from 'react';
import { Room, RoomEvent, createLocalAudioTrack, createLocalVideoTrack } from 'livekit-client';
import api, { getProductItems, resolveImageUrl } from '../services/api';
import { createLiveSocket } from '../services/realtime';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

function statusLabel(status) {
  if (status === 'live') return 'Đang live';
  if (status === 'starting') return 'Đang khởi động';
  if (status === 'ended') return 'Đã kết thúc';
  if (status === 'banned') return 'Bị khóa';
  return 'Đã lên lịch';
}

function decodeLiveData(payload) {
  try {
    return JSON.parse(new TextDecoder().decode(payload));
  } catch {
    return null;
  }
}

function describePublishError(err) {
  const message = err?.message || '';
  if (/permission|denied|notallowed/i.test(message)) {
    return 'Trình duyệt chưa được cấp quyền camera/microphone';
  }
  if (/notfound|device/i.test(message)) {
    return 'Không tìm thấy camera hoặc microphone';
  }
  if (/websocket|network|connect|timeout/i.test(message)) {
    return 'Không kết nối được LiveKit. Kiểm tra LIVEKIT_PUBLIC_URL, Vite proxy /livekit và livekit container';
  }
  return message || 'Không thể publish camera/microphone lên LiveKit';
}

export default function SellerLiveStudio() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const videoRef = useRef(null);
  const roomRef = useRef(null);
  const socketRef = useRef(null);
  const localTracksRef = useRef([]);

  const [lives, setLives] = useState([]);
  const [products, setProducts] = useState([]);
  const [selectedLiveId, setSelectedLiveId] = useState('');
  const [pinnedProducts, setPinnedProducts] = useState([]);
  const [selectedProductId, setSelectedProductId] = useState('');
  const [livekitSession, setLivekitSession] = useState(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isLiveRoomOpen, setIsLiveRoomOpen] = useState(false);
  const [hasCameraPreview, setHasCameraPreview] = useState(false);
  const [isMicEnabled, setIsMicEnabled] = useState(true);
  const [publishError, setPublishError] = useState('');
  const [viewerCount, setViewerCount] = useState(0);
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [form, setForm] = useState({ title: '', description: '', visibility: 'public' });
  const [loading, setLoading] = useState(false);

  const shopId = user?.shopId || user?.id;
  const selectedLive = useMemo(
    () => lives.find((item) => String(item.id || item._id) === String(selectedLiveId)) || null,
    [lives, selectedLiveId]
  );
  const activePinnedProduct = useMemo(
    () => pinnedProducts.find((item) => item.isActive) || null,
    [pinnedProducts]
  );

  function appendLiveEvent(data) {
    if (!data?.type) return;
    if (data.type === 'live.chat.message') {
      setChatMessages((prev) => [...prev.slice(-80), data]);
    }
    if (data.type === 'live.cart.item_added') {
      setChatMessages((prev) => [
        ...prev.slice(-80),
        { id: `cart-${Date.now()}`, senderName: 'Trợ lý AI', text: `Đã thêm sản phẩm ${data.productId} vào giỏ của ${data.buyerId}` }
      ]);
    }
    if (data.type === 'live.intent.detected') {
      setChatMessages((prev) => [
        ...prev.slice(-80),
        { id: data.id || `intent-${Date.now()}`, senderName: 'Trợ lý AI', text: data.reply || 'Đã nhận yêu cầu mua hàng' }
      ]);
    }
    if (data.type === 'live.intent.variant_required') {
      setChatMessages((prev) => [
        ...prev.slice(-80),
        { id: data.id || `variant-${Date.now()}`, senderName: 'Trợ lý AI', text: data.reply || 'Sản phẩm có nhiều biến thể, khách cần chọn thêm.' }
      ]);
    }
    if (data.type === 'live.cart.item_add_failed') {
      setChatMessages((prev) => [
        ...prev.slice(-80),
        { id: data.id || `cart-failed-${Date.now()}`, senderName: 'Trợ lý AI', text: data.reply || 'Không thể thêm sản phẩm vào giỏ hàng.' }
      ]);
    }
    if (data.type === 'live.product.active_changed') {
      loadPinnedProducts(selectedLiveId).catch(() => {});
      loadLives().catch(() => {});
    }
  }

  function emitRealtimeEvent(payload) {
    if (!socketRef.current?.connected) return;
    socketRef.current.emit('live:event:send', payload, (ack) => {
      if (!ack?.ok) {
        console.warn('Không thể gửi sự kiện live realtime', ack?.message);
      }
    });
  }

  async function loadLives() {
    const response = await api.get('/lives/seller/me');
    const nextLives = response.data || [];
    setLives(nextLives);
    if (!selectedLiveId && nextLives.length) {
      setSelectedLiveId(nextLives[0].id || nextLives[0]._id);
    }
  }

  async function loadProducts() {
    if (!shopId) return;
    const response = await api.get('/products', { params: { shopId, paginated: true, page: 1, limit: 100 } });
    const nextProducts = getProductItems(response.data);
    setProducts(nextProducts);
    if (!selectedProductId && nextProducts.length) {
      setSelectedProductId(nextProducts[0]._id || nextProducts[0].id);
    }
  }

  async function loadPinnedProducts(liveId) {
    if (!liveId) {
      setPinnedProducts([]);
      return;
    }
    const response = await api.get(`/lives/${liveId}/pinned-products`);
    setPinnedProducts(response.data || []);
  }

  useEffect(() => {
    loadLives().catch(() => setLives([]));
    loadProducts().catch(() => setProducts([]));
  }, [shopId]);

  useEffect(() => {
    loadPinnedProducts(selectedLiveId).catch(() => setPinnedProducts([]));
  }, [selectedLiveId]);

  useEffect(() => {
    if (!selectedLiveId || !user?.id) return undefined;

    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current = null;
    }

    const socket = createLiveSocket(selectedLiveId);
    socketRef.current = socket;
    socket.on('live:event', appendLiveEvent);
    socket.on('live:presence', () => {});
    socket.on('connect_error', (err) => {
      console.warn('Không thể kết nối realtime live', err?.message);
    });

    return () => {
      socket.disconnect();
      if (socketRef.current === socket) {
        socketRef.current = null;
      }
    };
  }, [selectedLiveId, user?.id]);

  useEffect(() => {
    if (!selectedLiveId) return undefined;
    let disposed = false;

    async function loadViewerCount() {
      try {
        const response = await api.get(`/lives/${selectedLiveId}/viewer-count`);
        if (!disposed) setViewerCount(Number(response.data?.viewerCount || 0));
      } catch {
        if (!disposed) setViewerCount((prev) => prev || 0);
      }
    }

    loadViewerCount();
    const interval = window.setInterval(loadViewerCount, 20000);
    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, [selectedLiveId]);

  useEffect(() => {
    document.body.classList.toggle('seller-live-fullscreen', isLiveRoomOpen);
    return () => document.body.classList.remove('seller-live-fullscreen');
  }, [isLiveRoomOpen]);

  async function disconnectLiveKitRoom() {
    if (roomRef.current) {
      await roomRef.current.disconnect();
      roomRef.current = null;
    }
    setIsPublishing(false);
  }

  function getLocalAudioTrack() {
    return localTracksRef.current.find((track) => track?.mediaStreamTrack?.kind === 'audio' || track?.kind === 'audio');
  }

  async function setLocalAudioEnabled(track, enabled) {
    if (!track) return;
    if (enabled && typeof track.unmute === 'function') {
      await track.unmute();
    } else if (!enabled && typeof track.mute === 'function') {
      await track.mute();
    }
    if (track.mediaStreamTrack) {
      track.mediaStreamTrack.enabled = enabled;
    }
  }

  function stopCameraPreviewTracks() {
    localTracksRef.current.forEach((track) => {
      track.stop();
      track.detach().forEach((element) => element.remove());
    });
    localTracksRef.current = [];
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setHasCameraPreview(false);
    setIsMicEnabled(true);
  }

  async function cleanupLiveKit() {
    await disconnectLiveKitRoom();
    stopCameraPreviewTracks();
    setIsPublishing(false);
  }

  useEffect(() => () => {
    cleanupLiveKit();
  }, []);

  function attachLocalVideoTrack() {
    const videoTrack = localTracksRef.current.find((track) => track?.mediaStreamTrack?.kind === 'video' || track?.kind === 'video');
    if (!videoTrack || !videoRef.current) return;
    videoTrack.attach(videoRef.current);
    videoRef.current.muted = true;
    videoRef.current.playsInline = true;
  }

  useEffect(() => {
    attachLocalVideoTrack();
  }, [isLiveRoomOpen, hasCameraPreview]);

  async function prepareCameraPreview() {
    setPublishError('');
    if (localTracksRef.current.length) {
      setHasCameraPreview(true);
      attachLocalVideoTrack();
      return localTracksRef.current;
    }
    const [videoTrack, audioTrack] = await Promise.all([
      createLocalVideoTrack({ resolution: { width: 1280, height: 720 }, facingMode: 'user' }),
      createLocalAudioTrack()
    ]);
    localTracksRef.current = [videoTrack, audioTrack];
    await setLocalAudioEnabled(audioTrack, isMicEnabled);
    attachLocalVideoTrack();
    setHasCameraPreview(true);
    return localTracksRef.current;
  }

  async function toggleMic() {
    const audioTrack = getLocalAudioTrack();
    if (!audioTrack) {
      showToast('Chưa bật microphone', 'error');
      return;
    }

    const nextEnabled = !isMicEnabled;
    try {
      await setLocalAudioEnabled(audioTrack, nextEnabled);
      setIsMicEnabled(nextEnabled);
      showToast(nextEnabled ? 'Đã bật mic' : 'Đã tắt mic');
    } catch {
      showToast('Không thể thay đổi trạng thái mic', 'error');
    }
  }

  async function connectAndPublish(session) {
    if (!session?.url || !session?.token) {
      throw new Error('LiveKit session is missing url or token');
    }
    setPublishError('');
    await disconnectLiveKitRoom();
    const tracks = await prepareCameraPreview();
    const room = new Room({ adaptiveStream: true, dynacast: true });
    roomRef.current = room;
    room.on(RoomEvent.Disconnected, () => setIsPublishing(false));
    room.on(RoomEvent.DataReceived, (payload) => {
      appendLiveEvent(decodeLiveData(payload));
    });
    await room.connect(session.url, session.token);
    await Promise.all(tracks.map((track) => room.localParticipant.publishTrack(track)));
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    api.post(`/lives/${selectedLiveId}/hls-egress/start`)
      .then((response) => {
        const updatedLive = response.data?.live;
        if (updatedLive) {
          setLives((prev) => prev.map((item) => (
            String(item.id || item._id) === String(updatedLive.id || updatedLive._id) ? updatedLive : item
          )));
        }
      })
      .catch((err) => {
        showToast(err?.response?.data?.message || 'Không thể khởi động HLS playback', 'error');
      });
    setIsPublishing(true);
    setIsLiveRoomOpen(true);
  }

  async function createLive(event) {
    event.preventDefault();
    if (!form.title.trim()) {
      showToast('Vui lòng nhập tiêu đề buổi live', 'error');
      return;
    }
    setLoading(true);
    try {
      const response = await api.post('/lives', { ...form, shopId });
      setForm({ title: '', description: '', visibility: 'public' });
      setSelectedLiveId(response.data.id || response.data._id);
      await loadLives();
      showToast('Đã tạo phiên live');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể tạo phiên live', 'error');
    } finally {
      setLoading(false);
    }
  }

  async function startLive() {
    if (!selectedLiveId) return;
    setLoading(true);
    try {
      const response = await api.post(`/lives/${selectedLiveId}/start`, {
        displayName: user?.shopName || user?.email || 'Người bán'
      });
      const session = response.data?.livekit || null;
      setLivekitSession(session);
      await loadLives();
      showToast('Đã bắt đầu live');
      if (session?.url && session?.token) {
        try {
          await connectAndPublish(session);
          showToast('Đang phát camera và microphone lên LiveKit');
        } catch (publishErr) {
          const message = describePublishError(publishErr);
          setPublishError(message);
          showToast(message, 'error');
        }
      }
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể bắt đầu livestream', 'error');
    } finally {
      setLoading(false);
    }
  }

  async function startPublishingCamera() {
    setLoading(true);
    try {
      await prepareCameraPreview();
      showToast('Đã bật camera. Bấm Bắt đầu live để phát lên LiveKit');
    } catch (err) {
      const message = describePublishError(err);
      setPublishError(message);
      showToast(message, 'error');
    } finally {
      setLoading(false);
    }
  }

  async function stopPublishing() {
    await cleanupLiveKit();
    showToast('Đã tắt camera');
  }

  async function endLive() {
    if (!selectedLiveId) return;
    setLoading(true);
    try {
      await cleanupLiveKit();
      await api.post(`/lives/${selectedLiveId}/end`);
      setLivekitSession(null);
      setIsLiveRoomOpen(false);
      await loadLives();
      showToast('Đã kết thúc livestream');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể kết thúc livestream', 'error');
    } finally {
      setLoading(false);
    }
  }

  async function pinProduct() {
    if (!selectedLiveId || !selectedProductId) return;
    setLoading(true);
    try {
      await api.post(`/lives/${selectedLiveId}/pinned-products`, {
        productId: selectedProductId,
        isActive: true
      });
      await Promise.all([loadPinnedProducts(selectedLiveId), loadLives()]);
      emitRealtimeEvent({
        type: 'live.product.active_changed',
        liveId: selectedLiveId,
        shopId,
        productId: selectedProductId
      });
      showToast('Đã ghim sản phẩm vào live');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể ghim sản phẩm', 'error');
    } finally {
      setLoading(false);
    }
  }

  async function activateProduct(productId) {
    setLoading(true);
    try {
      await api.patch(`/lives/${selectedLiveId}/active-product`, { productId });
      await Promise.all([loadPinnedProducts(selectedLiveId), loadLives()]);
      emitRealtimeEvent({
        type: 'live.product.active_changed',
        liveId: selectedLiveId,
        shopId,
        productId
      });
      showToast('Đã đổi sản phẩm đang ghim');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể đổi sản phẩm đang ghim', 'error');
    } finally {
      setLoading(false);
    }
  }

  function sendChatMessage() {
    const text = chatInput.trim();
    if (!text || !socketRef.current || !selectedLiveId) return;
    const payload = {
      id: `msg-${Date.now()}`,
      liveId: selectedLiveId,
      shopId,
      senderId: user?.id,
      senderRole: 'seller',
      senderName: user?.shopName || user?.email || 'Người bán',
      text,
      activePinnedProductId: activePinnedProduct?.productId || selectedLive?.activePinnedProductId || null
    };
    socketRef.current.emit('live:chat:send', payload, (ack) => {
      if (!ack?.ok) {
        showToast(ack?.message || 'Không thể gửi chat live', 'error');
        return;
      }
      setChatInput('');
    });
  }

  function renderPinnedProductsPanel({ asCard = true } = {}) {
    const content = (
      <>
        <div className="seller-live-card-header">
          <h3>Sản phẩm ghim</h3>
          <span className="section-link">{pinnedProducts.length} sản phẩm</span>
        </div>
        <div className="form-grid">
          <div>
            <label>Sản phẩm</label>
            <select value={selectedProductId} onChange={(event) => setSelectedProductId(event.target.value)}>
              <option value="">Chọn sản phẩm</option>
              {products.map((product) => (
                <option key={product._id || product.id} value={product._id || product.id}>
                  {product.name}
                </option>
              ))}
            </select>
          </div>
          <div className="live-pin-action">
            <button type="button" className="btn btn-primary" onClick={pinProduct} disabled={!selectedLiveId || !selectedProductId || loading}>
              Ghim vào live
            </button>
          </div>
        </div>
        <div className="pinned-products seller-live-pinned-strip">
          {pinnedProducts.length === 0 ? (
            <p className="muted">Chưa ghim sản phẩm nào.</p>
          ) : (
            pinnedProducts.map((item) => (
              <div key={item.id || item._id} className={`pinned-product-row ${item.isActive ? 'active' : ''}`}>
                {item.imageSnapshot ? <img src={resolveImageUrl(item.imageSnapshot)} alt={item.nameSnapshot} /> : <div />}
                <div>
                  <strong>{item.nameSnapshot}</strong>
                  <span className="muted">{formatPrice(item.priceSnapshot)} - Tồn {item.stockSnapshot}</span>
                </div>
                <button type="button" className="btn btn-outline" onClick={() => activateProduct(item.productId)} disabled={item.isActive || loading}>
                  {item.isActive ? 'Đang ghim' : 'Đặt làm ghim'}
                </button>
              </div>
            ))
          )}
        </div>
      </>
    );

    if (!asCard) {
      return <div className="seller-live-products">{content}</div>;
    }

    return (
      <div className="card seller-live-products">
        {content}
      </div>
    );
  }

  if (isLiveRoomOpen) {
    return (
      <div className="container page-section seller-live-room-page">
        <div className="section-header">
          <div>
            <h2>{selectedLive?.title || 'Livestream bán hàng'}</h2>
            <span className="muted">{selectedLive?.providerRoomId || livekitSession?.roomName || 'Phòng LiveKit'}</span>
          </div>
          <div className="seller-live-room-actions">
            <span className="section-link">{viewerCount} người xem</span>
            <button type="button" className="btn btn-outline" onClick={stopPublishing} disabled={!hasCameraPreview && !isPublishing}>
              Tắt camera
            </button>
            <button type="button" className="btn btn-outline" onClick={toggleMic} disabled={!hasCameraPreview && !isPublishing}>
              {isMicEnabled ? 'Tắt mic' : 'Bật mic'}
            </button>
            <button type="button" className="btn btn-primary" onClick={endLive} disabled={!selectedLiveId || loading}>
              Kết thúc live
            </button>
          </div>
        </div>

        <div className="seller-live-room-layout">
          <section className="seller-live-broadcast">
            <div className="live-video-frame seller-live-main-video">
              <video ref={videoRef} autoPlay playsInline muted />
              {!hasCameraPreview ? <span className="muted">Camera chưa bật</span> : null}
            </div>
            {publishError ? <p className="form-error">{publishError}</p> : null}
            <div className="seller-stats seller-live-inline-stats">
              <div>
                <span className="muted">Trạng thái</span>
                <strong>{selectedLive ? statusLabel(selectedLive.status) : 'Đang live'}</strong>
              </div>
              <div>
                <span className="muted">Sản phẩm ghim</span>
                <strong>{activePinnedProduct?.nameSnapshot || 'Chưa có'}</strong>
              </div>
              <div>
                <span className="muted">URL LiveKit</span>
                <strong>{livekitSession?.url || 'Đang kết nối'}</strong>
              </div>
            </div>
          </section>

          <aside className="card seller-live-chat-panel">
            <h3>Trò chuyện</h3>
            <div className="live-chat-list seller-live-chat-list">
              {chatMessages.length === 0 ? (
                <p className="muted">Chưa có tin nhắn.</p>
              ) : (
                chatMessages.map((msg, index) => (
                  <div key={msg.id || `${msg.senderId}-${index}`} className="live-chat-line">
                    <strong>{msg.senderName || msg.senderRole || 'người xem'}</strong>
                    <span>{msg.text}</span>
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
                placeholder="Nhắn tin trong live"
              />
              <button type="button" className="btn btn-primary" onClick={sendChatMessage}>
                Gửi
              </button>
            </div>
          </aside>
        </div>

        {renderPinnedProductsPanel()}
      </div>
    );
  }

  return (
    <div className="container page-section seller-live-studio">
      <div className="section-header">
        <h2>Livestream</h2>
        <span className="section-link">Studio LiveKit tự host</span>
      </div>

      <div className="seller-live-setup-grid">
        <form className="card seller-live-create-card" onSubmit={createLive}>
          <h3>Tạo phiên live</h3>
          <div className="form-grid">
            <div>
              <label>Tiêu đề</label>
              <input
                value={form.title}
                onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
                placeholder="Ví dụ: Flash sale tối nay"
              />
            </div>
            <div>
              <label>Hiển thị</label>
              <select
                value={form.visibility}
                onChange={(event) => setForm((prev) => ({ ...prev, visibility: event.target.value }))}
              >
                <option value="public">Công khai</option>
                <option value="followers_only">Chỉ người theo dõi</option>
                <option value="private">Riêng tư</option>
              </select>
            </div>
          </div>
          <label>Mô tả</label>
          <textarea
            value={form.description}
            onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
            placeholder="Nội dung buổi live"
          />
          <button type="submit" className="btn btn-primary" disabled={loading}>
            Tạo live
          </button>
        </form>

        <div className="card live-preview-card">
          <h3>Xem trước</h3>
          <div className="live-video-frame">
            <video ref={videoRef} autoPlay playsInline muted />
            {!hasCameraPreview ? <span className="muted">Camera chưa bật</span> : null}
          </div>
          {publishError ? <p className="form-error">{publishError}</p> : null}
          <div className="seller-stats">
            <div>
              <span className="muted">Trạng thái</span>
              <strong>{selectedLive ? statusLabel(selectedLive.status) : 'Chưa chọn live'}</strong>
            </div>
            <div>
              <span className="muted">Người xem</span>
              <strong>{viewerCount}</strong>
            </div>
          </div>
          <div className="form-actions">
            <button type="button" className="btn btn-primary" onClick={startLive} disabled={!selectedLiveId || loading}>
              Bắt đầu live
            </button>
            <button type="button" className="btn btn-outline" onClick={startPublishingCamera} disabled={loading || hasCameraPreview}>
              Bật camera
            </button>
            <button type="button" className="btn btn-outline" onClick={stopPublishing} disabled={!hasCameraPreview && !isPublishing}>
              Tắt camera
            </button>
            <button type="button" className="btn btn-outline" onClick={toggleMic} disabled={!hasCameraPreview && !isPublishing}>
              {isMicEnabled ? 'Tắt mic' : 'Bật mic'}
            </button>
            <button type="button" className="btn btn-outline" onClick={endLive} disabled={!selectedLiveId || loading}>
              Kết thúc
            </button>
          </div>
        </div>

        <div className="card seller-live-control-card">
          <h3>Điều khiển phiên live</h3>
          <label>Phiên live</label>
          <select value={selectedLiveId} onChange={(event) => setSelectedLiveId(event.target.value)}>
            <option value="">Chọn phiên live</option>
            {lives.map((live) => (
              <option key={live.id || live._id} value={live.id || live._id}>
                {live.title} - {statusLabel(live.status)}
              </option>
            ))}
          </select>
          {selectedLive ? (
            <div className="seller-stats">
              <div>
                <span className="muted">Phòng</span>
                <strong>{selectedLive.providerRoomId}</strong>
              </div>
              <div>
                <span className="muted">Sản phẩm đang ghim</span>
                <strong>{activePinnedProduct?.nameSnapshot || 'Chưa có'}</strong>
              </div>
            </div>
          ) : (
            <p className="muted">Chưa có phiên live nào.</p>
          )}
          {livekitSession ? (
            <div className="livekit-token-panel">
              <div className="checkout-row">
                <span>URL LiveKit</span>
                <strong>{livekitSession.url}</strong>
              </div>
              <div className="checkout-row">
                <span>Phòng</span>
                <strong>{livekitSession.roomName}</strong>
              </div>
            </div>
          ) : null}
        </div>

        <div className="card seller-live-pin-card">
          {renderPinnedProductsPanel({ asCard: false })}
        </div>

        <div className="card seller-live-setup-chat-card">
          <h3>Trò chuyện</h3>
          <div className="live-chat-list">
            {chatMessages.length === 0 ? (
              <p className="muted">Chưa có tin nhắn.</p>
            ) : (
              chatMessages.map((msg, index) => (
                <div key={msg.id || `${msg.senderId}-${index}`} className="live-chat-line">
                  <strong>{msg.senderName || msg.senderRole || 'người xem'}</strong>
                  <span>{msg.text}</span>
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
              placeholder="Nhắn tin trong live"
            />
            <button type="button" className="btn btn-primary" onClick={sendChatMessage}>
              Gửi
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
