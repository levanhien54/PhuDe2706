import React, { useEffect, useState } from 'react';
import { API_BASE } from '../api';

const LABELS = {
  orchestrator: 'Điều phối', whisperx: 'Nhận giọng (WhisperX)',
  omnivoice: 'Giọng đọc (OmniVoice)', tts: 'Giọng đọc (TTS)',
  ollama: 'Dịch (Ollama)', vllm: 'Dịch (vLLM)',
};

export default function SystemStatus() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(`${API_BASE}/api/health`);
        if (!r.ok) throw new Error('health ' + r.status);
        const d = await r.json();
        if (alive) { setHealth(d); setError(false); }
      } catch { if (alive) setError(true); }
    };
    tick();
    const id = setInterval(() => { if (!document.hidden) tick(); }, 10000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const ready = health?.ready ?? 0;
  const total = health?.total ?? 0;
  const allUp = !error && health && ready === total;
  const cls = error ? 'err' : allUp ? 'ok' : 'warn';
  const gpu = health?.gpu;
  const vramOk = gpu && Number.isFinite(gpu.vram_used_mb) && Number.isFinite(gpu.vram_total_mb);

  return (
    <div className="sysstatus">
      <button className={`sysstatus-badge ${cls}`} onClick={() => setOpen(o => !o)}>
        <span className="sysstatus-dot" />
        Hệ thống: {error ? 'mất kết nối' : health ? `${ready}/${total} sẵn sàng` : 'đang kiểm tra…'}
      </button>
      {open && health?.services && (
        <div className="sysstatus-panel">
          {Object.entries(health.services).map(([k, v]) => (
            <div key={k} className="sysstatus-row">
              <span className={`sysstatus-dot ${v === 'up' ? 'ok' : 'down'}`} />
              {LABELS[k] || k}: {v === 'up' ? 'sẵn sàng' : 'chưa lên'}
            </div>
          ))}
          {gpu && (
            <div className="sysstatus-gpu">
              {gpu.name}{vramOk && ` — VRAM ${Math.round(gpu.vram_used_mb / 1024)}/${Math.round(gpu.vram_total_mb / 1024)} GB`}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
