import React from 'react';
import { 
  Mic, 
  Scissors, 
  Languages, 
  Speech, 
  MonitorPlay, 
  Type, 
  Wand2, 
  Smile, 
  Film,
  Check,
  Loader2
} from 'lucide-react';

const STAGES = [
  { id: 'audio_separate', label: 'Tách Âm Thanh', desc: 'Sử dụng Demucs để tách lời và nhạc nền', icon: Mic },
  { id: 'video_ocr', label: 'Nhận diện & Xóa Chữ', desc: 'PaddleOCR + OpenCV', icon: Type },
  { id: 'transcribe', label: 'Nhận diện Giọng nói', desc: 'WhisperX chuyển Audio thành Text', icon: Scissors },
  { id: 'translate', label: 'Dịch thuật', desc: 'Qwen2.5 / GPT-4 dịch sang Tiếng Việt', icon: Languages },
  { id: 'synthesize', label: 'Lồng Tiếng (TTS)', desc: 'OmniVoice / GPT-SoVITS tạo giọng mới', icon: Speech },
  { id: 'lip_sync', label: 'Khớp Khẩu Hình', desc: 'LatentSync', icon: Smile },
  { id: 'mux', label: 'Kết xuất (Muxing)', desc: 'FFmpeg ghép Audio và Video', icon: Film },
];

export default function PipelineProgress({ statusData }) {
  if (!statusData || statusData.status === 'NOT_FOUND') {
    return (
      <div className="glass glass-panel animate-slide-up" style={{ animationDelay: '0.2s', height: '100%' }}>
        <h3>Tiến trình lồng tiếng</h3>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '80%', color: 'var(--text-muted)' }}>
          <MonitorPlay size={48} style={{ marginBottom: '16px', opacity: 0.5 }} />
          <p>Chọn một video để xem tiến trình</p>
        </div>
      </div>
    );
  }

  const { status, results } = statusData;
  const isFailed = status === 'FAILED';
  const isCompleted = status === 'COMPLETED';
  const isProcessing = status === 'PROCESSING' || status === 'PROCESSING_PHASE2';

  // Flatten phase1/phase2 nested results into a single map
  const flatResults = {};
  if (results) {
    for (const phase of ['phase1', 'phase2']) {
      if (results[phase]) Object.assign(flatResults, results[phase]);
    }
  }

  return (
    <div className="glass glass-panel animate-slide-up" style={{ animationDelay: '0.2s' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h3>Tiến trình xử lý</h3>
        <span className={`status-badge ${isProcessing ? 'status-processing' : (isCompleted ? 'status-completed' : (isFailed ? 'status-failed' : (status === 'AWAITING_REVIEW' ? 'status-warning' : 'status-pending')))}`}>
          {status}
        </span>
      </div>

      <div className="pipeline-steps">
        {STAGES.map((stage, idx) => {
          const Icon = stage.icon;
          const stageResult = flatResults[stage.id] ?? null;
          let stageStatus = 'pending'; // pending, active, completed, failed
          
          if (stageResult) {
            stageStatus = stageResult.success ? 'completed' : 'failed';
          } else if (isProcessing) {
            const currentIndex = STAGES.findIndex(s => !flatResults[s.id]);
            if (idx === currentIndex) stageStatus = 'active';
          }

          return (
            <div key={stage.id} className={`step-item ${stageStatus}`}>
              <div className="step-icon">
                {stageStatus === 'completed' ? <Check size={16} /> : (stageStatus === 'active' ? <Loader2 className="animate-spin" size={16} /> : <Icon size={16} />)}
              </div>
              <div className="step-content">
                <h4 style={{ color: stageStatus === 'active' ? 'var(--primary)' : (stageStatus === 'failed' ? 'var(--error)' : '') }}>
                  {stage.label}
                </h4>
                <p>{stage.desc}</p>
                {stageResult && stageResult.duration && (
                  <span style={{ fontSize: '0.75rem', color: 'var(--success)' }}>
                    Hoàn thành trong {stageResult.duration.toFixed(1)}s
                  </span>
                )}
                {stageResult && !stageResult.success && stageResult.error && (
                  <span style={{ fontSize: '0.75rem', color: 'var(--error)', display: 'block', marginTop: '4px' }}>
                    ✕ {stageResult.error}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
