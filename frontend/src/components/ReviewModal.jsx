import React, { useState, useEffect, useRef } from 'react';
import { X, Save, Play } from 'lucide-react';
import { API_BASE } from '../api';

export default function ReviewModal({ jobId, onClose, onResume }) {
  const [segments, setSegments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saveStatuses, setSaveStatuses] = useState({});
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
    setSaveStatuses(prev => ({ ...prev, [id]: 'saving' }));

    // Debounce the API call 500ms
    clearTimeout(debounceTimers.current[id]);
    debounceTimers.current[id] = setTimeout(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${jobId}/segments`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id, translated_text: newText })
        });
        if (!res.ok) throw new Error(`save failed (HTTP ${res.status})`);
        setSaveStatuses(prev => ({ ...prev, [id]: 'saved' }));
      } catch (e) {
        console.error(e);
        setSaveStatuses(prev => ({ ...prev, [id]: 'error' }));
      }
    }, 500);
  };

  const handleResume = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}/resume`, { method: 'POST' });
      if (!res.ok) throw new Error(`resume failed (HTTP ${res.status})`);
      onResume();
    } catch (e) {
      console.error(e);
      alert('Không thể tiếp tục lồng tiếng — job chưa sẵn sàng hoặc backend lỗi. Vui lòng thử lại.');
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
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {segments.map((seg) => {
                const saveStatus = saveStatuses[seg.id];
                return (
                  <div key={seg.id} className="segment-card">
                    {/* Status Indicator */}
                    {saveStatus === 'saving' && (
                      <div className="save-indicator saving">
                        Đang lưu...
                      </div>
                    )}
                    {saveStatus === 'saved' && (
                      <div className="save-indicator saved">
                        <Save size={12} /> Đã lưu
                      </div>
                    )}

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem', fontWeight: 500 }}>
                        ⏳ {seg.start_time.toFixed(1)}s - {seg.end_time.toFixed(1)}s
                      </span>
                      {seg.speaker && (
                        <span style={{ 
                          padding: '2px 8px',
                          background: 'rgba(139, 92, 246, 0.2)',
                          color: '#c4b5fd',
                          borderRadius: '12px',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          border: '1px solid rgba(139, 92, 246, 0.3)'
                        }}>
                          🎤 {seg.speaker}
                        </span>
                      )}
                    </div>
                    
                    <div style={{ fontSize: '0.95rem', color: 'rgba(255,255,255,0.8)', padding: '4px 0' }}>
                      {seg.original_text}
                    </div>
                    
                    <textarea 
                      className="segment-textarea"
                      value={seg.translated_text || ''}
                      placeholder="Nhập bản dịch tại đây..."
                      onChange={(e) => handleUpdate(seg.id, e.target.value)}
                    />
                  </div>
                );
              })}
            </div>
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
