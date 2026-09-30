import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import api, { resolveImageUrl } from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useCart } from '../context/CartContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import MicrophoneButton from './MicrophoneButton.jsx';

const defaultAiMessage = {
  id: 'ai-welcome',
  role: 'assistant',
  text: 'Xin chào! Tôi có thể trả lời câu hỏi về sản phẩm này.'
};

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

export default function ChatWidget({ product, shopId, shopName, onClose }) {
  const { user } = useAuth();
  const { refreshCart } = useCart();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [mode, setMode] = useState('ai');
  const [input, setInput] = useState('');
  const [attachment, setAttachment] = useState(null);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [aiMessages, setAiMessages] = useState([defaultAiMessage]);
  const [humanMessages, setHumanMessages] = useState([]);
  const [conversation, setConversation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const scrollRef = useRef(null);
  const pollRef = useRef(null);
  const fileInputRef = useRef(null);
  const aiSessionRef = useRef(null);
  const currentProductId = String(product?._id || product?.id || '');

  const productSnapshot = useMemo(() => {
    if (!product) return null;
    return {
      productId: product._id || product.id,
      name: product.name,
      price: product.price,
      stock: product.quantity,
      category: product.categoryName,
      description: product.description,
      detail: product.detail,
      shopName
    };
  }, [product, shopName]);

  const productImage = useMemo(() => {
    if (!product) return '';
    const raw = product?.images?.[0] || product?.imageUrl || '';
    return resolveImageUrl(raw);
  }, [product]);

  useEffect(() => {
    aiSessionRef.current = null;
    setAiMessages([defaultAiMessage]);
    setAttachment(null);
  }, [currentProductId]);

  useEffect(() => {
    if (mode !== 'human') {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }

    if (!shopId || !user?.id) return;

    let active = true;
    const connect = async () => {
      setConnecting(true);
      try {
        const response = await api.post('/chat/conversations', {
          shopId,
          buyerId: user.id,
          buyerName: user.email || 'Người mua',
          product: productSnapshot
        });
        if (!active) return;

        setConversation(response.data);

        const messagesRes = await api.get(`/chat/conversations/${response.data.id}/messages`);
        if (!active) return;

        setHumanMessages(messagesRes.data || []);

        if (!pollRef.current) {
          pollRef.current = setInterval(async () => {
            try {
              const next = await api.get(`/chat/conversations/${response.data.id}/messages`);
              setHumanMessages(next.data || []);
            } catch {
              // bỏ qua lỗi polling tạm thời
            }
          }, 4000);
        }
      } catch (err) {
        if (active) {
          showToast(err?.response?.data?.message || 'Không thể kết nối với shop', 'error');
        }
      } finally {
        if (active) setConnecting(false);
      }
    };

    connect();

    return () => {
      active = false;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [mode, shopId, user?.id, productSnapshot, showToast]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [aiMessages, humanMessages, mode]);

  const sendAi = async (text, referenceProductId = currentProductId, action = {}) => {
    const trimmed = String(text || '').trim();
    const selectedImage = attachment;
    if ((!trimmed && !selectedImage) || loading || voiceBusy) return;
    setAiMessages((prev) => [
      ...prev,
      {
        id: `ai-user-${Date.now()}`,
        role: 'user',
        text: trimmed || 'Tìm sản phẩm giống ảnh này',
        image: selectedImage?.data || null
      }
    ]);
    setAttachment(null);
    setLoading(true);
    try {
      const response = await api.post('/assistant/chat', {
        message: trimmed,
        image: selectedImage?.data || null,
        sessionId: aiSessionRef.current,
        referenceProductId: referenceProductId || null,
        ...action
      }, { timeout: 370000 });
      const data = response.data || {};
      aiSessionRef.current = data.sessionId || aiSessionRef.current;
      setAiMessages((prev) => [...prev, {
        id: `ai-bot-${Date.now()}`,
        role: 'assistant',
        text: data.answer || '...',
        products: data.products || [],
        pendingAction: data.pendingAction || null
      }]);

      if (data.actionResult?.status === 'completed' || data.actionResult?.cartChanged) {
        await refreshCart();
        if (data.actionResult.tool === 'open_orders') {
          onClose?.();
          navigate('/orders', {
            state: { source: 'assistant', orderIds: data.actionResult.orderIds || [] }
          });
        }
      }
      if (data.actionResult?.status === 'handoff_required') {
        if (data.actionResult.tool === 'open_checkout') {
          const selectedProductIds = Array.isArray(data.actionResult.selectedProductIds)
            ? data.actionResult.selectedProductIds.filter((item) => typeof item === 'string')
            : [];
          localStorage.setItem('checkoutSelection', JSON.stringify(selectedProductIds));
          onClose?.();
          navigate('/checkout', { state: {
            selectedProductIds,
            paymentMethod: data.actionResult.paymentMethod,
            voucherCode: data.actionResult.voucherCode || '',
            addressId: data.actionResult.addressId || '',
            source: 'assistant'
          } });
        } else if (data.actionResult.tool === 'open_addresses') {
          onClose?.();
          navigate('/addresses', { state: { source: 'assistant' } });
        }
      }
    } catch (err) {
      setAttachment(selectedImage);
      showToast(
        err?.response?.data?.detail || err?.response?.data?.message || 'Không thể nhận phản hồi AI',
        'error'
      );
    } finally {
      setLoading(false);
    }
  };

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed && (mode !== 'ai' || !attachment)) return;
    setInput('');

    if (mode === 'ai') {
      await sendAi(trimmed);
      return;
    }

    if (!conversation?.id) {
      showToast('Đang kết nối với shop...', 'error');
      return;
    }

    try {
      const response = await api.post(`/chat/conversations/${conversation.id}/messages`, {
        senderRole: 'buyer',
        senderId: user?.id,
        text: trimmed
      });
      setHumanMessages((prev) => [...prev, response.data]);
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể gửi tin nhắn', 'error');
    }
  };

  const messages = mode === 'ai' ? aiMessages : humanMessages;

  const chooseImage = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) {
      showToast('Chọn ảnh JPG, PNG hoặc WebP, tối đa 5 MB.', 'error');
      return;
    }
    try {
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      setAttachment({ data, name: file.name });
    } catch {
      showToast('Không đọc được ảnh. Bạn thử chọn lại nhé.', 'error');
    }
  };

  return (
    <div className="chat-widget">
      <div className="chat-widget-header">
        <div>
          <strong>Trò chuyện</strong>
          <div className="muted">{shopName || 'Trợ lý shop'}</div>
        </div>
        <button type="button" className="chat-close" onClick={onClose}>X</button>
      </div>

      <div className="chat-widget-product">
        {productImage ? (
          <img src={productImage} alt={product?.name} />
        ) : (
          <div className="chat-product-placeholder" />
        )}
        <div>
          <div className="chat-product-name">{product?.name || 'Sản phẩm'}</div>
          <div className="muted">Giá: {product?.price != null ? formatPrice(product.price) : 'Không có'}</div>
          <div className="muted">Tồn kho: {product?.quantity ?? 'Không có'}</div>
        </div>
      </div>

      <div className="chat-widget-tabs">
        <button
          type="button"
          className={`chat-tab ${mode === 'ai' ? 'active' : ''}`}
          onClick={() => setMode('ai')}
        >
          Trợ lý AI
        </button>
        <button
          type="button"
          className={`chat-tab ${mode === 'human' ? 'active' : ''}`}
          onClick={() => {
            if (!user?.id || user?.role !== 'buyer') {
              showToast('Vui lòng đăng nhập tài khoản người mua để chat với người bán', 'error');
              return;
            }
            setMode('human');
          }}
        >
          Chat với người bán
        </button>
      </div>

      <div className="chat-widget-body" ref={scrollRef}>
        {connecting && mode === 'human' ? (
          <div className="muted">Đang kết nối với shop...</div>
        ) : messages.length === 0 ? (
          <div className="muted">Hãy bắt đầu cuộc trò chuyện.</div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`chat-message ${msg.role === 'assistant' || msg.senderRole === 'seller' ? 'incoming' : 'outgoing'}`}
            >
              {msg.image && <img className="chat-sent-image" src={msg.image} alt="Ảnh đã gửi" />}
              <span>{msg.text}</span>
              {mode === 'ai' && msg.products?.length > 0 && (
                <div className="chat-ai-products">
                  {msg.products.map((item) => (
                    <div className="chat-ai-product" key={item.id}>
                      <Link to={`/product/${item.id}`} onClick={onClose}>
                        <strong>{item.name}</strong>
                        {Number.isFinite(Number(item.price)) && (
                          <small>{formatPrice(item.price)}</small>
                        )}
                      </Link>
                      <button
                        type="button"
                        disabled={loading}
                        onClick={() => sendAi(`Thêm ${item.name} vào giỏ`, item.id, {
                          actionRequestId: crypto.randomUUID()
                        })}
                      >
                        Thêm giỏ
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {mode === 'ai' && msg.pendingAction?.type === 'checkout_confirmation' && (
                <div className="chat-ai-confirm">
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => sendAi('Xác nhận đặt hàng', null, {
                      confirmActionId: msg.pendingAction.quoteId
                    })}
                  >
                    Xác nhận đặt hàng
                  </button>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => sendAi('Hủy', null, {
                      cancelActionId: msg.pendingAction.quoteId
                    })}
                  >
                    Hủy
                  </button>
                </div>
              )}
              {mode === 'ai' && msg.pendingAction?.type === 'cart_mutation_confirmation' && (
                <div className="chat-ai-confirm">
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => sendAi('Xác nhận', null, {
                      confirmActionId: msg.pendingAction.actionId
                    })}
                  >
                    Xác nhận thay đổi giỏ
                  </button>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => sendAi('Hủy', null, {
                      cancelActionId: msg.pendingAction.actionId
                    })}
                  >
                    Hủy
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {mode === 'ai' && attachment && (
        <div className="chat-image-preview">
          <img src={attachment.data} alt="Ảnh đã chọn" />
          <span>{attachment.name}</span>
          <button type="button" onClick={() => setAttachment(null)} aria-label="Bỏ ảnh">×</button>
        </div>
      )}
      <div className="chat-widget-input">
        {mode === 'ai' && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              hidden
              onChange={chooseImage}
            />
            <button
              type="button"
              className="chat-image-button"
              onClick={() => fileInputRef.current?.click()}
              disabled={loading || voiceBusy}
              aria-label="Gửi ảnh cho trợ lý"
            >
              Ảnh
            </button>
            <MicrophoneButton
              disabled={loading}
              onText={(text) => setInput((current) => `${current}${current ? ' ' : ''}${text}`)}
              onError={(message) => message && showToast(message, 'error')}
              onBusy={setVoiceBusy}
            />
          </>
        )}
        <input
          placeholder={mode === 'ai' ? 'Hỏi về sản phẩm này...' : 'Nhắn cho người bán...'}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') handleSend();
          }}
          disabled={loading || voiceBusy}
        />
        <button type="button" className="btn btn-primary" onClick={handleSend} disabled={loading || voiceBusy}>
          Gửi
        </button>
      </div>
    </div>
  );
}
