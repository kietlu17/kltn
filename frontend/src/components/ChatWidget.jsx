import { useEffect, useMemo, useRef, useState } from 'react';
import api, { resolveImageUrl } from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

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
  const { showToast } = useToast();
  const [mode, setMode] = useState('ai');
  const [input, setInput] = useState('');
  const [aiMessages, setAiMessages] = useState([defaultAiMessage]);
  const [humanMessages, setHumanMessages] = useState([]);
  const [conversation, setConversation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const scrollRef = useRef(null);
  const pollRef = useRef(null);

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

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    setInput('');

    if (mode === 'ai') {
      const nextId = `ai-user-${Date.now()}`;
      setAiMessages((prev) => [...prev, { id: nextId, role: 'user', text: trimmed }]);
      setLoading(true);
      try {
        const response = await api.post('/chat/ai/respond', {
          question: trimmed,
          product: productSnapshot
        });
        setAiMessages((prev) => [
          ...prev,
          { id: `ai-bot-${Date.now()}`, role: 'assistant', text: response.data?.answer || '...' }
        ]);
      } catch (err) {
        showToast(err?.response?.data?.message || 'Không thể nhận phản hồi AI', 'error');
      } finally {
        setLoading(false);
      }
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
          onClick={() => setMode('human')}
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
              <span>{msg.text}</span>
            </div>
          ))
        )}
      </div>

      <div className="chat-widget-input">
        <input
          placeholder={mode === 'ai' ? 'Hỏi về sản phẩm này...' : 'Nhắn cho người bán...'}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') handleSend();
          }}
          disabled={loading}
        />
        <button type="button" className="btn btn-primary" onClick={handleSend} disabled={loading}>
          Gửi
        </button>
      </div>
    </div>
  );
}
