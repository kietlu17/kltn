import { useEffect, useMemo, useRef, useState } from 'react';
import { Room, RoomEvent, createLocalAudioTrack, createLocalVideoTrack } from 'livekit-client';
import api, { resolveImageUrl } from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

function statusLabel(status) {
  if (status === 'live') return 'Dang live';
  if (status === 'starting') return 'Dang khoi dong';
  if (status === 'ended') return 'Da ket thuc';
  if (status === 'banned') return 'Bi khoa';
  return 'Da len lich';
}

function encodeLiveData(payload) {
  return new TextEncoder().encode(JSON.stringify(payload));
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
    return 'Trinh duyet chua duoc cap quyen camera/microphone';
  }
  if (/notfound|device/i.test(message)) {
    return 'Khong tim thay camera hoac microphone';
  }
  if (/websocket|network|connect|timeout/i.test(message)) {
    return 'Khong ket noi duoc LiveKit. Kiem tra livekit container va ws://localhost:7880';
  }
  return message || 'Khong the publish camera/microphone len LiveKit';
}

async function publishLiveData(room, payload) {
  if (!room?.localParticipant) return;
  await room.localParticipant.publishData(encodeLiveData(payload), {
    reliable: true,
    topic: payload.type || 'live.event'
  });
}

export default function SellerLiveStudio() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const videoRef = useRef(null);
  const roomRef = useRef(null);
  const localTracksRef = useRef([]);

  const [lives, setLives] = useState([]);
  const [products, setProducts] = useState([]);
  const [selectedLiveId, setSelectedLiveId] = useState('');
  const [pinnedProducts, setPinnedProducts] = useState([]);
  const [selectedProductId, setSelectedProductId] = useState('');
  const [livekitSession, setLivekitSession] = useState(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [hasCameraPreview, setHasCameraPreview] = useState(false);
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
    const response = await api.get('/products', { params: { shopId } });
    const nextProducts = response.data || [];
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

  async function disconnectLiveKitRoom() {
    if (roomRef.current) {
      await roomRef.current.disconnect();
      roomRef.current = null;
    }
    setIsPublishing(false);
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
  }

  async function cleanupLiveKit() {
    await disconnectLiveKitRoom();
    stopCameraPreviewTracks();
    setIsPublishing(false);
  }

  useEffect(() => () => {
    cleanupLiveKit();
  }, []);

  async function prepareCameraPreview() {
    setPublishError('');
    if (localTracksRef.current.length) {
      setHasCameraPreview(true);
      return localTracksRef.current;
    }
    const [videoTrack, audioTrack] = await Promise.all([
      createLocalVideoTrack({ resolution: { width: 1280, height: 720 }, facingMode: 'user' }),
      createLocalAudioTrack()
    ]);
    localTracksRef.current = [videoTrack, audioTrack];

    if (videoRef.current) {
      videoTrack.attach(videoRef.current);
      videoRef.current.muted = true;
      videoRef.current.playsInline = true;
    }
    setHasCameraPreview(true);
    return localTracksRef.current;
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
    room.on(RoomEvent.ParticipantConnected, () => setViewerCount(room.remoteParticipants.size));
    room.on(RoomEvent.ParticipantDisconnected, () => setViewerCount(room.remoteParticipants.size));
    room.on(RoomEvent.DataReceived, (payload) => {
      const data = decodeLiveData(payload);
      if (!data) return;
      if (data.type === 'live.chat.message') {
        setChatMessages((prev) => [...prev.slice(-80), data]);
      }
      if (data.type === 'live.cart.item_added') {
        setChatMessages((prev) => [
          ...prev.slice(-80),
          { id: `cart-${Date.now()}`, senderName: 'AI Co-host', text: `Da them san pham ${data.productId} vao gio cua ${data.buyerId}` }
        ]);
      }
      if (data.type === 'live.intent.detected') {
        setChatMessages((prev) => [
          ...prev.slice(-80),
          { id: data.id || `intent-${Date.now()}`, senderName: 'AI Co-host', text: data.reply || 'Da nhan yeu cau mua hang' }
        ]);
      }
    });
    await room.connect(session.url, session.token);
    setViewerCount(room.remoteParticipants.size);
    await Promise.all(tracks.map((track) => room.localParticipant.publishTrack(track)));
    setIsPublishing(true);
  }

  async function createLive(event) {
    event.preventDefault();
    if (!form.title.trim()) {
      showToast('Vui long nhap tieu de livestream', 'error');
      return;
    }
    setLoading(true);
    try {
      const response = await api.post('/lives', { ...form, shopId });
      setForm({ title: '', description: '', visibility: 'public' });
      setSelectedLiveId(response.data.id || response.data._id);
      await loadLives();
      showToast('Da tao phien livestream');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Khong the tao livestream', 'error');
    } finally {
      setLoading(false);
    }
  }

  async function startLive() {
    if (!selectedLiveId) return;
    setLoading(true);
    try {
      const response = await api.post(`/lives/${selectedLiveId}/start`, {
        displayName: user?.shopName || user?.email || 'Seller'
      });
      const session = response.data?.livekit || null;
      setLivekitSession(session);
      await loadLives();
      showToast('Da bat dau live');
      if (session?.url && session?.token) {
        try {
          await connectAndPublish(session);
          showToast('Dang publish camera va microphone len LiveKit');
        } catch (publishErr) {
          const message = describePublishError(publishErr);
          setPublishError(message);
          showToast(message, 'error');
        }
      }
    } catch (err) {
      showToast(err?.response?.data?.message || 'Khong the bat dau livestream', 'error');
    } finally {
      setLoading(false);
    }
  }

  async function startPublishingCamera() {
    setLoading(true);
    try {
      await prepareCameraPreview();
      showToast('Da bat camera preview. Bam Bat dau live de phat len LiveKit');
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
    showToast('Da tat camera');
  }

  async function endLive() {
    if (!selectedLiveId) return;
    setLoading(true);
    try {
      await cleanupLiveKit();
      await api.post(`/lives/${selectedLiveId}/end`);
      setLivekitSession(null);
      await loadLives();
      showToast('Da ket thuc livestream');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Khong the ket thuc livestream', 'error');
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
      await publishLiveData(roomRef.current, {
        type: 'live.product.active_changed',
        liveId: selectedLiveId,
        shopId,
        productId: selectedProductId
      });
      showToast('Da ghim san pham vao live');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Khong the ghim san pham', 'error');
    } finally {
      setLoading(false);
    }
  }

  async function activateProduct(productId) {
    setLoading(true);
    try {
      await api.patch(`/lives/${selectedLiveId}/active-product`, { productId });
      await Promise.all([loadPinnedProducts(selectedLiveId), loadLives()]);
      await publishLiveData(roomRef.current, {
        type: 'live.product.active_changed',
        liveId: selectedLiveId,
        shopId,
        productId
      });
      showToast('Da doi san pham dang ghim');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Khong the doi san pham dang ghim', 'error');
    } finally {
      setLoading(false);
    }
  }

  function sendChatMessage() {
    const text = chatInput.trim();
    if (!text || !roomRef.current || !selectedLiveId) return;
    const payload = {
      type: 'live.chat.message',
      id: `msg-${Date.now()}`,
      liveId: selectedLiveId,
      shopId,
      senderId: user?.id,
      senderRole: 'seller',
      senderName: user?.shopName || user?.email || 'Seller',
      text,
      activePinnedProductId: activePinnedProduct?.productId || selectedLive?.activePinnedProductId || null
    };
    publishLiveData(roomRef.current, payload).catch(() => showToast('Khong the gui chat LiveKit', 'error'));
    setChatMessages((prev) => [...prev.slice(-80), payload]);
    setChatInput('');
  }

  return (
    <div className="container page-section seller-live-studio">
      <div className="section-header">
        <h2>Livestream ban hang</h2>
        <span className="section-link">LiveKit self-host studio</span>
      </div>

      <div className="seller-grid">
        <form className="card" onSubmit={createLive}>
          <h3>Tao phien live</h3>
          <div className="form-grid">
            <div>
              <label>Tieu de</label>
              <input
                value={form.title}
                onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
                placeholder="Vi du: Flash sale toi nay"
              />
            </div>
            <div>
              <label>Hien thi</label>
              <select
                value={form.visibility}
                onChange={(event) => setForm((prev) => ({ ...prev, visibility: event.target.value }))}
              >
                <option value="public">Cong khai</option>
                <option value="followers_only">Chi follower</option>
                <option value="private">Rieng tu</option>
              </select>
            </div>
          </div>
          <label>Mo ta</label>
          <textarea
            value={form.description}
            onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
            placeholder="Noi dung buoi live"
          />
          <button type="submit" className="btn btn-primary" disabled={loading}>
            Tao live
          </button>
        </form>

        <div className="card live-preview-card">
          <h3>Preview & publish</h3>
          <div className="live-video-frame">
            <video ref={videoRef} autoPlay playsInline muted />
            {!hasCameraPreview ? <span className="muted">Camera chua bat</span> : null}
          </div>
          {publishError ? <p className="form-error">{publishError}</p> : null}
          <div className="seller-stats">
            <div>
              <span className="muted">Trang thai</span>
              <strong>{selectedLive ? statusLabel(selectedLive.status) : 'Chua chon live'}</strong>
            </div>
            <div>
              <span className="muted">Nguoi xem</span>
              <strong>{viewerCount}</strong>
            </div>
          </div>
          <div className="form-actions">
            <button type="button" className="btn btn-primary" onClick={startLive} disabled={!selectedLiveId || loading}>
              Bat dau live
            </button>
            <button type="button" className="btn btn-outline" onClick={startPublishingCamera} disabled={loading || hasCameraPreview}>
              Bat camera
            </button>
            <button type="button" className="btn btn-outline" onClick={stopPublishing} disabled={!hasCameraPreview && !isPublishing}>
              Tat camera
            </button>
            <button type="button" className="btn btn-outline" onClick={endLive} disabled={!selectedLiveId || loading}>
              Ket thuc
            </button>
          </div>
        </div>

        <div className="card">
          <h3>Dieu khien live</h3>
          <label>Phien live</label>
          <select value={selectedLiveId} onChange={(event) => setSelectedLiveId(event.target.value)}>
            <option value="">Chon phien live</option>
            {lives.map((live) => (
              <option key={live.id || live._id} value={live.id || live._id}>
                {live.title} - {statusLabel(live.status)}
              </option>
            ))}
          </select>
          {selectedLive ? (
            <div className="seller-stats">
              <div>
                <span className="muted">Room</span>
                <strong>{selectedLive.providerRoomId}</strong>
              </div>
              <div>
                <span className="muted">Active product</span>
                <strong>{activePinnedProduct?.nameSnapshot || 'Chua co'}</strong>
              </div>
            </div>
          ) : (
            <p className="muted">Chua co phien live nao.</p>
          )}
          {livekitSession ? (
            <div className="livekit-token-panel">
              <div className="checkout-row">
                <span>LiveKit URL</span>
                <strong>{livekitSession.url}</strong>
              </div>
              <div className="checkout-row">
                <span>Room</span>
                <strong>{livekitSession.roomName}</strong>
              </div>
            </div>
          ) : null}
        </div>

        <div className="card">
          <h3>Ghim san pham</h3>
          <div className="form-grid">
            <div>
              <label>San pham</label>
              <select value={selectedProductId} onChange={(event) => setSelectedProductId(event.target.value)}>
                <option value="">Chon san pham</option>
                {products.map((product) => (
                  <option key={product._id || product.id} value={product._id || product.id}>
                    {product.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="live-pin-action">
              <button type="button" className="btn btn-primary" onClick={pinProduct} disabled={!selectedLiveId || !selectedProductId || loading}>
                Ghim vao live
              </button>
            </div>
          </div>
          <div className="pinned-products">
            {pinnedProducts.length === 0 ? (
              <p className="muted">Chua ghim san pham nao.</p>
            ) : (
              pinnedProducts.map((item) => (
                <div key={item.id || item._id} className={`pinned-product-row ${item.isActive ? 'active' : ''}`}>
                  {item.imageSnapshot ? <img src={resolveImageUrl(item.imageSnapshot)} alt={item.nameSnapshot} /> : <div />}
                  <div>
                    <strong>{item.nameSnapshot}</strong>
                    <span className="muted">{formatPrice(item.priceSnapshot)} - Ton {item.stockSnapshot}</span>
                  </div>
                  <button type="button" className="btn btn-outline" onClick={() => activateProduct(item.productId)} disabled={item.isActive || loading}>
                    {item.isActive ? 'Dang ghim' : 'Dat active'}
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="card">
          <h3>Chat live</h3>
          <div className="live-chat-list">
            {chatMessages.length === 0 ? (
              <p className="muted">Chua co tin nhan.</p>
            ) : (
              chatMessages.map((msg, index) => (
                <div key={msg.id || `${msg.senderId}-${index}`} className="live-chat-line">
                  <strong>{msg.senderName || msg.senderRole || 'viewer'}</strong>
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
              placeholder="Nhan tin trong live"
            />
            <button type="button" className="btn btn-primary" onClick={sendChatMessage}>
              Gui
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
