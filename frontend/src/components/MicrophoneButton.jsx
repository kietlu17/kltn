import { useEffect, useRef, useState } from 'react';
import api from '../services/api';

export default function MicrophoneButton({ disabled, onText, onError, onBusy }) {
  const [phase, setPhase] = useState('idle');
  const [seconds, setSeconds] = useState(0);
  const work = useRef(null);
  const callbacks = useRef({ onText, onError, onBusy });
  callbacks.current = { onText, onError, onBusy };

  useEffect(() => () => {
    const job = work.current;
    work.current = null;
    if (job) {
      clearInterval(job.timer);
      job.controller.abort();
      if (job.recorder?.state === 'recording') job.recorder.stop();
      job.stream?.getTracks().forEach((track) => track.stop());
    }
    callbacks.current.onBusy(false);
  }, []);

  async function toggle() {
    if (work.current) {
      if (work.current.recorder?.state === 'recording') work.current.recorder.stop();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      callbacks.current.onError('Trình duyệt chưa hỗ trợ thu âm. Hãy dùng HTTPS hoặc localhost và thử Chrome/Edge.');
      return;
    }
    const job = { controller: new AbortController(), chunks: [], bytes: 0 };
    work.current = job;
    setPhase('permission');
    callbacks.current.onBusy(true);
    callbacks.current.onError('');
    function finish() {
      clearInterval(job.timer);
      job.stream?.getTracks().forEach((track) => track.stop());
      if (work.current !== job) return;
      work.current = null;
      setPhase('idle');
      callbacks.current.onBusy(false);
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (work.current !== job) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      job.stream = stream;
      const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus']
        .find((type) => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw new Error('unsupported');
      const recorder = new MediaRecorder(stream, { mimeType });
      job.recorder = recorder;
      recorder.ondataavailable = ({ data }) => {
        job.bytes += data.size;
        if (job.bytes > 5 * 1024 * 1024) {
          job.tooLarge = true;
          if (recorder.state === 'recording') recorder.stop();
        } else job.chunks.push(data);
      };
      recorder.onerror = () => {
        job.failed = true;
        if (work.current === job) callbacks.current.onError('Không thu được âm thanh. Bạn thử lại nhé.');
        finish();
      };
      recorder.onstop = async () => {
        clearInterval(job.timer);
        stream.getTracks().forEach((track) => track.stop());
        if (work.current !== job || job.failed) return;
        setPhase('transcribing');
        try {
          if (job.tooLarge) throw new Error('large');
          const audio = new Blob(job.chunks, { type: mimeType });
          const { data } = await api.post('/assistant/transcribe', audio, {
            headers: { 'Content-Type': mimeType }, timeout: 180000, signal: job.controller.signal,
          });
          if (work.current !== job) return;
          if (data.text?.trim()) callbacks.current.onText(data.text.trim());
          else callbacks.current.onError('Chưa nghe rõ lời nói. Bạn thử thu lại nhé.');
        } catch (err) {
          if (work.current === job) {
            const detail = err.response?.data?.detail;
            callbacks.current.onError(job.tooLarge ? 'Bản ghi vượt quá 5 MB.' :
              typeof detail === 'string' ? detail : 'Chưa chuyển được giọng nói thành chữ. Bạn thử lại nhé.');
          }
        } finally { finish(); }
      };
      recorder.start(250);
      setSeconds(0);
      setPhase('recording');
      const started = Date.now();
      job.timer = setInterval(() => {
        const elapsed = Math.floor((Date.now() - started) / 1000);
        setSeconds(elapsed);
        if (elapsed >= 59 && recorder.state === 'recording') recorder.stop();
      }, 250);
    } catch (err) {
      if (work.current === job) callbacks.current.onError(err.name === 'NotAllowedError'
        ? 'Bạn cần cho phép truy cập micro để nhập bằng giọng nói.'
        : 'Không mở được micro. Kiểm tra thiết bị và thử lại.');
      finish();
    }
  }

  return <div className="sa-mic-control">
    <button type="button" className={`sa-image-button sa-mic ${phase === 'recording' ? 'sa-recording' : ''}`}
      onClick={toggle} disabled={disabled || phase === 'permission' || phase === 'transcribing'}
      aria-label={phase === 'recording' ? 'Dừng thu âm' : 'Nhập bằng giọng nói'} aria-pressed={phase === 'recording'}
      title={phase === 'recording' ? 'Dừng và chuyển thành chữ' : 'Nhập bằng giọng nói'}>
      {phase === 'recording' ? <span aria-hidden="true">■</span> :
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8" />
        </svg>}
    </button>
    {phase !== 'idle' && <span className="sa-mic-status" role="status">
      {phase === 'recording' ? `Đang thu ${seconds}s · Nhấn mic để dừng` : phase === 'permission' ? 'Đang chờ quyền micro…' : 'Đang chuyển giọng nói thành chữ…'}
    </span>}
  </div>;
}
