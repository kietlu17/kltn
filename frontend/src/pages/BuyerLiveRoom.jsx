import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Room, RoomEvent, Track } from 'livekit-client';
import api, { resolveImageUrl } from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useCart } from '../context/CartContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
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

async function publishLiveData(room, payload) {
  if (!room?.localParticipant) return;
  await room.localParticipant.publishData(encodeLiveData(payload), {
    reliable: true,
    topic: payload.type || 'live.event'
  });
}

export default function BuyerLiveRoom() {
  const { liveId } = useParams();
  const { user } = useAuth();
  const { addItem } = useCart();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const videoRef = useRef(null);
  const audioRef = useRef(null);
  const roomRef = useRef(null);

  const [live, setLive] = useState(null);
  const [pinnedProducts, setPinnedProducts] = useState([]);
  const [viewerCount, setViewerCount] = useState(0);
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [connectError, setConnectError] = useState('');

  const activeProduct = useMemo(
    () => pinnedProducts.find((item) => item.isActive) || pinnedProducts[0] || null,
    [pinnedProducts]
  );

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

  async function attachTrack(publication) {
    if (!publication?.track) return;
    if (publication.kind === Track.Kind.Video && videoRef.current) {
      publication.track.attach(videoRef.current);
    }
    if (publication.kind === Track.Kind.Audio && audioRef.current) {
      publication.track.attach(audioRef.current);
    }
  }

  async function connectViewer() {
    if (!liveId || connecting || connected) return;
    setConnecting(true);
    setConnectError('');
    try {
      const response = await api.post(`/lives/${liveId}/viewer-token`, {
        displayName: user?.email || 'Người xem'
      });
      const session = response.data;
      if (roomRef.current) {
        await roomRef.current.disconnect();
        setConnected(false);
      }
      const room = new Room({ adaptiveStream: true });
      roomRef.current = room;
      room.on(RoomEvent.Disconnected, () => setConnected(false));
      room.on(RoomEvent.TrackSubscribed, (track, publication) => attachTrack({ ...publication, track }));
      room.on(RoomEvent.ParticipantConnected, () => setViewerCount(room.remoteParticipants.size + 1));
      room.on(RoomEvent.ParticipantDisconnected, () => setViewerCount(room.remoteParticipants.size + 1));
      room.on(RoomEvent.DataReceived, (payload) => {
        const data = decodeLiveData(payload);
        if (!data) return;
        if (data.type === 'live.chat.message' || data.type === 'live.intent.detected') {
          setChatMessages((prev) => [...prev.slice(-80), data]);
        }
        if (data.type === 'live.product.active_changed') {
          loadLive().catch(() => {});
        }
        if (data.type === 'live.cart.item_added' && (!data.buyerId || data.buyerId === user?.id)) {
          showToast('Đã thêm sản phẩm từ live vào giỏ hàng');
        }
      });
      await room.connect(session.url, session.token);
      setConnected(true);
      setViewerCount(room.remoteParticipants.size + 1);
      room.remoteParticipants.forEach((participant) => {
        participant.trackPublications.forEach((publication) => attachTrack(publication));
      });
      showToast('Đã kết nối phòng live');
    } catch (err) {
      const message = err?.response?.data?.message || 'Không thể xem live';
      setConnectError(message);
      showToast(message, 'error');
    } finally {
      setConnecting(false);
    }
  }

  useEffect(() => {
    let disposed = false;
    const timer = window.setTimeout(() => {
      if (!disposed) connectViewer();
    }, 0);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [liveId]);

  useEffect(() => () => {
    if (roomRef.current) {
      roomRef.current.disconnect();
      setConnected(false);
    }
  }, []);

  function sendChatMessage() {
    const text = chatInput.trim();
    if (!text || !roomRef.current) return;
    const payload = {
      type: 'live.chat.message',
      id: `msg-${Date.now()}`,
      liveId,
      shopId: live?.shopId,
      senderId: user?.id,
      senderRole: 'buyer',
      senderName: user?.email || 'Người mua',
      buyerId: user?.id,
      text,
      activePinnedProductId: activeProduct?.productId || live?.activePinnedProductId || null
    };
    publishLiveData(roomRef.current, payload).catch(() => showToast('Không thể gửi chat LiveKit', 'error'));
    setChatMessages((prev) => [...prev.slice(-80), payload]);
    setChatInput('');
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
      await addItem(product.productId, 1);
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
        <span className="section-link">{viewerCount} người xem</span>
      </div>

      <div className="live-room-layout">
        <section className="live-watch-surface">
          <div className="live-video-frame buyer">
            <video ref={videoRef} autoPlay playsInline />
            <audio ref={audioRef} autoPlay />
            {!connected ? (
              <div className="live-watch-status">
                <span>{connecting ? 'Đang kết nối...' : connectError || 'Đang vào phòng live'}</span>
                {connectError ? (
                  <button type="button" className="btn btn-primary" onClick={connectViewer} disabled={connecting}>
                    Thử lại
                  </button>
                ) : null}
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
                placeholder="Ví dụ: tôi muốn mua sản phẩm này"
              />
              <button type="button" className="btn btn-primary" onClick={sendChatMessage}>
                Gửi
              </button>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
