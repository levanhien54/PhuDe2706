import React from 'react';
import {
  Mic,
  Scissors,
  Languages,
  Speech,
  Type,
  Wand2,
  Smile,
  Film,
  Check,
  Loader2,
  MinusCircle,
} from 'lucide-react';

const STAGES = [
  { id: 'audio_separate', label: 'Tách Âm Thanh', desc: 'Sử dụng Demucs để tách lời và nhạc nền', icon: Mic },
  { id: 'video_ocr', label: 'Nhận diện & Xóa Chữ', desc: 'PaddleOCR + OpenCV', icon: Type },
  { id: 'transcribe', label: 'Nhận diện Giọng nói', desc: 'WhisperX chuyển Audio thành Text', icon: Scissors },
  { id: 'translate', label: 'Dịch thuật', desc: 'Qwen2.5 / GPT-4 dịch sang Tiếng Việt', icon: Languages },
  { id: 'synthesize', label: 'Lồng Tiếng (TTS)', desc: 'OmniVoice tạo giọng mới (clone giọng gốc)', icon: Speech },
  { id: 'lip_sync', label: 'Khớp Khẩu Hình', desc: 'LatentSync', icon: Smile },
  { id: 'mux', label: 'Kết xuất (Muxing)', desc: 'FFmpeg ghép Audio và Video', icon: Film },
];

export default function PipelineProgress({ statusData }) {
  if (!statusData || statusData.status === 'NOT_FOUND') {
    return (
      <div className="glass glass-panel animate-slide-up" style={{ animationDelay: '0.2s', height: '100%' }}>
        <h3>Tiến trình lồng tiếng</h3>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '80%', color: 'var(--text-muted)' }}>
          <Loader2 size={48} className="animate-spin" style={{ marginBottom: '16px', opacity: 0.6 }} />
          <p>Đang tải tiến trình…</p>
        </div>
      </div>
    );
  }

  const { status, results } = statusData;
  // SQLite stores booleans as 0/1 integers
  const lipSyncEnabled = Boolean(statusData.enable_lipsync);
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

  // Stages visible to user — lip_sync is always shown but greyed when disabled
  const visibleStages = STAGES;

  // Calculate active step index for the glowing line
  let activeStepIndex = 0;
  if (isCompleted) {
    activeStepIndex = visibleStages.length - 1;
  } else {
    for (let i = 0; i < visibleStages.length; i++) {
      const stage = visibleStages[i];
      const isLipSync = stage.id === 'lip_sync';
      const disabled = isLipSync && !lipSyncEnabled;
      const stageResult = flatResults[stage.id];
      if (stageResult && stageResult.success) {
        activeStepIndex = i;
      } else if (isProcessing && !disabled && !stageResult) {
        activeStepIndex = i;
        break;
      }
    }
  }
  const progressHeight = Math.min(100, Math.max(0, (activeStepIndex / (visibleStages.length - 1)) * 100));

  return (
    <div className="glass glass-panel animate-slide-up" style={{ animationDelay: '0.2s' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h3>Tiến trình xử lý</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {/* Lip sync indicator badge */}
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            padding: '3px 8px', borderRadius: '12px', fontSize: '0.72rem',
            background: lipSyncEnabled ? 'rgba(99,102,241,0.15)' : 'rgba(255,255,255,0.06)',
            border: `1px solid ${lipSyncEnabled ? 'rgba(99,102,241,0.4)' : 'rgba(255,255,255,0.1)'}`,
            color: lipSyncEnabled ? 'var(--primary)' : 'var(--text-muted)',
          }}>
            <Smile size={11} />
            {lipSyncEnabled ? 'Khớp môi: Bật' : 'Khớp môi: Tắt'}
          </span>
          <span className={`status-badge ${isProcessing ? 'status-processing' : (isCompleted ? 'status-completed' : (isFailed ? 'status-failed' : (status === 'AWAITING_REVIEW' ? 'status-warning' : 'status-pending')))}`}>
            {status}
          </span>
        </div>
      </div>

      <div className="pipeline-steps">
        <div className="pipeline-progress-line" style={{ height: `calc(${progressHeight}% - 30px)` }} />
        {visibleStages.map((stage, idx) => {
          const Icon = stage.icon;
          const isLipSync = stage.id === 'lip_sync';
          const disabled = isLipSync && !lipSyncEnabled;

          const stageResult = flatResults[stage.id] ?? null;
          let stageStatus = 'pending';

          if (disabled) {
            stageStatus = 'disabled';
          } else if (stageResult) {
            stageStatus = stageResult.success ? 'completed' : 'failed';
          } else if (isProcessing) {
            // Find first stage without a result, skipping disabled ones
            const currentIndex = STAGES.findIndex(
              (s) => !flatResults[s.id] && !(s.id === 'lip_sync' && !lipSyncEnabled)
            );
            if (idx === currentIndex) stageStatus = 'active';
          }

          return (
            <div
              key={stage.id}
              className={`step-item ${stageStatus === 'disabled' ? 'pending' : stageStatus}`}
              style={{ opacity: disabled ? 0.38 : 1 }}
            >
              <div className="step-icon" style={disabled ? { background: 'rgba(255,255,255,0.05)' } : {}}>
                {disabled
                  ? <MinusCircle size={16} />
                  : stageStatus === 'completed'
                    ? <Check size={16} />
                    : stageStatus === 'active'
                      ? <Loader2 className="animate-spin" size={16} />
                      : <Icon size={16} />
                }
              </div>
              <div className="step-content">
                <h4 style={{
                  color: disabled ? 'var(--text-muted)'
                    : stageStatus === 'active' ? 'var(--primary)'
                    : stageStatus === 'failed' ? 'var(--error)'
                    : '',
                }}>
                  {stage.label}
                  {disabled && (
                    <span style={{ marginLeft: '6px', fontSize: '0.7rem', fontWeight: 400, color: 'var(--text-muted)' }}>
                      (đã tắt)
                    </span>
                  )}
                </h4>
                <p style={{ color: disabled ? 'var(--text-muted)' : '' }}>
                  {isLipSync && !disabled ? 'LatentSync v1.5 — Khớp khẩu hình theo giọng mới' : stage.desc}
                </p>
                {stageResult && stageResult.success && stageResult.duration != null && (
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
