import React from 'react';
import { Play } from 'lucide-react';
import { API_BASE } from '../api';

export default function VideoPlayer({ filename, hasOutput }) {
  if (!filename || !hasOutput) {
    return (
      <div className="glass glass-panel animate-slide-up" style={{ animationDelay: '0.3s' }}>
        <div style={{
          background: 'rgba(0,0,0,0.3)',
          borderRadius: '12px',
          aspectRatio: '16/9',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-muted)'
        }}>
          <div style={{ textAlign: 'center' }}>
            <Play size={48} style={{ opacity: 0.2, marginBottom: '16px' }} />
            <p>Video kết quả sẽ hiển thị ở đây</p>
          </div>
        </div>
      </div>
    );
  }

  const lastDot = filename.lastIndexOf('.');
  const baseName = lastDot !== -1 ? filename.substring(0, lastDot) : filename;
  const safeName = encodeURIComponent(`${baseName}_dubbed.mp4`);
  const videoUrl = `${API_BASE}/output/${safeName}`;

  return (
    <div className="glass glass-panel animate-slide-up" style={{ animationDelay: '0.3s' }}>
      <h3 style={{ marginBottom: '16px' }}>Kết quả lồng tiếng: {filename}</h3>
      <div style={{ borderRadius: '12px', overflow: 'hidden', boxShadow: '0 10px 30px rgba(0,0,0,0.5)' }}>
        <video 
          src={videoUrl} 
          controls 
          style={{ width: '100%', display: 'block', backgroundColor: '#000' }}
        />
      </div>
      <div style={{ marginTop: '16px', display: 'flex', gap: '12px' }}>
        <a href={videoUrl} download className="btn btn-primary">Tải Xuống</a>
      </div>
    </div>
  );
}
