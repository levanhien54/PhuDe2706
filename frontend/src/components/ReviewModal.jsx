import React, { useState, useEffect, useRef } from 'react';
import { X, Save, Play } from 'lucide-react';
import { API_BASE } from '../api';

export default function ReviewModal({ jobId, onClose, onResume }) {
  const [segments, setSegments] = useState([]);
  const [loading, setLoading] = useState(true);
  const debounceTimers = useRef({});

  useEffect(() => {
    fetchSegments();
  }, [jobId]);

  useEffect(() => {
    return () => {
      Object.values(debounceTimers.current).forEach(clearTimeout);
    };
  }, []);

  const fetchSegments = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}/segments`);
      const data = await res.json();
      setSegments(data.segments);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdate = (id, newText) => {
    // Optimistic update immediately
    setSegments(prev => prev.map(s => s.id === id ? { ...s, translated_text: newText } : s));

    // Debounce the API call 500ms
    clearTimeout(debounceTimers.current[id]);
    debounceTimers.current[id] = setTimeout(async () => {
      try {
        await fetch(`${API_BASE}/api/jobs/${jobId}/segments`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id, translated_text: newText })
        });
      } catch (e) {
        console.error(e);
      }
    }, 500);
  };

  const handleResume = async () => {
    try {
      await fetch(`${API_BASE}/api/jobs/${jobId}/resume`, { method: 'POST' });
      onResume();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(5px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
    }}>
      <div className="glass" style={{ width: '90%', maxWidth: '1000px', maxHeight: '85vh', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '20px', borderBottom: '1px solid var(--border-light)', display: 'flex', justifyContent: 'space-between' }}>
          <h3>Hiệu đính Kịch bản (Human-in-the-loop)</h3>
          <button className="btn btn-outline" onClick={onClose} style={{ padding: '6px' }}><X size={20}/></button>
        </div>
        
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>
          {loading ? (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)' }}>Đang tải kịch bản...</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--border-light)' }}>
                  <th style={{ padding: '12px', width: '15%' }}>Thời gian</th>
                  <th style={{ padding: '12px', width: '40%' }}>Bản gốc</th>
                  <th style={{ padding: '12px', width: '45%' }}>Bản dịch (Bấm để sửa)</th>
                </tr>
              </thead>
              <tbody>
                {segments.map((seg) => (
                  <tr key={seg.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <td style={{ padding: '12px', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                      {seg.start_time.toFixed(1)}s - {seg.end_time.toFixed(1)}s
                    </td>
                    <td style={{ padding: '12px', fontSize: '0.95rem' }}>
                      {seg.speaker && (
                        <span style={{ 
                          display: 'inline-block',
                          padding: '2px 6px',
                          background: 'rgba(139, 92, 246, 0.2)',
                          color: '#c4b5fd',
                          borderRadius: '4px',
                          fontSize: '0.75rem',
                          marginBottom: '6px',
                          marginRight: '6px'
                        }}>
                          {seg.speaker}
                        </span>
                      )}
                      {seg.original_text}
                    </td>
                    <td style={{ padding: '12px' }}>
                      <textarea 
                        value={seg.translated_text || ''}
                        onChange={(e) => handleUpdate(seg.id, e.target.value)}
                        style={{
                          width: '100%',
                          minHeight: '60px',
                          background: 'rgba(0,0,0,0.2)',
                          border: '1px solid var(--border-light)',
                          color: 'white',
                          padding: '8px',
                          borderRadius: '4px',
                          resize: 'vertical',
                          fontFamily: 'inherit'
                        }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        
        <div style={{ padding: '20px', borderTop: '1px solid var(--border-light)', display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button className="btn btn-outline" onClick={onClose}>Để sau</button>
          <button className="btn btn-primary" onClick={handleResume} disabled={loading}>
            <Play size={18}/> Duyệt & Chạy tiếp (TTS)
          </button>
        </div>
      </div>
    </div>
  );
}
