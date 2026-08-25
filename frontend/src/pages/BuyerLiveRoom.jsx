import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Room, RoomEvent, Track } from 'livekit-client';
import api, { resolveImageUrl } from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
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
  const { showToast } = useToast();
  const videoRef = useRef(null);
  const audioRef = useRef(null);
  const roomRef = useRef(null);

  const [live, setLive] = useState(null);
  const [pinnedProducts, setPinnedProducts] = useState([]);
  const [viewerCount, setViewerCount] = useState(0);
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [connecting, setConnecting] = useState(false);

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
      showToast('Khong the tai phong live', 'error');
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
    if (!liveId) return;
    setConnecting(true);
    try {
      const response = await api.post(`/lives/${liveId}/viewer-token`, {
        displayName: user?.email || 'Viewer'
      });
      const session = response.data;
      if (roomRef.current) {
        await roomRef.current.disconnect();
      }
      const room = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = room;
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
          showToast('Da them san pham tu live vao gio hang');
        }
      });
      await room.connect(session.url, session.token);
      setViewerCount(room.remoteParticipants.size + 1);
      room.remoteParticipants.forEach((participant) => {
        participant.trackPublications.forEach((publication) => attachTrack(publication));
      });
      showToast('Da ket noi phong live');
    } catch (err) {
      showToast(err?.response?.data?.message || 'Khong the xem live', 'error');
    } finally {
      setConnecting(false);
    }
  }

  useEffect(() => () => {
    if (roomRef.current) roomRef.current.disconnect();
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
      senderName: user?.email || 'Buyer',
      buyerId: user?.id,
      text,
      activePinnedProductId: activeProduct?.productId || live?.activePinnedProductId || null
    };
    publishLiveData(roomRef.current, payload).catch(() => showToast('Khong the gui chat LiveKit', 'error'));
    setChatMessages((prev) => [...prev.slice(-80), payload]);
    setChatInput('');
  }

  return (
    <div className="container page-section buyer-live-room">
      <div className="section-header">
        <h2>{live?.title || 'Livestream'}</h2>
        <span className="section-link">{viewerCount} viewer</span>
      </div>

      <div className="live-room-layout">
        <section className="live-watch-surface">
          <div className="live-video-frame buyer">
            <video ref={videoRef} autoPlay playsInline />
            <audio ref={audioRef} autoPlay />
            <button type="button" className="btn btn-primary live-watch-button" onClick={connectViewer} disabled={connecting}>
              {connecting ? 'Dang ket noi...' : 'Xem live'}
            </button>
          </div>
        </section>

        <aside className="live-side-panel">
          <div className="card">
            <h3>San pham dang ghim</h3>
            {activeProduct ? (
              <div className="live-active-product">
                {activeProduct.imageSnapshot ? <img src={resolveImageUrl(activeProduct.imageSnapshot)} alt={activeProduct.nameSnapshot} /> : <div />}
                <strong>{activeProduct.nameSnapshot}</strong>
                <span>{formatPrice(activeProduct.priceSnapshot)}</span>
                <span className="muted">Ton {activeProduct.stockSnapshot}</span>
              </div>
            ) : (
              <p className="muted">Shop chua ghim san pham.</p>
            )}
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
                placeholder="Vi du: toi muon mua san pham nay"
              />
              <button type="button" className="btn btn-primary" onClick={sendChatMessage}>
                Gui
              </button>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
