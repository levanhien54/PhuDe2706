import React, { useState, useEffect } from 'react';
import Uploader from './components/Uploader';
import PipelineProgress from './components/PipelineProgress';
import VideoPlayer from './components/VideoPlayer';
import ReviewModal from './components/ReviewModal';
import { PlayCircle, Settings, RefreshCw, Film, Edit3 } from 'lucide-react';

function App() {
  const [videos, setVideos] = useState([]);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [statusData, setStatusData] = useState(null);
  const [targetLang, setTargetLang] = useState('Tiếng Việt');
  const [showReview, setShowReview] = useState(false);

  const fetchVideos = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/videos');
      const data = await res.json();
      setVideos(data.videos || []);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchVideos();
    const interval = setInterval(fetchVideos, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!selectedVideo) return;
    let stopped = false;

    const fetchStatus = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/status/${selectedVideo}`);
        const data = await res.json();
        setStatusData(data);
        if (data.status === 'COMPLETED') fetchVideos();
        if (data.status === 'COMPLETED' || data.status === 'FAILED') stopped = true;
      } catch (e) {
        console.error(e);
      }
    };

    const STATIC_STATUSES = new Set(['AWAITING_REVIEW', 'COMPLETED', 'FAILED', 'NOT_FOUND']);

    const poll = async () => {
      await fetchStatus();
      if (!stopped) {
        const delay = STATIC_STATUSES.has(statusData?.status) ? 15000 : 2000;
        setTimeout(poll, delay);
      }
    };

    poll();
    return () => { stopped = true; };
  }, [selectedVideo]);

  const handleUploadSuccess = (filename) => {
    fetchVideos();
    setSelectedVideo(filename);
  };

  const startDubbing = async (filename) => {
    try {
      await fetch(`http://localhost:8000/api/dub/${filename}?target_lang=${encodeURIComponent(targetLang)}`, { method: 'POST' });
      setSelectedVideo(filename);
      // Re-fetch status immediately
      const res = await fetch(`http://localhost:8000/api/status/${filename}`);
      const data = await res.json();
      setStatusData(data);
      fetchVideos();
    } catch (e) {
      console.error(e);
      alert('Không thể bắt đầu lồng tiếng');
    }
  };

  return (
    <div className="container">
      <header className="header animate-slide-up">
        <div>
          <h1 className="gradient-text" style={{ fontSize: '2.5rem', marginBottom: '8px' }}>Studio Lồng Tiếng AI</h1>
          <p style={{ color: 'var(--text-muted)' }}>Tự động hóa toàn bộ quy trình dịch và lồng tiếng video</p>
        </div>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button className="btn btn-outline" onClick={fetchVideos}>
            <RefreshCw size={18} /> Làm mới
          </button>
          <button className="btn btn-outline">
            <Settings size={18} /> Cấu hình
          </button>
        </div>
      </header>

      <div className="main-grid">
        <aside className="glass glass-panel animate-slide-up" style={{ animationDelay: '0.1s' }}>
          <Uploader onUploadSuccess={handleUploadSuccess} />
          
          <div className="video-list">
            <h3 style={{ marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Film size={20} className="gradient-text" /> Thư viện Video
            </h3>
            {videos.length === 0 ? (
              <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '20px 0' }}>Chưa có video nào</p>
            ) : (
              videos.map((v) => (
                <div 
                  key={v.filename} 
                  className="video-item" 
                  style={{ cursor: 'pointer', border: selectedVideo === v.filename ? '1px solid var(--primary)' : '' }}
                  onClick={() => setSelectedVideo(v.filename)}
                >
                  <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '150px' }}>
                    <p style={{ fontSize: '0.95rem', fontWeight: 500 }}>{v.filename}</p>
                  </div>
                  <div>
                    {v.status === 'PENDING' && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'flex-end' }}>
                        <select 
                          value={targetLang}
                          onChange={(e) => setTargetLang(e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          style={{
                            background: 'rgba(255,255,255,0.1)',
                            color: 'white',
                            border: '1px solid rgba(255,255,255,0.2)',
                            borderRadius: '4px',
                            padding: '4px 8px',
                            fontSize: '0.8rem',
                            outline: 'none',
                            cursor: 'pointer'
                          }}
                        >
                          <option value="Tiếng Việt">Tiếng Việt</option>
                          <option value="English">English</option>
                          <option value="日本語">Nhật Bản</option>
                          <option value="中文">Trung Quốc</option>
                          <option value="한국어">Hàn Quốc</option>
                          <option value="Français">Pháp</option>
                          <option value="Deutsch">Đức</option>
                        </select>
                        <button className="btn btn-primary" style={{ padding: '6px 12px', fontSize: '0.8rem' }} onClick={(e) => { e.stopPropagation(); startDubbing(v.filename); }}>
                          <PlayCircle size={14} /> Lồng tiếng
                        </button>
                      </div>
                    )}
                    {v.status !== 'PENDING' && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'flex-end' }}>
                        <span className={`status-badge ${
                          v.status === 'PROCESSING' || v.status === 'PROCESSING_PHASE2' ? 'status-processing' : 
                          v.status === 'COMPLETED' ? 'status-completed' : 
                          v.status === 'FAILED' ? 'status-failed' : 
                          v.status === 'AWAITING_REVIEW' ? 'status-warning' : 'status-queued'
                        }`}>
                          {v.status}
                        </span>
                        {v.status === 'AWAITING_REVIEW' && v.job_id && (
                          <button
                            className="btn btn-outline"
                            style={{ padding: '4px 8px', fontSize: '0.75rem', borderColor: 'var(--warning)', color: 'var(--warning)' }}
                            onClick={(e) => { e.stopPropagation(); setSelectedVideo(v.filename); setShowReview(true); }}
                          >
                            <Edit3 size={14} /> Chỉnh sửa dịch thuật
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>

        <main style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div style={{ flex: 1 }}>
            <PipelineProgress statusData={statusData} />
          </div>
          {statusData?.status === 'COMPLETED' && (
            <VideoPlayer filename={selectedVideo} hasOutput={true} />
          )}
        </main>
      </div>

      {showReview && selectedVideo && (
        <ReviewModal
          jobId={videos.find(v => v.filename === selectedVideo)?.job_id ?? statusData?.job_id}
          onClose={() => setShowReview(false)}
          onResume={() => { setShowReview(false); fetchVideos(); }}
        />
      )}
    </div>
  );
}

export default App;
