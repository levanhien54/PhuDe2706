import React, { useState, useEffect, useRef } from 'react';
import { X, Save, Play, AlertCircle } from 'lucide-react';
import { API_BASE } from '../api';

export default function ReviewModal({ jobId, onClose, onResume }) {
  const [segments, setSegments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saveStatuses, setSaveStatuses] = useState({});
  const [resuming, setResuming] = useState(false);
  const debounceTimers = useRef({});
  // Edits whose save hasn't succeeded yet (debounce still pending, in-flight, or failed),
  // keyed by segment id. Flushed before resume so no edit is lost.
  const pendingSaves = useRef({});

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
      if (!res.ok) throw new Error(`load failed (HTTP ${res.status})`);
      const data = await res.json();
      setSegments(data.segments || []);
    } catch (e) {
      console.error(e);
      setSegments([]);
    } finally {
      setLoading(false);
    }
  };

  // Persist one segment immediately (bypassing the debounce). Clears it from the pending set on
  // success; marks an 'error' save state on failure so the edit is never silently lost.
  const saveSegment = async (id, newText) => {
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}/segments`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, translated_text: newText })
      });
      if (!res.ok) throw new Error(`save failed (HTTP ${res.status})`);
      delete pendingSaves.current[id];
      setSaveStatuses(prev => ({ ...prev, [id]: 'saved' }));
      return true;
    } catch (e) {
      console.error(e);
      setSaveStatuses(prev => ({ ...prev, [id]: 'error' }));
      return false;
    }
  };

  const handleUpdate = (id, newText) => {
    // Optimistic update immediately
    setSegments(prev => prev.map(s => s.id === id ? { ...s, translated_text: newText } : s));
    setSaveStatuses(prev => ({ ...prev, [id]: 'saving' }));
    pendingSaves.current[id] = { id, text: newText };

    // Debounce the API call 500ms
    clearTimeout(debounceTimers.current[id]);
    debounceTimers.current[id] = setTimeout(() => { saveSegment(id, newText); }, 500);
  };

  // Cancel any debounce timers and persist every still-pending edit right away.
  // Returns true only if all pending saves succeeded.
  const flushPendingSaves = async () => {
    Object.values(debounceTimers.current).forEach(clearTimeout);
    debounceTimers.current = {};
    const results = await Promise.all(
      Object.values(pendingSaves.current).map(({ id, text }) => saveSegment(id, text))
    );
    return results.every(Boolean);
  };

  const handleResume = async () => {
    if (resuming) return;
    setResuming(true);
    try {
      // Flush outstanding autosaves first so no edit is lost when phase-2 (TTS) resumes.
      const allSaved = await flushPendingSaves();
      if (!allSaved) {
        alert('Một số chỉnh sửa chưa lưu được. Vui lòng kiểm tra kết nối và thử lại trước khi tiếp tục.');
        return;
      }
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}/resume`, { method: 'POST' });
      if (!res.ok) throw new Error(`resume failed (HTTP ${res.status})`);
      onResume();
    } catch (e) {
      console.error(e);
      alert('Không thể tiếp tục lồng tiếng — job chưa sẵn sàng hoặc backend lỗi. Vui lòng thử lại.');
    } finally {
      setResuming(false);
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
                    {saveStatus === 'error' && (
                      <div className="save-indicator" style={{ color: 'var(--error)' }}>
                        <AlertCircle size={12} /> Lưu lỗi — thử lại
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
          <button className="btn btn-primary" onClick={handleResume} disabled={loading || resuming}>
            <Play size={18}/> {resuming ? 'Đang lưu & chạy tiếp…' : 'Duyệt & Chạy tiếp (TTS)'}
          </button>
        </div>
      </div>
    </div>
  );
}
