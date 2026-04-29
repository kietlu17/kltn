import { useEffect, useMemo, useRef, useState } from 'react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';

export default function SellerChat() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const shopId = user?.shopId || user?.id;
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const pollListRef = useRef(null);
  const pollMessagesRef = useRef(null);

  const activeConversation = useMemo(
    () => conversations.find((conv) => conv.id === activeId) || null,
    [conversations, activeId]
  );

  const loadConversations = async () => {
    if (!shopId) return;
    try {
      const response = await api.get(`/chat/shops/${shopId}/conversations`);
      setConversations(response.data || []);
    } catch {
      setConversations([]);
    }
  };

  const loadMessages = async (conversationId) => {
    if (!conversationId) return;
    try {
      const response = await api.get(`/chat/conversations/${conversationId}/messages`);
      setMessages(response.data || []);
    } catch {
      setMessages([]);
    }
  };

  useEffect(() => {
    loadConversations();
    if (pollListRef.current) clearInterval(pollListRef.current);
    pollListRef.current = setInterval(loadConversations, 5000);
    return () => {
      if (pollListRef.current) clearInterval(pollListRef.current);
    };
  }, [shopId]);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return undefined;
    }
    loadMessages(activeId);
    if (pollMessagesRef.current) clearInterval(pollMessagesRef.current);
    pollMessagesRef.current = setInterval(() => loadMessages(activeId), 3000);
    return () => {
      if (pollMessagesRef.current) clearInterval(pollMessagesRef.current);
    };
  }, [activeId]);

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || !activeId) return;
    setInput('');
    try {
      const response = await api.post(`/chat/conversations/${activeId}/messages`, {
        senderRole: 'seller',
        senderId: shopId,
        text: trimmed
      });
      setMessages((prev) => [...prev, response.data]);
    } catch (err) {
      showToast(err?.response?.data?.message || 'Không thể gửi tin nhắn', 'error');
    }
  };

  return (
    <div className="chat-layout">
      <aside className="chat-list">
        <h3>Cuộc trò chuyện khách hàng</h3>
        {conversations.length === 0 ? (
          <div className="muted">Chưa có cuộc trò chuyện nào.</div>
        ) : (
          conversations.map((conv) => (
            <button
              key={conv.id}
              type="button"
              className={`chat-list-item ${activeId === conv.id ? 'active' : ''}`}
              onClick={() => setActiveId(conv.id)}
            >
              <div className="chat-list-title">{conv.buyerName || conv.buyerId}</div>
              <div className="muted">
                {conv.product?.name || 'Sản phẩm'} · {conv.lastMessage || 'Tin nhắn mới'}
              </div>
            </button>
          ))
        )}
      </aside>

      <section className="chat-thread">
        {activeConversation ? (
          <>
            <div className="chat-thread-header">
              <div>
                <h3>{activeConversation.buyerName || activeConversation.buyerId}</h3>
                <div className="muted">{activeConversation.product?.name || 'Sản phẩm'}</div>
              </div>
            </div>
            <div className="chat-thread-body">
              {messages.length === 0 ? (
                <div className="muted">Hãy bắt đầu cuộc trò chuyện.</div>
              ) : (
                messages.map((msg) => (
                  <div key={msg.id} className={`chat-message ${msg.senderRole === 'seller' ? 'outgoing' : 'incoming'}`}>
                    <span>{msg.text}</span>
                  </div>
                ))
              )}
            </div>
            <div className="chat-thread-input">
              <input
                placeholder="Nhập phản hồi..."
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') handleSend();
                }}
              />
              <button type="button" className="btn btn-primary" onClick={handleSend}>Gửi</button>
            </div>
          </>
        ) : (
          <div className="chat-empty">
            <h3>Chọn một cuộc chat</h3>
            <p className="muted">Chọn một cuộc chat để bắt đầu phản hồi.</p>
          </div>
        )}
      </section>
    </div>
  );
}
