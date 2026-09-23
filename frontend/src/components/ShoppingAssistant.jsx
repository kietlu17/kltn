import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import api, { resolveImageUrl } from '../services/api';
import './ShoppingAssistant.css';
import MicrophoneButton from './MicrophoneButton';

const welcome = { role: 'assistant', text: 'Chào bạn! Bạn đang tìm món gì? Gửi mô tả hoặc ảnh, tôi sẽ giúp tìm sản phẩm phù hợp trên sàn.' };

export default function ShoppingAssistant() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([welcome]);
  const [input, setInput] = useState('');
  const [attachment, setAttachment] = useState(null);
  const [busy, setBusy] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [error, setError] = useState('');
  const session = useRef(null);
  const pending = useRef(false);
  const fileInput = useRef(null);
  const textInput = useRef(null);
  const end = useRef(null);
  const launcher = useRef(null);
  const activeRequest = useRef(null);
  const detailMatch = location.pathname.match(/^\/product\/([a-fA-F0-9]{24})$/);
  const visible = location.pathname === '/' || location.pathname === '/products' || Boolean(detailMatch);

  useEffect(() => {
    if (open) {
      end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [messages, busy, open]);

  useEffect(() => {
    if (open) textInput.current?.focus();
  }, [open]);

  useEffect(() => () => activeRequest.current?.abort(), []);

  async function chooseImage(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) {
      setError('Chọn ảnh JPG, PNG hoặc WebP, tối đa 5 MB.');
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
      setError('');
    } catch {
      setError('Không đọc được ảnh. Bạn thử chọn lại nhé.');
    }
  }

  async function send(text = input, referenceProductId = null) {
    if (voiceBusy || pending.current || (!text.trim() && !attachment && !referenceProductId)) return;
    pending.current = true;
    setBusy(true);
    setError('');
    const selectedImage = attachment;
    const sentMessage = { role: 'user', text: text.trim() || 'Tìm sản phẩm giống ảnh này', image: selectedImage?.data };
    setMessages((previous) => [...previous, sentMessage]);
    setInput('');
    setAttachment(null);
    const controller = new AbortController();
    activeRequest.current = controller;
    try {
      const { data } = await api.post('/assistant/chat', {
        message: text.trim(), image: selectedImage?.data || null,
        sessionId: session.current, referenceProductId,
      }, { timeout: 370000, signal: controller.signal });
      session.current = data.sessionId;
      setMessages((previous) => [...previous, { role: 'assistant', text: data.answer, products: data.products || [] }]);
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err.response?.status === 410) session.current = null;
      const detail = err.response?.data?.detail || err.response?.data?.message;
      setError(typeof detail === 'string' ? detail : 'Chưa kết nối được trợ lý. Bạn thử gửi lại sau nhé.');
      setInput(text);
      setAttachment(selectedImage);
    } finally {
      pending.current = false;
      setBusy(false);
      activeRequest.current = null;
    }
  }

  function reset() {
    if (pending.current) return;
    session.current = null;
    setMessages([welcome]);
    setInput('');
    setAttachment(null);
    setError('');
    textInput.current?.focus();
  }

  function close() {
    setOpen(false);
    launcher.current?.focus();
  }

  if (!visible) return null;

  return (
    <div className="shopping-assistant">
      <button ref={launcher} type="button" className="sa-launcher" onClick={() => setOpen(!open)}
        aria-expanded={open} aria-controls="shopping-assistant-panel">
        <span aria-hidden="true">✦</span> Trợ lý mua sắm
      </button>
      {open && (
        <section id="shopping-assistant-panel" className="sa-panel" role="dialog" aria-label="Trợ lý mua sắm"
          onKeyDown={(event) => { if (event.key === 'Escape') close(); }}>
          <header className="sa-header">
            <div><strong>Trợ lý mua sắm</strong><span>Tìm bằng chữ, ảnh hoặc giọng nói</span></div>
            <button type="button" onClick={close} aria-label="Đóng trợ lý">×</button>
          </header>
          <div className="sa-toolbar">
            <span>Khám phá sản phẩm trên toàn sàn</span>
            <button type="button" onClick={reset} disabled={busy || voiceBusy}>Chat mới</button>
          </div>
          <div className="sa-messages" role="log" aria-live="polite" aria-relevant="additions" aria-busy={busy}>
            {messages.map((message, index) => (
              <div key={index} className={`sa-message sa-${message.role}`}>
                <span className="sa-speaker">{message.role === 'user' ? 'Bạn' : 'Trợ lý'}</span>
                {message.image && <img className="sa-sent-image" src={message.image} alt="Ảnh bạn gửi để tìm sản phẩm" />}
                <p>{message.text}</p>
                {message.products?.length > 0 && (
                  <div className="sa-products">
                    {message.products.map((product) => (
                      <article className="sa-product" key={product.id}>
                        <Link to={`/product/${product.id}`} onClick={close} className="sa-product-link">
                          {product.imageUrl ? <img src={resolveImageUrl(product.imageUrl)} alt={product.name} loading="lazy" />
                            : <span className="sa-no-image" aria-hidden="true">◇</span>}
                          <div><strong>{product.name}</strong>
                            <span className="sa-price">{Number(product.price).toLocaleString('vi-VN')} ₫</span>
                            {product.variants?.[0]?.id && <small>Có biến thể phù hợp · Xem lựa chọn</small>}
                          </div>
                        </Link>
                        <button type="button" disabled={busy}
                          onClick={() => send(`Tìm sản phẩm tương tự ${product.name}`, product.id)}>Tìm tương tự</button>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {messages.length === 1 && (
              <div className="sa-suggestions">
                {['Tìm quà tặng dưới 500k', 'Gợi ý đồ dùng học tập'].map((text) => (
                  <button key={text} type="button" onClick={() => send(text)} disabled={busy}>{text}</button>
                ))}
                {detailMatch && <button type="button" onClick={() => send('Tìm sản phẩm tương tự mẫu đang xem', detailMatch[1])}
                  disabled={busy}>Tìm mẫu giống sản phẩm đang xem</button>}
              </div>
            )}
            {busy && <p className="sa-status" role="status">Đang tìm và kiểm tra sản phẩm…</p>}
            <div ref={end} />
          </div>
          {error && <p className="sa-error" role="alert">{error}</p>}
          {attachment && <div className="sa-attachment">
            <img src={attachment.data} alt="Ảnh đã chọn" /><span>{attachment.name}</span>
            <button type="button" onClick={() => setAttachment(null)} aria-label="Bỏ ảnh đã chọn">×</button>
          </div>}
          <form className="sa-composer" onSubmit={(event) => { event.preventDefault(); send(); }}>
            <MicrophoneButton disabled={busy} onBusy={setVoiceBusy} onError={setError}
              onText={(text) => setInput((previous) => `${previous}${previous ? ' ' : ''}${text}`.slice(0, 2000))} />
            <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" onChange={chooseImage} hidden />
            <button className="sa-image-button" type="button" onClick={() => fileInput.current?.click()} disabled={busy}
              aria-label="Chọn ảnh sản phẩm" title="Chọn ảnh JPG, PNG, WebP (tối đa 5 MB)">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
                <rect x="3" y="3" width="18" height="18" rx="4" /><circle cx="8" cy="8" r="1.5" />
                <path d="m4 18 5-6 4 4 3-4 5 6" />
              </svg>
            </button>
            <textarea ref={textInput} aria-label="Tin nhắn cho trợ lý" placeholder="Bạn muốn tìm món gì?" rows={2}
              maxLength={2000} value={input} disabled={busy} onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault(); send();
                }
              }} />
            <button className="sa-send" type="submit" disabled={busy || voiceBusy || (!input.trim() && !attachment)} aria-label="Gửi tin nhắn">Gửi</button>
          </form>
          <p className="sa-footnote">Ảnh rõ một món đồ giúp tìm chính xác hơn. Giá và tồn kho có thể thay đổi.</p>
        </section>
      )}
    </div>
  );
}
