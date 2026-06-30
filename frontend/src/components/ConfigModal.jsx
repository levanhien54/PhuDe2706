import React, { useState, useEffect } from 'react';
import { X, CheckCircle, XCircle, Loader2, Settings, RefreshCw, Eraser, FolderOpen } from 'lucide-react';
import { API_BASE } from '../api';

const LANGUAGES = [
  { value: 'Tiếng Việt', label: 'Tiếng Việt' },
  { value: 'English (US)', label: 'Tiếng Anh (Mỹ)' },
  { value: 'English (UK)', label: 'Tiếng Anh (Anh)' },
  { value: 'Français', label: 'Tiếng Pháp' },
  { value: 'Deutsch', label: 'Tiếng Đức' },
  { value: '日本語', label: 'Tiếng Nhật' },
  { value: '한국어', label: 'Tiếng Hàn' },
  { value: 'Português (Brasil)', label: 'Tiếng Bồ Đào Nha (Brazil)' },
  { value: '中文', label: 'Tiếng Trung' },
];

const SERVICES = [
  { name: 'Orchestrator', url: `${API_BASE}/api/jobs`, port: 8000 },
  { name: 'WhisperX STT', url: 'http://127.0.0.1:8001/health', port: 8001 },
  { name: 'OmniVoice TTS (mặc định)', url: 'http://127.0.0.1:3900/health', port: 3900 },
];

export default function ConfigModal({ defaultLang, defaultStyle = 'Tiêu chuẩn', defaultLipSync, defaultOCR = false, defaultOCRMode = 'blur', onSave, onClose }) {
  const [lang, setLang] = useState(defaultLang);
  const [style, setStyle] = useState(defaultStyle);
  const [lipSync, setLipSync] = useState(defaultLipSync);
  const [enableOCR, setEnableOCR] = useState(defaultOCR);
  const [ocrMode, setOcrMode] = useState(defaultOCRMode);
  const [svcStatus, setSvcStatus] = useState({});
  const [checking, setChecking] = useState(false);
  const [outputFolder, setOutputFolder] = useState('');
  const [savingCfg, setSavingCfg] = useState(false);

  useEffect(() => { checkServices(); loadAppConfig(); }, []);

  const loadAppConfig = async () => {
    try {
      const r = await fetch(`${API_BASE}/api/app-config`, { signal: AbortSignal.timeout(4000) });
      if (r.ok) { const d = await r.json(); setOutputFolder(d.output_folder || ''); }
    } catch { /* keep default */ }
  };

  const pickOutputFolder = async () => {
    if (window.electronAPI?.selectFolder) {
      const p = await window.electronAPI.selectFolder();
      if (p) setOutputFolder(p);
    } else {
      const p = window.prompt('Nhập đường dẫn thư mục lưu video (để trống = mặc định data/output):', outputFolder || '');
      if (p !== null) setOutputFolder(p.trim());
    }
  };

  const checkServices = async () => {
    setChecking(true);
    setSvcStatus({});
    await Promise.allSettled(
      SERVICES.map(async (s) => {
        try {
          const r = await fetch(s.url, { signal: AbortSignal.timeout(3000) });
          setSvcStatus(prev => ({ ...prev, [s.name]: r.ok || r.status < 500 ? 'ok' : 'error' }));
        } catch {
          setSvcStatus(prev => ({ ...prev, [s.name]: 'error' }));
        }
      })
    );
    setChecking(false);
  };

  const handleSave = async () => {
    localStorage.setItem('defaultLang', lang);
    localStorage.setItem('defaultStyle', style);
    localStorage.setItem('defaultLipSync', String(lipSync));
    localStorage.setItem('defaultOCR', String(enableOCR));
    localStorage.setItem('defaultOCRMode', ocrMode);
    setSavingCfg(true);
    try {
      const res = await fetch(`${API_BASE}/api/app-config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ output_folder: outputFolder || '' }),
        signal: AbortSignal.timeout(5000),
      });
      if (!res.ok) {
        let msg = 'Không lưu được cấu hình.';
        try { const d = await res.json(); if (d.detail) msg = d.detail; } catch { /* ignore */ }
        setSavingCfg(false);
        alert(msg);          // keep the modal open so the user can fix the folder
        return;
      }
    } catch {
      setSavingCfg(false);
      alert('Không kết nối được máy chủ để lưu cấu hình.');
      return;
    }
    setSavingCfg(false);
    onSave(lang, style, lipSync, enableOCR, ocrMode);
    onClose();
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, backdropFilter: 'blur(6px)' }}>
      <div className="glass" style={{ width: '460px', display: 'flex', flexDirection: 'column', padding: '28px', position: 'relative' }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '1.15rem' }}>
            <Settings size={20} className="gradient-text" /> Cấu hình hệ thống
          </h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '4px', lineHeight: 0 }}>
            <X size={20} />
          </button>
        </div>

        {/* Default settings */}
        <div style={{ marginBottom: '24px' }}>
          <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '12px' }}>
            Mặc định khi xử lý
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: '0.9rem' }}>Ngôn ngữ dịch</span>
              <select
                value={lang}
                onChange={(e) => setLang(e.target.value)}
                style={{ background: '#1e293b', color: 'white', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', padding: '6px 10px', fontSize: '0.85rem', outline: 'none', cursor: 'pointer' }}
              >
                {LANGUAGES.map(l => <option key={l.value} value={l.value} style={{ background: '#1e293b', color: 'white' }}>{l.label}</option>)}
              </select>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: '0.9rem' }}>Phong cách dịch</span>
              <select
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                style={{ background: '#1e293b', color: 'white', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', padding: '6px 10px', fontSize: '0.85rem', outline: 'none', cursor: 'pointer' }}
              >
                <option value="Tiêu chuẩn" style={{ background: '#1e293b', color: 'white' }}>Tiêu chuẩn</option>
                <option value="Hài hước / Bắt trend" style={{ background: '#1e293b', color: 'white' }}>Hài hước / Gen Z</option>
                <option value="Tài liệu / Trang trọng" style={{ background: '#1e293b', color: 'white' }}>Tài liệu / Nghiêm túc</option>
                <option value="Review phim / Châm biếm" style={{ background: '#1e293b', color: 'white' }}>Review phim</option>
              </select>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <span style={{ fontSize: '0.9rem' }}>Khớp môi (Lip Sync)</span>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>LatentSync v1.5 · cần thêm ~8GB VRAM</p>
              </div>
              <div
                onClick={() => setLipSync(v => !v)}
                style={{ width: '38px', height: '20px', background: lipSync ? 'var(--primary)' : 'rgba(255,255,255,0.15)', borderRadius: '10px', cursor: 'pointer', position: 'relative', transition: 'background 0.2s', border: '1px solid rgba(255,255,255,0.1)', flexShrink: 0 }}
              >
                <div style={{ position: 'absolute', top: '3px', left: lipSync ? '17px' : '3px', width: '12px', height: '12px', background: 'white', borderRadius: '50%', transition: 'left 0.2s', boxShadow: '0 1px 3px rgba(0,0,0,0.4)' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: enableOCR ? '10px' : 0 }}>
                <div>
                  <span style={{ fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Eraser size={14} style={{ color: enableOCR ? 'var(--primary)' : 'var(--text-muted)' }} />
                    Xóa chữ / Logo (OCR)
                  </span>
                  <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>PaddleOCR · phát hiện và xử lý watermark</p>
                </div>
                <div
                  onClick={() => setEnableOCR(v => !v)}
                  style={{ width: '38px', height: '20px', background: enableOCR ? 'var(--primary)' : 'rgba(255,255,255,0.15)', borderRadius: '10px', cursor: 'pointer', position: 'relative', transition: 'background 0.2s', border: '1px solid rgba(255,255,255,0.1)', flexShrink: 0 }}
                >
                  <div style={{ position: 'absolute', top: '3px', left: enableOCR ? '17px' : '3px', width: '12px', height: '12px', background: 'white', borderRadius: '50%', transition: 'left 0.2s', boxShadow: '0 1px 3px rgba(0,0,0,0.4)' }} />
                </div>
              </div>
              {enableOCR && (
                <div style={{ display: 'flex', gap: '8px', paddingLeft: '2px' }}>
                  {[{ v: 'blur', label: 'Làm mờ', desc: 'Gaussian blur · nhanh' }, { v: 'inpaint', label: 'Xóa (AI inpaint)', desc: 'TELEA · chậm hơn, sạch hơn' }].map(({ v, label, desc }) => (
                    <button
                      key={v}
                      onClick={() => setOcrMode(v)}
                      style={{
                        flex: 1, padding: '7px 10px', fontSize: '0.78rem', textAlign: 'left',
                        background: ocrMode === v ? 'rgba(139,92,246,0.2)' : 'rgba(255,255,255,0.04)',
                        border: `1px solid ${ocrMode === v ? 'var(--primary)' : 'rgba(255,255,255,0.12)'}`,
                        borderRadius: '8px', color: ocrMode === v ? 'var(--primary)' : 'var(--text-muted)',
                        cursor: 'pointer',
                      }}
                    >
                      <div style={{ fontWeight: 500, marginBottom: '2px' }}>{label}</div>
                      <div style={{ fontSize: '0.68rem', opacity: 0.75 }}>{desc}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Output folder */}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                <div>
                  <span style={{ fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <FolderOpen size={14} style={{ color: outputFolder ? 'var(--primary)' : 'var(--text-muted)' }} />
                    Thư mục lưu video
                  </span>
                  <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>Nơi lưu video sau xử lý · để trống = mặc định (data/output)</p>
                </div>
                <button className="btn btn-outline" onClick={pickOutputFolder} style={{ padding: '6px 12px', fontSize: '0.8rem', flexShrink: 0 }}>Chọn…</button>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  value={outputFolder}
                  onChange={(e) => setOutputFolder(e.target.value)}
                  placeholder="Mặc định: data/output"
                  spellCheck={false}
                  style={{ flex: 1, minWidth: 0, background: '#1e293b', color: 'white', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', padding: '6px 10px', fontSize: '0.8rem', outline: 'none' }}
                />
                {outputFolder && (
                  <button onClick={() => setOutputFolder('')} title="Về mặc định" style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '4px', lineHeight: 0, flexShrink: 0 }}>
                    <X size={16} />
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Service status */}
        <div style={{ marginBottom: '24px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Trạng thái dịch vụ
            </p>
            <button
              onClick={checkServices}
              disabled={checking}
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: checking ? 'not-allowed' : 'pointer', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '4px', opacity: checking ? 0.6 : 1 }}
            >
              <RefreshCw size={12} className={checking ? 'spinner' : ''} /> Kiểm tra lại
            </button>
          </div>
          <div style={{ borderRadius: '10px', border: '1px solid var(--border-light)', overflow: 'hidden' }}>
            {SERVICES.map((s, i) => {
              const status = svcStatus[s.name];
              return (
                <div
                  key={s.name}
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: 'rgba(255,255,255,0.02)', borderBottom: i < SERVICES.length - 1 ? '1px solid var(--border-light)' : 'none' }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '0.85rem' }}>{s.name}</span>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: '4px' }}>:{s.port}</span>
                  </div>
                  {!status
                    ? <Loader2 size={14} className="spinner" style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
                    : status === 'ok'
                      ? <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.78rem', color: 'var(--success)' }}><CheckCircle size={14} /> Online</span>
                      : <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.78rem', color: 'var(--error)' }}><XCircle size={14} /> Offline</span>
                  }
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button className="btn btn-outline" onClick={onClose} style={{ padding: '8px 18px', fontSize: '0.85rem' }}>Đóng</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={savingCfg} style={{ padding: '8px 18px', fontSize: '0.85rem', opacity: savingCfg ? 0.7 : 1 }}>{savingCfg ? 'Đang lưu…' : 'Lưu cài đặt'}</button>
        </div>
      </div>
    </div>
  );
}
