import React, { useState, useEffect } from 'react';
import { X, FolderSearch, Loader2, FolderOpen } from 'lucide-react';
import { API_BASE } from '../api';

const LANGUAGES = [
  'Tiếng Việt', 'English (US)', 'English (UK)', 'Français', 'Deutsch',
  '日本語', '한국어', 'Português (Brasil)', '中文',
];
const STYLES = [
  { v: 'Tiêu chuẩn', label: 'Tiêu chuẩn' },
  { v: 'Hài hước / Bắt trend', label: 'Hài hước / Gen Z' },
  { v: 'Tài liệu / Trang trọng', label: 'Tài liệu / Nghiêm túc' },
  { v: 'Review phim / Châm biếm', label: 'Review phim' },
];

const selectStyle = { background: '#1e293b', color: 'white', border: '1px solid rgba(255,255,255,0.18)', borderRadius: '6px', padding: '6px 10px', fontSize: '0.85rem', outline: 'none', cursor: 'pointer' };

function Toggle({ on, onClick }) {
  return (
    <div onClick={onClick} style={{ width: '38px', height: '20px', background: on ? 'var(--primary)' : 'rgba(255,255,255,0.15)', borderRadius: '10px', cursor: 'pointer', position: 'relative', transition: 'background 0.2s', border: '1px solid rgba(255,255,255,0.1)', flexShrink: 0 }}>
      <div style={{ position: 'absolute', top: '3px', left: on ? '17px' : '3px', width: '12px', height: '12px', background: 'white', borderRadius: '50%', transition: 'left 0.2s', boxShadow: '0 1px 3px rgba(0,0,0,0.4)' }} />
    </div>
  );
}

const Row = ({ children }) => (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>{children}</div>
);

export default function WatchFolderModal({ onClose, onSaved }) {
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/watch/config`);
        setCfg(await r.json());
      } catch {
        setCfg({ enabled: false, folder: '', target_lang: 'Tiếng Việt', target_style: 'Tiêu chuẩn', enable_lipsync: false, enable_ocr: false, ocr_mode: 'blur', auto_resume: true, folder_exists: false });
      }
    })();
  }, []);

  const set = (k, v) => setCfg(prev => ({ ...prev, [k]: v }));

  const pickFolder = async () => {
    if (window.electronAPI?.selectFolder) {
      const p = await window.electronAPI.selectFolder();
      if (p) set('folder', p);
    } else {
      const p = window.prompt('Nhập đường dẫn tuyệt đối tới thư mục:', cfg?.folder || '');
      if (p) set('folder', p.trim());
    }
  };

  const save = async () => {
    setSaving(true); setMsg(null);
    try {
      const body = {
        enabled: cfg.enabled, folder: cfg.folder, target_lang: cfg.target_lang,
        target_style: cfg.target_style, enable_lipsync: cfg.enable_lipsync,
        enable_ocr: cfg.enable_ocr, ocr_mode: cfg.ocr_mode, auto_resume: cfg.auto_resume,
      };
      const r = await fetch(`${API_BASE}/api/watch/config`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!r.ok) {
        setMsg({ type: 'error', text: `Backend từ chối cấu hình (HTTP ${r.status}).` });
        setSaving(false);
        return;
      }
      const data = await r.json();
      const n = data?.scan?.imported?.length || 0;
      if (cfg.enabled && !data.folder_exists) {
        setMsg({ type: 'error', text: 'Đã lưu, nhưng thư mục không tồn tại / không đọc được.' });
      } else {
        setMsg({ type: 'ok', text: cfg.enabled ? `Đã bật theo dõi. Phát hiện ${n} video mới để xử lý.` : 'Đã tắt theo dõi tự động.' });
        onSaved?.(data);
      }
    } catch {
      setMsg({ type: 'error', text: 'Không lưu được cấu hình.' });
    }
    setSaving(false);
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, backdropFilter: 'blur(6px)' }}>
      <div className="glass" style={{ width: '480px', maxHeight: '90vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', padding: '28px', position: 'relative' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '1.15rem' }}>
            <FolderSearch size={20} className="gradient-text" /> Tự động xử lý theo thư mục
          </h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '4px', lineHeight: 0 }}>
            <X size={20} />
          </button>
        </div>
        <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: '20px', lineHeight: 1.5 }}>
          Chọn một thư mục, hệ thống sẽ tự phát hiện video mới (chưa xử lý) thả vào và lồng tiếng tự động — kể cả khi thu nhỏ xuống khay hệ thống.
        </p>

        {!cfg ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}><Loader2 className="spinner" /></div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* Folder */}
            <div>
              <label style={{ fontSize: '0.85rem', display: 'block', marginBottom: '6px' }}>Thư mục theo dõi</label>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  value={cfg.folder || ''}
                  onChange={(e) => set('folder', e.target.value)}
                  placeholder="Chưa chọn thư mục…"
                  style={{ flex: 1, ...selectStyle, cursor: 'text', minWidth: 0 }}
                />
                <button className="btn btn-outline" onClick={pickFolder} style={{ padding: '6px 12px', fontSize: '0.82rem', whiteSpace: 'nowrap' }}>
                  <FolderOpen size={15} /> Chọn
                </button>
              </div>
              {cfg.folder && cfg.folder_exists === false && (
                <p style={{ fontSize: '0.72rem', color: 'var(--error)', marginTop: '4px' }}>Thư mục không tồn tại.</p>
              )}
            </div>

            {/* Enable */}
            <Row>
              <div>
                <span style={{ fontSize: '0.9rem' }}>Bật theo dõi tự động</span>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>Quét thư mục mỗi ~20 giây ở nền</p>
              </div>
              <Toggle on={!!cfg.enabled} onClick={() => set('enabled', !cfg.enabled)} />
            </Row>

            {/* Auto resume */}
            <Row>
              <div>
                <span style={{ fontSize: '0.9rem' }}>Chạy tự động hoàn toàn</span>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>Bỏ qua bước duyệt dịch, chạy thẳng tới khi xong</p>
              </div>
              <Toggle on={!!cfg.auto_resume} onClick={() => set('auto_resume', !cfg.auto_resume)} />
            </Row>

            <div style={{ height: '1px', background: 'var(--border-light)' }} />

            {/* Language + style applied to auto jobs */}
            <Row>
              <span style={{ fontSize: '0.9rem' }}>Ngôn ngữ dịch</span>
              <select value={cfg.target_lang} onChange={(e) => set('target_lang', e.target.value)} style={selectStyle}>
                {LANGUAGES.map(l => <option key={l} value={l} style={{ background: '#1e293b' }}>{l}</option>)}
              </select>
            </Row>
            <Row>
              <span style={{ fontSize: '0.9rem' }}>Phong cách dịch</span>
              <select value={cfg.target_style} onChange={(e) => set('target_style', e.target.value)} style={selectStyle}>
                {STYLES.map(s => <option key={s.v} value={s.v} style={{ background: '#1e293b' }}>{s.label}</option>)}
              </select>
            </Row>
            <Row>
              <span style={{ fontSize: '0.9rem' }}>Xóa chữ / Logo (OCR)</span>
              <Toggle on={!!cfg.enable_ocr} onClick={() => set('enable_ocr', !cfg.enable_ocr)} />
            </Row>
            {cfg.enable_ocr && (
              <div style={{ display: 'flex', gap: '8px' }}>
                {[{ v: 'blur', label: 'Làm mờ' }, { v: 'inpaint', label: 'Xóa (AI inpaint)' }].map(({ v, label }) => (
                  <button key={v} onClick={() => set('ocr_mode', v)} style={{
                    flex: 1, padding: '7px 10px', fontSize: '0.78rem',
                    background: cfg.ocr_mode === v ? 'rgba(139,92,246,0.2)' : 'rgba(255,255,255,0.04)',
                    border: `1px solid ${cfg.ocr_mode === v ? 'var(--primary)' : 'rgba(255,255,255,0.12)'}`,
                    borderRadius: '8px', color: cfg.ocr_mode === v ? 'var(--primary)' : 'var(--text-muted)', cursor: 'pointer',
                  }}>{label}</button>
                ))}
              </div>
            )}
            <Row>
              <span style={{ fontSize: '0.9rem' }}>Khớp môi (Lip Sync)</span>
              <Toggle on={!!cfg.enable_lipsync} onClick={() => set('enable_lipsync', !cfg.enable_lipsync)} />
            </Row>

            {msg && (
              <p style={{ fontSize: '0.8rem', color: msg.type === 'ok' ? 'var(--success)' : 'var(--error)', margin: 0 }}>{msg.text}</p>
            )}
          </div>
        )}

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '24px' }}>
          <button className="btn btn-outline" onClick={onClose} style={{ padding: '8px 18px', fontSize: '0.85rem' }}>Đóng</button>
          <button className="btn btn-primary" onClick={save} disabled={saving || !cfg} style={{ padding: '8px 18px', fontSize: '0.85rem' }}>
            {saving ? <Loader2 size={15} className="spinner" /> : null} Lưu & áp dụng
          </button>
        </div>
      </div>
    </div>
  );
}
