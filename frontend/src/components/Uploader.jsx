import React, { useCallback, useState } from 'react';
import { FileVideo, Loader2 } from 'lucide-react';
import { API_BASE } from '../api';

// Client-side guard matching the advertised limit (see the "Tối đa 500MB" hint below).
const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;

export default function Uploader({ onUploadSuccess }) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') setIsDragging(true);
    else if (e.type === 'dragleave') setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (isUploading) return;   // ignore drops while an upload is in flight
    if (e.dataTransfer.files?.[0]) handleFiles(e.dataTransfer.files[0]);
  }, [isUploading]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (e) => {
    e.preventDefault();
    if (e.target.files?.[0]) handleFiles(e.target.files[0]);
  };

  const handleFiles = async (file) => {
    if (isUploading) return;   // one upload at a time
    if (!file.type.includes('video')) { alert('Vui lòng chọn file video!'); return; }
    if (file.size > MAX_UPLOAD_BYTES) { alert('File quá lớn! Kích thước tối đa là 500MB.'); return; }
    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: formData });
      const data = await res.json();
      if (res.ok) onUploadSuccess(data.filename);
      else alert('Lỗi upload: ' + (data.detail || 'Không xác định'));
    } catch {
      alert('Không thể kết nối đến Backend');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div style={{ paddingBottom: '12px', borderBottom: '1px solid var(--border-light)', marginBottom: '4px' }}>
      <h3 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '8px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        Tải Video Lên
      </h3>
      <div
        className={isDragging ? 'drag-active' : ''}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '10px 12px',
          border: `2px dashed ${isDragging ? 'var(--primary)' : 'var(--border-light)'}`,
          borderRadius: '10px',
          background: isDragging ? 'rgba(139, 92, 246, 0.08)' : 'rgba(15, 23, 42, 0.4)',
          cursor: 'pointer',
          transition: 'all 0.25s ease',
          transform: isDragging ? 'scale(1.01)' : 'scale(1)',
        }}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        {isUploading
          ? <Loader2 size={18} className="spinner" style={{ color: 'var(--primary)', flexShrink: 0 }} />
          : <FileVideo size={18} style={{ color: 'var(--primary)', flexShrink: 0 }} />
        }
        <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)', flex: 1, minWidth: 0 }}>
          {isUploading ? 'Đang tải lên...' : isDragging ? 'Thả vào đây!' : 'Kéo thả hoặc chọn file'}
        </span>
        <label className="btn btn-primary" style={{ padding: '5px 10px', fontSize: '0.78rem', flexShrink: 0, opacity: isUploading ? 0.7 : 1, cursor: isUploading ? 'not-allowed' : 'pointer' }}>
          {isUploading ? 'Đang xử lý...' : 'Chọn file'}
          <input type="file" accept="video/*" style={{ display: 'none' }} onChange={handleChange} disabled={isUploading} />
        </label>
      </div>
      <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '5px', opacity: 0.7 }}>
        MP4, MKV, AVI · Tối đa 500MB
      </p>
    </div>
  );
}
