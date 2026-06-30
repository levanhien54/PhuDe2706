import React, { useState, useEffect, useRef } from 'react';
import Uploader from './components/Uploader';
import PipelineProgress from './components/PipelineProgress';
import VideoPlayer from './components/VideoPlayer';
import ReviewModal from './components/ReviewModal';
import ConfigModal from './components/ConfigModal';
import WatchFolderModal from './components/WatchFolderModal';
import Toast from './components/Toast';
import { PlayCircle, Settings, RefreshCw, Film, Edit3, Smile, Eraser, FolderSearch, Ban } from 'lucide-react';
import { API_BASE } from './api';

function App() {
  const [videos, setVideos] = useState([]);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [statusData, setStatusData] = useState(null);
  const [targetLang, setTargetLang] = useState(() => localStorage.getItem('defaultLang') || 'Tiếng Việt');
  const [targetStyle, setTargetStyle] = useState(() => localStorage.getItem('defaultStyle') || 'Tiêu chuẩn');
  const [enableLipSync, setEnableLipSync] = useState(() => localStorage.getItem('defaultLipSync') === 'true');
  // OCR (xóa chữ) chạy trên CPU và là phần nặng nhất → mặc định TẮT; bật khi video có chữ cần xóa.
  const [enableOCR, setEnableOCR] = useState(() => localStorage.getItem('defaultOCR') === 'true');
  const [ocrMode, setOcrMode] = useState(() => localStorage.getItem('defaultOCRMode') || 'blur');
  // 'multi' = auto-detect speakers & clone each (đa nhân vật); 'single' = one narrator voice.
  const [voiceMode, setVoiceMode] = useState(() => localStorage.getItem('defaultVoiceMode') || 'multi');
  // Preset narrator voice for single mode ('' = clone the video's own main speaker = default).
  const [voicePreset, setVoicePreset] = useState(() => localStorage.getItem('defaultVoicePreset') || '');
  const [voices, setVoices] = useState([]);
  const [showReview, setShowReview] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const [showWatch, setShowWatch] = useState(false);
  // Bumped to force the status poller to restart even when selectedVideo is unchanged
  // (e.g. re-dubbing the already-selected video).
  const [pollKey, setPollKey] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [toast, setToast] = useState(null);

  const showToast = (message, type = 'info') => {
    setToast({ message, type });
  };

  const fetchVideos = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/videos`);
      const data = await res.json();
      const list = data.videos || [];
      setVideos(list);
      return list;
    } catch (e) {
      console.error(e);
      return [];
    }
  };

  useEffect(() => {
    const ACTIVE_STATUSES = new Set(['PROCESSING', 'PROCESSING_PHASE2', 'QUEUED', 'CANCELLING']);
    let timeoutId;

    const tick = async () => {
      const list = await fetchVideos();
      const hasActive = list.some(v => ACTIVE_STATUSES.has(v.status));
      timeoutId = setTimeout(tick, hasActive ? 5000 : 30000);
    };

    tick();
    return () => clearTimeout(timeoutId);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedVideo) return;
    setStatusData(null); // Clear old status immediately when switching videos
    let stopped = false;

    const STATIC_STATUSES = new Set(['AWAITING_REVIEW', 'COMPLETED', 'FAILED', 'NOT_FOUND', 'CANCELLED']);

    const fetchStatus = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/status/${encodeURIComponent(selectedVideo)}`);
        const data = await res.json();
        setStatusData(data);
        if (data.status === 'COMPLETED') fetchVideos();
        if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(data.status)) stopped = true;
        return data.status;
      } catch (e) {
        console.error(e);
        return null;
      }
    };

    const poll = async () => {
      const status = await fetchStatus();
      if (!stopped) {
        const delay = STATIC_STATUSES.has(status) ? 15000 : 2000;
        setTimeout(poll, delay);
      }
    };

    poll();
    return () => { stopped = true; };
  }, [selectedVideo, pollKey]);

  // Sync the latest statusData back to the videos list for instant sidebar updates.
  // Skip NOT_FOUND (no job yet, e.g. a freshly-uploaded PENDING video) so it doesn't
  // clobber the real library status and mislabel the sidebar badge.
  useEffect(() => {
    if (statusData && statusData.status !== 'NOT_FOUND' && selectedVideo) {
      setVideos(prev => prev.map(v =>
        v.filename === selectedVideo ? { ...v, status: statusData.status, job_id: statusData.job_id || v.job_id } : v
      ));
    }
  }, [statusData, selectedVideo]);

  // Load the preset narrator-voice library once (for single-voice mode).
  useEffect(() => {
    fetch(`${API_BASE}/api/voices`)
      .then(r => (r.ok ? r.json() : { voices: [] }))
      .then(d => setVoices(d.voices || []))
      .catch(() => {});
  }, []);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await fetchVideos();
    setIsRefreshing(false);
    showToast('Đã làm mới danh sách!', 'success');
  };

  const handleUploadSuccess = (filename) => {
    fetchVideos();
    setSelectedVideo(filename);
    showToast('Tải video lên thành công!', 'success');
  };

  const startDubbing = async (filename) => {
    try {
      localStorage.setItem('defaultVoiceMode', voiceMode);
      localStorage.setItem('defaultVoicePreset', voicePreset);
      const preset = voiceMode === 'single' ? voicePreset : '';
      const res = await fetch(`${API_BASE}/api/dub/${encodeURIComponent(filename)}?target_lang=${encodeURIComponent(targetLang)}&target_style=${encodeURIComponent(targetStyle)}&enable_lipsync=${enableLipSync}&enable_ocr=${enableOCR}&ocr_mode=${ocrMode}&voice_mode=${voiceMode}&voice_preset=${encodeURIComponent(preset)}`, { method: 'POST' });
      if (!res.ok) throw new Error('API error');
      setSelectedVideo(filename);
      setPollKey(k => k + 1);  // restart the poller even if this video was already selected
      // Re-fetch status immediately
      const statusRes = await fetch(`${API_BASE}/api/status/${encodeURIComponent(filename)}`);
      const data = await statusRes.json();
      setStatusData(data);
      fetchVideos();
      showToast('Đã bắt đầu lồng tiếng!', 'success');
    } catch (e) {
      console.error(e);
      showToast('Không thể bắt đầu lồng tiếng', 'error');
    }
  };

  const handleCancelJob = async (jobId) => {
    if (!jobId) return;
    if (!window.confirm('Hủy tiến trình đang xử lý? Video sẽ dừng ngay khi hoàn tất bước hiện tại.')) return;
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}/cancel`, { method: 'POST' });
      if (!res.ok) throw new Error('cancel failed');
      setPollKey(k => k + 1);
      fetchVideos();
      showToast('Đã yêu cầu hủy — đang dừng tiến trình...', 'success');
    } catch (e) {
      console.error(e);
      showToast('Không thể hủy tiến trình', 'error');
    }
  };

  const renderMainContent = () => {
    if (!selectedVideo) {
      return (
        <div className="empty-state animate-slide-up">
          <div className="empty-icon-container">
            <Film size={48} className="empty-icon" />
          </div>
          <h2>Chưa chọn video</h2>
          <p>Vui lòng chọn một video từ thư viện bên trái hoặc tải lên video mới để bắt đầu.</p>
        </div>
      );
    }

    const videoObj = videos.find(v => v.filename === selectedVideo);
    // Use statusData as priority since it polls faster, fallback to library state.
    // /api/status returns NOT_FOUND when no job exists yet (a fresh PENDING video); treat
    // that as "no live status" so the config/start panel shows instead of the progress placeholder.
    const liveStatus = statusData && statusData.status !== 'NOT_FOUND' ? statusData.status : null;
    const currentStatus = liveStatus || videoObj?.status;

    if (currentStatus === 'PENDING') {
      return (
        <div className="config-panel glass animate-slide-up">
          <div className="config-header">
            <h2>Cấu hình lồng tiếng</h2>
            <p className="text-muted">Video đang chọn: <span className="highlight-text">{selectedVideo}</span></p>
          </div>
          
          <div className="config-form">
            <div className="form-group">
              <label>Ngôn ngữ đích</label>
              <select
                className="custom-select"
                value={targetLang}
                onChange={(e) => setTargetLang(e.target.value)}
              >
                <option value="Tiếng Việt">Tiếng Việt</option>
                <option value="English (US)">Tiếng Anh (Mỹ)</option>
                <option value="English (UK)">Tiếng Anh (Anh)</option>
                <option value="Français">Tiếng Pháp</option>
                <option value="Deutsch">Tiếng Đức</option>
                <option value="日本語">Tiếng Nhật</option>
                <option value="한국어">Tiếng Hàn</option>
                <option value="Português (Brasil)">Tiếng Bồ Đào Nha (Brazil)</option>
                <option value="中文">Tiếng Trung</option>
              </select>
            </div>

            <div className="form-group">
              <label>Phong cách dịch</label>
              <select
                className="custom-select"
                value={targetStyle}
                onChange={(e) => setTargetStyle(e.target.value)}
              >
                <option value="Tiêu chuẩn">Tiêu chuẩn (Chính xác, tự nhiên)</option>
                <option value="Hài hước / Bắt trend">Hài hước / Bắt trend (Gen Z, mặn mòi)</option>
                <option value="Tài liệu / Trang trọng">Tài liệu / Trang trọng (Nghiêm túc, chuẩn mực)</option>
                <option value="Review phim / Châm biếm">Review phim / Châm biếm (Lôi cuốn, tò mò)</option>
              </select>
            </div>

            <div className="form-group toggle-group" onClick={() => setEnableLipSync(prev => !prev)}>
              <div className="toggle-info">
                <div className="toggle-title">
                  <Smile size={20} className={enableLipSync ? 'text-primary' : 'text-muted'} />
                  <span className={enableLipSync ? 'text-main' : 'text-muted'}>Khớp môi (Lip Sync)</span>
                </div>
                <p className="toggle-desc">Sử dụng LatentSync để khớp khẩu hình miệng (cần thêm ~8GB VRAM và 60-120s).</p>
              </div>
              <div className={`custom-toggle ${enableLipSync ? 'active' : ''}`}>
                <div className="toggle-thumb" />
              </div>
            </div>

            <div className="form-group toggle-group" onClick={() => setEnableOCR(prev => !prev)}>
              <div className="toggle-info">
                <div className="toggle-title">
                  <Eraser size={20} className={enableOCR ? 'text-primary' : 'text-muted'} />
                  <span className={enableOCR ? 'text-main' : 'text-muted'}>Xóa chữ trong video (OCR)</span>
                </div>
                <p className="toggle-desc">Tự động phát hiện và xử lý chữ, logo, hoặc watermark trên video.</p>
              </div>
              <div className={`custom-toggle ${enableOCR ? 'active' : ''}`}>
                <div className="toggle-thumb" />
              </div>
            </div>

            {enableOCR && (
              <div className="form-group animate-slide-up ocr-mode-group">
                <label>Chế độ xử lý chữ</label>
                <div className="radio-group">
                  <button 
                    className={`radio-btn ${ocrMode === 'blur' ? 'active' : ''}`}
                    onClick={() => setOcrMode('blur')}
                  >
                    Làm mờ
                  </button>
                  <button 
                    className={`radio-btn ${ocrMode === 'inpaint' ? 'active' : ''}`}
                    onClick={() => setOcrMode('inpaint')}
                  >
                    Xóa (AI Inpaint)
                  </button>
                </div>
              </div>
            )}

            <div className="form-group">
              <label>Chế độ giọng đọc</label>
              <div className="radio-group">
                <button
                  className={`radio-btn ${voiceMode === 'multi' ? 'active' : ''}`}
                  onClick={() => setVoiceMode('multi')}
                  title="Tự nhận diện từng nhân vật và nhân bản giọng riêng cho mỗi người"
                >
                  Đa giọng (nhiều nhân vật)
                </button>
                <button
                  className={`radio-btn ${voiceMode === 'single' ? 'active' : ''}`}
                  onClick={() => setVoiceMode('single')}
                  title="Một giọng đọc thống nhất cho toàn bộ video (kiểu thuyết minh)"
                >
                  Một giọng đọc
                </button>
              </div>
              <p className="toggle-desc" style={{ marginTop: '6px' }}>
                {voiceMode === 'multi'
                  ? 'Tự nhận diện nhiều giọng — mỗi nhân vật một giọng nhân bản riêng.'
                  : 'Một giọng thuyết minh duy nhất cho cả video.'}
              </p>
            </div>

            {voiceMode === 'single' && (
              <div className="form-group animate-slide-up">
                <label>Giọng đọc (clone theo quốc gia)</label>
                <select
                  className="custom-select"
                  value={voicePreset}
                  onChange={(e) => setVoicePreset(e.target.value)}
                >
                  <option value="">⭐ Mặc định — clone giọng chính trong video</option>
                  {Object.entries(
                    voices.reduce((acc, v) => { (acc[v.country] ||= []).push(v); return acc; }, {})
                  ).map(([country, vs]) => (
                    <optgroup key={country} label={`${vs[0].flag} ${country}`}>
                      {vs.map((v) => (
                        <option key={v.id} value={v.id}>{v.name} · {v.gender}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                <p className="toggle-desc" style={{ marginTop: '6px' }}>
                  Không chọn → clone giọng người nói chính trong video. Chọn một giọng để lồng bằng giọng đó (clone xuyên ngôn ngữ).
                </p>
              </div>
            )}

            <div className="config-actions">
              <button className="btn btn-primary btn-large" onClick={() => startDubbing(selectedVideo)}>
                <PlayCircle size={22} /> Bắt đầu lồng tiếng
              </button>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="status-view-split">
        <div className="glass animate-slide-up pipeline-container-half">
          <PipelineProgress statusData={statusData} />
        </div>
        <div className="glass animate-slide-up player-container-half">
           <VideoPlayer filename={selectedVideo} hasOutput={currentStatus === 'COMPLETED'} />
        </div>
      </div>
    );
  };

  return (
    <div className="container">
      <header className="header animate-slide-up">
        <div>
          <h1 className="gradient-text">Studio Lồng Tiếng AI</h1>
          <p className="subtitle">Tự động hóa toàn bộ quy trình dịch và lồng tiếng video</p>
        </div>
        <div className="header-actions">
          <button className="btn btn-outline" onClick={handleRefresh} disabled={isRefreshing}>
            <RefreshCw size={18} className={isRefreshing ? 'spinner' : ''} /> Làm mới
          </button>
          <button className="btn btn-outline" onClick={() => setShowWatch(true)}>
            <FolderSearch size={18} /> Tự động
          </button>
          <button className="btn btn-outline" onClick={() => setShowConfig(true)}>
            <Settings size={18} /> Cấu hình
          </button>
        </div>
      </header>

      <div className="main-grid">
        <aside className="sidebar glass animate-slide-up">
          <div className="sidebar-upload">
            <Uploader onUploadSuccess={handleUploadSuccess} />
          </div>

          <div className="sidebar-list">
            <h3 className="sidebar-title">
              <Film size={18} className="text-primary" /> Thư viện Video
            </h3>
            {videos.length === 0 ? (
              <div className="empty-list">
                <Film size={40} className="text-muted" />
                <p>Chưa có video</p>
              </div>
            ) : (
              <div className="video-items-container">
                {videos.map((v) => (
                  <div 
                    key={v.filename} 
                    className={`video-item-clean ${selectedVideo === v.filename ? 'selected' : ''}`}
                    onClick={() => setSelectedVideo(v.filename)}
                  >
                    <div className="video-item-info">
                      <p className="video-filename" title={v.filename}>{v.filename}</p>
                      <span className={`status-dot ${v.status.toLowerCase()}`} title={v.status} />
                    </div>
                    <span className={`status-badge-small status-${v.status.toLowerCase()}`}>
                      {v.status === 'PENDING' ? 'MỚI' :
                       v.status === 'COMPLETED' ? 'HOÀN THÀNH' :
                       v.status === 'AWAITING_REVIEW' ? 'CẦN DUYỆT' :
                       v.status === 'FAILED' ? 'LỖI' :
                       v.status === 'CANCELLED' ? 'ĐÃ HỦY' :
                       v.status === 'CANCELLING' ? 'ĐANG HỦY' : 'ĐANG XỬ LÝ'}
                    </span>

                    {v.status === 'AWAITING_REVIEW' && v.job_id && (
                       <button
                         className="btn-review-mini"
                         title="Chỉnh sửa dịch thuật"
                         onClick={(e) => { e.stopPropagation(); setSelectedVideo(v.filename); setShowReview(true); }}
                       >
                         <Edit3 size={14} />
                       </button>
                    )}

                    {['PROCESSING', 'PROCESSING_PHASE2', 'QUEUED', 'AWAITING_REVIEW'].includes(v.status) && v.job_id && (
                       <button
                         className="btn-cancel-mini"
                         title="Hủy / dừng xử lý"
                         onClick={(e) => { e.stopPropagation(); handleCancelJob(v.job_id); }}
                       >
                         <Ban size={14} />
                       </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        <main className="main-content">
          {renderMainContent()}
        </main>
      </div>

      {showConfig && (
        <ConfigModal
          defaultLang={targetLang}
          defaultStyle={targetStyle}
          defaultLipSync={enableLipSync}
          defaultOCR={enableOCR}
          defaultOCRMode={ocrMode}
          onSave={(lang, style, lipSync, ocr, mode) => {
            setTargetLang(lang);
            setTargetStyle(style);
            setEnableLipSync(lipSync);
            setEnableOCR(ocr);
            setOcrMode(mode);
          }}
          onClose={() => setShowConfig(false)}
        />
      )}

      {showWatch && (
        <WatchFolderModal
          onClose={() => setShowWatch(false)}
          onSaved={() => { fetchVideos(); showToast('Đã cập nhật theo dõi thư mục!', 'success'); }}
        />
      )}

      {showReview && selectedVideo && (
        <ReviewModal
          jobId={videos.find(v => v.filename === selectedVideo)?.job_id ?? statusData?.job_id}
          onClose={() => setShowReview(false)}
          onResume={() => {
            setShowReview(false);
            fetchVideos();
            setPollKey(k => k + 1);  // restart polling so phase-2 progress shows immediately
            showToast('Đã lưu thay đổi, tiếp tục lồng tiếng!', 'success');
          }}
        />
      )}

      {toast && (
        <div className="toast-container">
          <Toast 
            message={toast.message} 
            type={toast.type} 
            onClose={() => setToast(null)} 
          />
        </div>
      )}
    </div>
  );
}

export default App;
