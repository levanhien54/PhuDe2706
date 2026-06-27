import asyncio
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
        with sf.SoundFile(vocal_path) as f:
            sr = f.samplerate
            total_frames = f.frames
            has_audio = True
    except Exception:
        sr = 22050
        total_frames = 0
        has_audio = False

    # Build per-speaker reference clips from the longest segment per speaker
    speaker_refs: dict[str, SrtSegment] = {}
    for seg in segments:
        if seg.speaker:
            if seg.speaker not in speaker_refs or seg.duration > speaker_refs[seg.speaker].duration:
                speaker_refs[seg.speaker] = seg

    speaker_ref_paths: dict[str, str] = {}
    if has_audio:
        for spk, seg in speaker_refs.items():
            spk_ref_path = os.path.join(temp_dir, f"{spk}_ref.wav")
            start_idx = max(0, int(seg.start * sr))
            end_idx = min(total_frames, int(seg.end * sr))
            n_frames = end_idx - start_idx
            if n_frames > 0:
                with sf.SoundFile(vocal_path) as f:
                    f.seek(start_idx)
                    spk_data = f.read(n_frames)
                sf.write(spk_ref_path, spk_data, sr)
                speaker_ref_paths[spk] = spk_ref_path

    combined_audio = np.zeros(0, dtype=np.float32)

    try:
        async with vram.slot("tts", _TTS_VRAM_GB):
            client = TTSClient(settings)
            sem = asyncio.Semaphore(2)

            async def _synth_seg(i, seg):
                if not seg.translated:
                    return None
                if seg.duration <= 0:
                    log.warning("skip_zero_duration_segment", index=i, start=seg.start, end=seg.end)
                    return None
                async with sem:
                    if not has_audio:
                        seg_ref = None
                    elif seg.speaker:
                        seg_ref = speaker_ref_paths.get(seg.speaker, vocal_path)
                    else:
                        seg_ref = vocal_path
                    seg_output = os.path.join(temp_dir, f"seg_{i:04d}.wav")
                    await client.synthesize(
                        text=seg.translated,
                        reference_audio=seg_ref,
                        output_path=seg_output,
                        target_duration=seg.duration,
                        language=job.target_language,
                    )
                    stretched_path = os.path.join(temp_dir, f"seg_{i:04d}_stretched.wav")
                    await asyncio.to_thread(stretch_audio, seg_output, stretched_path, seg.duration)
                    seg_data, _ = await asyncio.to_thread(sf.read, stretched_path)
                    return (i, seg, seg_data)

            tasks = [_synth_seg(i, seg) for i, seg in enumerate(segments)]
            results = await asyncio.gather(*tasks)

            for _, seg, seg_data in sorted(
                (r for r in results if r is not None), key=lambda x: x[0]
            ):
                start_sample = int(seg.start * sr)
                end_sample = start_sample + len(seg_data)
                if end_sample > len(combined_audio):
                    combined_audio = np.pad(combined_audio, (0, end_sample - len(combined_audio)))
                combined_audio[start_sample:end_sample] += seg_data

        if combined_audio.size == 0:
            log.error("synthesize_no_audio", reason="all segments skipped or failed")
            return StageResult(stage="synthesize", success=False, error="No audio synthesized (all segments empty)")

        peak = np.max(np.abs(combined_audio))
        if peak > 1.0:
            combined_audio = combined_audio / peak

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
