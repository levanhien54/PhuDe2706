import asyncio
import os, time
import numpy as np
import soundfile as sf
from orchestrator.models import PipelineJob, StageResult, SrtSegment
from orchestrator.config import Settings
from orchestrator.vram_manager import VRAMManager
from orchestrator.clients.tts_client import TTSClient
from orchestrator.audio_sync import stretch_audio
from orchestrator.voice_library import get_voice_ref
from orchestrator.logger import get_logger

log = get_logger(__name__)

_TTS_VRAM_GB = 4.0


def _write_ref_clip(vocal_path: str, start_s: float, end_s: float, sr: int,
                    total_frames: int, dest: str) -> bool:
    """Extract [start_s, end_s) of the vocal track to `dest`. Returns False if the span is empty."""
    start_idx = max(0, int(start_s * sr))
    end_idx = min(total_frames, int(end_s * sr))
    n = end_idx - start_idx
    if n <= 0:
        return False
    with sf.SoundFile(vocal_path) as f:
        f.seek(start_idx)
        data = f.read(n)
    sf.write(dest, data, sr)
    return True


_REF_CLIP_MAX_S = 10.0  # cap reference clips to OmniVoice's recommended 3–10s range


def _ref_text_for_cap(seg, cap: float = _REF_CLIP_MAX_S) -> str:
    """Transcript matching the first ~`cap` seconds of seg's audio. When the ref clip is capped
    shorter than the segment, the full transcript no longer describes the clip, so truncate it
    proportionally (by word count) to keep ref_text length-matched to the ref audio."""
    text = (seg.text or "").strip()
    if text and seg.duration > cap > 0:
        words = text.split()
        n = max(1, round(len(words) * cap / seg.duration))
        text = " ".join(words[:n])
    return text


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

    if os.path.exists(final_output):
        log.info("synthesize_resume", msg="Found existing new_vocal.wav, skipping inference")
        return StageResult(
            stage="synthesize",
            success=True,
            output_path=final_output,
            duration_seconds=0,
        )

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

    # speaker -> (ref_clip_path, matching_transcript). One dict so path and text can't desync.
    # Clip capped to _REF_CLIP_MAX_S and its transcript truncated to match.
    speaker_refs_built: dict[str, tuple[str, str]] = {}
    if has_audio:
        for spk, seg in speaker_refs.items():
            spk_ref_path = os.path.join(temp_dir, f"{spk}_ref.wav")
            if _write_ref_clip(vocal_path, seg.start, min(seg.end, seg.start + _REF_CLIP_MAX_S),
                               sr, total_frames, spk_ref_path):
                speaker_refs_built[spk] = (spk_ref_path, _ref_text_for_cap(seg))

    # Global fallback reference clip — the longest segment overall, capped to ~10s. Used for
    # short / speaker-less lines so we NEVER hand the entire (multi-minute) vocal track to the
    # TTS engine as a zero-shot reference (wrong, and can exceed the model's reference limit).
    fallback_ref: str | None = None
    fallback_ref_text: str | None = None
    if has_audio and segments:
        longest = max(segments, key=lambda s: s.duration)
        gpath = os.path.join(temp_dir, "global_ref.wav")
        if _write_ref_clip(vocal_path, longest.start, min(longest.end, longest.start + _REF_CLIP_MAX_S),
                           sr, total_frames, gpath):
            fallback_ref = gpath
            fallback_ref_text = _ref_text_for_cap(longest)

    # Single-voice mode + a chosen country preset: clone THAT voice for the whole video instead
    # of the video's own audio (the default when no preset is picked). Used as the global ref below.
    if settings.voice_mode == "single" and getattr(settings, "voice_preset", ""):
        preset = get_voice_ref(settings.voice_preset)
        if preset:
            fallback_ref, fallback_ref_text = preset
            log.info("voice_preset_selected", id=settings.voice_preset)
        else:
            log.warning("voice_preset_not_found", id=settings.voice_preset)

    combined_audio = np.zeros(0, dtype=np.float32)

    try:
        tts_conc = max(1, settings.tts_concurrency)
        async with vram.slot("tts", _TTS_VRAM_GB * tts_conc):
            client = TTSClient(settings)
            # Concurrency must match the OmniVoice replica pool size; the server hands each
            # request its own replica so these genuinely run in parallel (no shared lock).
            sem = asyncio.Semaphore(tts_conc)
            # "single" = one consistent narrator voice (global ref) for every line;
            # "multi" (default) = clone each detected speaker / each segment's own voice.
            single_voice = (settings.voice_mode == "single")
            log.info("synthesize_voice_mode", mode=settings.voice_mode, speakers=len(speaker_refs_built))

            async def _synth_seg(i, seg):
                if not seg.translated:
                    return None
                if seg.duration <= 0:
                    log.warning("skip_zero_duration_segment", index=i, start=seg.start, end=seg.end)
                    return None
                async with sem:
                    # Reference clip + its matching transcript. Providing ref_text lets OmniVoice
                    # skip its own ASR auto-transcribe (needs libtorchcodec; failing that, cloning
                    # is silently lost). Default to the speaker/global fallback, then prefer THIS
                    # segment's own audio (best clone) when it's long enough to be a good sample.
                    # Single-voice: always the one global reference. Multi: speaker ref, then prefer
                    # THIS segment's own audio when it's long enough to be a good clone sample.
                    seg_ref, seg_ref_text = fallback_ref, fallback_ref_text
                    if not single_voice:
                        if seg.speaker and seg.speaker in speaker_refs_built:
                            seg_ref, seg_ref_text = speaker_refs_built[seg.speaker]
                        if has_audio and seg.duration >= 1.5:
                            dynamic_ref_path = os.path.join(temp_dir, f"seg_{i:04d}_ref.wav")
                            try:
                                success = await asyncio.to_thread(
                                    _write_ref_clip, vocal_path, seg.start,
                                    min(seg.end, seg.start + _REF_CLIP_MAX_S), sr, total_frames, dynamic_ref_path
                                )
                                if success:
                                    seg_ref, seg_ref_text = dynamic_ref_path, _ref_text_for_cap(seg)
                            except Exception as e:
                                log.warning("dynamic_ref_failed", index=i, error=str(e))
                    # A ref clip without a transcript would force OmniVoice's heavy ASR fallback;
                    # drop the reference instead (synthesize uncloned rather than load Whisper).
                    if not seg_ref_text:
                        seg_ref = None
                    seg_output = os.path.join(temp_dir, f"seg_{i:04d}.wav")
                    await client.synthesize(
                        text=seg.translated,
                        reference_audio=seg_ref,
                        ref_text=seg_ref_text,
                        output_path=seg_output,
                        target_duration=seg.duration,
                        language=job.target_language,
                    )
                    stretched_path = os.path.join(temp_dir, f"seg_{i:04d}_stretched.wav")
                    await asyncio.to_thread(stretch_audio, seg_output, stretched_path, seg.duration)
                    # Capture the ACTUAL sample rate of the synthesized audio (e.g. OmniVoice=24000),
                    # not the source vocal rate — otherwise timeline math + output header desync (wrong speed/pitch).
                    seg_data, seg_sr = await asyncio.to_thread(sf.read, stretched_path, dtype="float32")
                    return (i, seg, seg_data, seg_sr)

            tasks = [_synth_seg(i, seg) for i, seg in enumerate(segments)]
            # return_exceptions: one failed segment must not abort the whole stage
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
            results = []
            for r in raw_results:
                if isinstance(r, Exception):
                    log.warning("segment_synth_failed", error=str(r))
                elif r is not None:
                    results.append(r)

            # Output timeline sample rate = the synthesized audio's real rate (consistent for all segments).
            seg_srs = [r[3] for r in results]
            out_sr = max(set(seg_srs), key=seg_srs.count) if seg_srs else sr
            if seg_srs and len(set(seg_srs)) > 1:
                log.warning("mixed_segment_sample_rates", rates=sorted(set(seg_srs)), using=out_sr)

            def _to_out_sr(data, src_sr):
                if src_sr == out_sr:
                    return np.asarray(data, dtype=np.float32)
                import librosa
                return librosa.resample(np.asarray(data, dtype=np.float32), orig_sr=src_sr, target_sr=out_sr)

            # Pre-compute placements (time-ordered), then allocate the buffer ONCE.
            placements = []
            for i, seg, seg_data, seg_sr in sorted(results, key=lambda x: x[0]):
                data = _to_out_sr(seg_data, seg_sr)
                placements.append((int(seg.start * out_sr), data))
            placements.sort(key=lambda p: p[0])

            if placements:
                # Time-stretch is rate-clamped, so a segment can stay longer than its slot.
                # Trim each so it cannot bleed into the next segment's start — additive overlap
                # would double/garble the speech. The last segment keeps its natural length.
                for idx in range(len(placements) - 1):
                    start_sample, data = placements[idx]
                    max_len = max(0, placements[idx + 1][0] - start_sample)
                    if len(data) > max_len:
                        placements[idx] = (start_sample, data[:max_len])
                total_len = max(start + len(data) for start, data in placements)
                combined_audio = np.zeros(total_len, dtype=np.float32)
                for start_sample, data in placements:
                    combined_audio[start_sample:start_sample + len(data)] += data

        if combined_audio.size == 0:
            log.error("synthesize_no_audio", reason="all segments skipped or failed")
            return StageResult(stage="synthesize", success=False, error="No audio synthesized (all segments empty)")

        peak = np.max(np.abs(combined_audio))
        if peak > 1.0:
            combined_audio = combined_audio / peak

        sf.write(final_output, combined_audio, out_sr)
        return StageResult(
            stage="synthesize",
            success=True,
            output_path=final_output,
            duration_seconds=time.monotonic() - start_time,
        )
    except Exception as e:
        log.error("synthesize_failed", error=str(e))
        return StageResult(stage="synthesize", success=False, error=str(e))
