import React, { useEffect, useState } from 'react';

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
const LABELS = {
  orchestrator: 'Điều phối', whisperx: 'Nhận giọng (WhisperX)',
  omnivoice: 'Giọng đọc (OmniVoice)', tts: 'Giọng đọc (TTS)',
  ollama: 'Dịch (Ollama)', vllm: 'Dịch (vLLM)',
};

export default function SystemStatus() {
  const [health, setHealth] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(`${API}/api/health`);
        const d = await r.json();
        if (alive) setHealth(d);
      } catch { if (alive) setHealth(null); }
    };
    tick();
    const id = setInterval(() => { if (!document.hidden) tick(); }, 10000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const ready = health?.ready ?? 0;
  const total = health?.total ?? 0;
  const allUp = health && ready === total;

  return (
    <div className="sysstatus">
      <button className={`sysstatus-badge ${allUp ? 'ok' : 'warn'}`} onClick={() => setOpen(o => !o)}>
        <span className="sysstatus-dot" />
        Hệ thống: {health ? `${ready}/${total} sẵn sàng` : 'đang kiểm tra…'}
      </button>
      {open && health && (
        <div className="sysstatus-panel">
          {Object.entries(health.services).map(([k, v]) => (
            <div key={k} className="sysstatus-row">
              <span className={`sysstatus-dot ${v === 'up' ? 'ok' : 'down'}`} />
              {LABELS[k] || k}: {v === 'up' ? 'sẵn sàng' : 'chưa lên'}
            </div>
          ))}
          {health.gpu && (
            <div className="sysstatus-gpu">
              {health.gpu.name} — VRAM {Math.round(health.gpu.vram_used_mb / 1024)}/
              {Math.round(health.gpu.vram_total_mb / 1024)} GB
            </div>
          )}
        </div>
      )}
    </div>
  );
}
