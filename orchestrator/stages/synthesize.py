import os, time
import numpy as np
import soundfile as sf
from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.tts_client import TTSClient
from orchestrator.audio_sync import stretch_audio
from orchestrator.logger import get_logger

log = get_logger(__name__)

_TTS_VRAM_GB = 4.0


async def run_synthesize(
    job: PipelineJob,
    segments: list[SrtSegment],
    settings: Settings,
    vram: VRAMManager,
) -> StageResult:
    start_time = time.monotonic()
    temp_dir = os.path.join(settings.data_dir, "temp", job.base_name)
    vocal_path = os.path.join(temp_dir, "vocal.wav")
    final_output = os.path.join(temp_dir, "new_vocal.wav")

    try:
        ref_data, sr = sf.read(vocal_path)
    except Exception:
        sr = 22050
        ref_data = np.zeros(0, dtype=np.float32)

    # Lọc danh sách các loa và đoạn có thời lượng dài nhất làm mẫu
    speaker_refs = {}
    for seg in segments:
        if seg.speaker:
            if seg.speaker not in speaker_refs or seg.duration > speaker_refs[seg.speaker].duration:
                speaker_refs[seg.speaker] = seg

    # Trích xuất file mẫu cho từng người nói
    speaker_ref_paths = {}
    if ref_data.size > 0:
        for spk, seg in speaker_refs.items():
            spk_ref_path = os.path.join(temp_dir, f"{spk}_ref.wav")
            start_idx = max(0, int(seg.start * sr))
            end_idx = min(len(ref_data), int(seg.end * sr))
            spk_data = ref_data[start_idx:end_idx]
            if spk_data.size > 0:
                sf.write(spk_ref_path, spk_data, sr)
                speaker_ref_paths[spk] = spk_ref_path

    combined_audio = np.zeros(0, dtype=np.float32)

    try:
        async with vram.slot("tts", _TTS_VRAM_GB):
            client = TTSClient(settings)
            for i, seg in enumerate(segments):
                if not seg.translated:
                    continue
                seg_output = os.path.join(temp_dir, f"seg_{i:04d}.wav")
                seg_ref_path = speaker_ref_paths.get(seg.speaker, vocal_path) if seg.speaker else vocal_path
                
                await client.synthesize(
                    text=seg.translated,
                    reference_audio=seg_ref_path,
                    output_path=seg_output,
                    target_duration=seg.duration,
                )
                stretched_path = os.path.join(temp_dir, f"seg_{i:04d}_stretched.wav")
                stretch_audio(seg_output, stretched_path, seg.duration)

                seg_data, _ = sf.read(stretched_path)
                start_sample = int(seg.start * sr)
                end_sample = start_sample + len(seg_data)
                if end_sample > len(combined_audio):
                    combined_audio = np.pad(combined_audio, (0, end_sample - len(combined_audio)))
                combined_audio[start_sample:end_sample] += seg_data

        # Chống clipping
        combined_audio = np.clip(combined_audio, -1.0, 1.0)
        sf.write(final_output, combined_audio, sr)
        return StageResult(
            stage="synthesize",
            success=True,
            output_path=final_output,
            duration_seconds=time.monotonic() - start_time,
        )
    except Exception as e:
        log.error("synthesize_failed", error=str(e))
        return StageResult(stage="synthesize", success=False, error=str(e))
