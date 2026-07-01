import os
import shutil
import soundfile as sf
import subprocess
import numpy as np


def _resolve_ffmpeg() -> str:
    """Resolve the ffmpeg binary robustly so we never depend on PATH being set up.
    Order: FFMPEG_BINARY env -> PATH -> bundled binaries shipped with the project."""
    env_bin = os.environ.get("FFMPEG_BINARY")
    if env_bin and os.path.exists(env_bin):
        return env_bin
    found = shutil.which("ffmpeg")
    if found:
        return found
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for cand in (
        os.path.join(project_root, "ffmpeg_extracted", "ffmpeg-master-latest-win64-gpl", "bin", "ffmpeg.exe"),
        os.path.join(project_root, "ffmpeg.exe"),
    ):
        if os.path.exists(cand):
            return cand
    return "ffmpeg"  # last resort — let subprocess raise a clear FileNotFoundError

def stretch_audio(input_path: str, output_path: str, target_duration: float) -> None:
    """
    Kéo dãn hoặc nén file âm thanh để đạt được target_duration.

    Thuật toán chọn bằng env TIMESTRETCH_ALGO:
      - "phasevocoder" (mặc định): Pedalboard (lõi Rubberband C++), chất lượng cao.
      - "wsola": WSOLA qua gói `audiotsm` — tự nhiên hơn, ít méo pha; fallback về Pedalboard/librosa
        nếu chưa cài audiotsm.
    Sau khi kéo dãn, áp Vocal Mastering (Pedalboard) nếu có, cho mọi thuật toán.
    """
    print(f"[AudioSync] Xử lý file {input_path} -> target: {target_duration}s")

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if target_duration <= 0:
        raise ValueError(f"target_duration must be positive, got {target_duration}")

    # Load audio
    try:
        y, sr = sf.read(input_path, dtype='float32', always_2d=False)
        if y.ndim > 1:
            y = y.mean(axis=1)  # stereo → mono
    except Exception:
        # soundfile can't decode compressed formats (mp3/m4a) — fall back to librosa/audioread
        import librosa
        y, sr = librosa.load(input_path, sr=None, mono=True)
    current_duration = len(y) / sr

    if current_duration <= 0:
        sf.write(output_path, y, sr)  # honor the output contract (avoid downstream FileNotFoundError)
        return

    # Tính tỉ lệ (rate)
    # rate > 1: chạy nhanh hơn (thời lượng ngắn lại)
    # rate < 1: chạy chậm lại (thời lượng dài ra)
    rate = current_duration / target_duration

    # Clamp to avoid extreme artifacts (pyrubberband degrades past ~2.5x)
    MAX_RATE = 2.5
    MIN_RATE = 0.4
    if rate > MAX_RATE:
        print(f"[AudioSync] Warning: stretch rate {rate:.2f} clamped to {MAX_RATE} (segment too long for target)")
        rate = MAX_RATE
    elif rate < MIN_RATE:
        print(f"[AudioSync] Warning: stretch rate {rate:.2f} clamped to {MIN_RATE} (segment too short for target)")
        rate = MIN_RATE

    print(f" - Original duration: {current_duration:.2f}s, Rate: {rate:.4f}")

    # (channels, samples) cho Pedalboard/WSOLA
    y_2d = y.reshape(1, -1)
    algo = os.environ.get("TIMESTRETCH_ALGO", "phasevocoder").strip().lower()

    y_stretched = None
    if algo == "wsola":
        try:
            import audiotsm
            from audiotsm.io.array import ArrayReader, ArrayWriter
            print("[AudioSync] Using WSOLA (audiotsm) for time stretching...")
            reader = ArrayReader(y_2d)
            writer = ArrayWriter(channels=1)
            audiotsm.wsola(1, speed=rate).run(reader, writer)
            y_stretched = np.asarray(writer.data[0], dtype='float32')
        except ImportError:
            print("[AudioSync] CẢNH BÁO: audiotsm chưa cài (WSOLA), fallback về Pedalboard/librosa...")

    if y_stretched is None:
        try:
            import pedalboard
            print("[AudioSync] Using Pedalboard (Rubberband Phase-Vocoder) for high-quality time stretching...")
            y_stretched = pedalboard.time_stretch(y_2d, sr, rate)[0]  # (samples,)
        except ImportError:
            print("[AudioSync] CẢNH BÁO: Thư viện pedalboard chưa được cài đặt, fallback về librosa (chất lượng kém hơn)...")
            import librosa
            y_stretched = librosa.effects.time_stretch(y, rate=rate)

    # Vocal Mastering Chain (Làm rõ giọng, nén âm lượng, chống rè) — áp dụng nếu có pedalboard,
    # cho mọi thuật toán stretch (kể cả WSOLA). Nếu chưa cài pedalboard thì bỏ qua.
    try:
        import pedalboard
        board = pedalboard.Pedalboard([
            pedalboard.HighpassFilter(cutoff_frequency_hz=80),  # Cắt tiếng lụp bụp ở dải trầm
            pedalboard.Compressor(threshold_db=-15, ratio=3.0, attack_ms=5.0, release_ms=50.0), # Làm đều âm lượng giọng
            pedalboard.Limiter(threshold_db=-1.5) # Chống rè (clipping)
        ])
        y_stretched = board(np.asarray(y_stretched, dtype='float32').reshape(1, -1), sr)[0]
        print("[AudioSync] Vocal Mastering applied.")
    except ImportError:
        pass

    # Ghi ra file
    sf.write(output_path, y_stretched, sr)
    print(f" - Đã lưu output: {output_path}")

def mix_audio_to_video(video_path: str, new_vocal_path: str, background_path: str,
                       output_video_path: str, bg_denoise: bool = True) -> None:
    """
    Sử dụng FFmpeg để mix audio giọng nói mới và âm thanh nền, sau đó ghép vào video gốc.
    bg_denoise: khử nhiễu nhẹ trên track nền (giữ nhạc/hiệu ứng, bỏ ù/hiss).
    """
    print(f"[FFmpeg] Đang mix và render video cuối cùng...")

    for path in [video_path, new_vocal_path, background_path]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing input for mix_audio_to_video: {path}")

    # Background chain: optionally strip subsonic rumble + broadband hiss while preserving
    # music/SFX (gentle spectral denoise — NOT a speech-RNN denoiser, which would eat music).
    bg_chain = "[2:a]aformat=channel_layouts=stereo"
    if bg_denoise:
        bg_chain += ",highpass=f=50,afftdn=nr=12:nf=-25"
    bg_chain += "[bg];"

    # Lệnh FFmpeg:
    # - afftdn (voice): Khử nhiễu tĩnh điện từ quá trình AI TTS
    # - acompressor: Cân bằng giọng nói
    # - sidechaincompress (bg_ducking): nhạc nền lùi tự nhiên khi có thoại
    # - amix normalize=0: để sidechain tự kiểm soát mức nền, tránh amix chia đôi âm lượng và
    #   renormalize lúc im lặng (làm nền phình lên giữa các câu)
    # - loudnorm (chuẩn Web): I=-14 LUFS (YouTube/Tiktok) — chạy MỘT lần trên bản mix cuối
    # asplit the processed voice: one copy is mixed in, the other KEYS the sidechain ducking.
    # (A named filter pad can't be consumed twice, so [voc] must be duplicated explicitly.)
    filter_complex = (
        bg_chain +
        "[1:a]afftdn=nf=-20,highpass=f=80,acompressor=threshold=-15dB:ratio=3:attack=5:release=50,aformat=channel_layouts=stereo,asplit=2[voc][vockey];"
        "[bg][vockey]sidechaincompress=threshold=0.063:ratio=4:attack=5:release=100[bg_ducked];"  # 0.063 amplitude ~ -24dB
        # apad + -shortest below clamp the mixed audio to EXACTLY the (copied) video length:
        # pad with silence if the dub/bg is shorter, trim if a dub tail runs past the video end,
        # so the output never has an audio track longer/shorter than the video.
        "[voc][bg_ducked]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-14:LRA=11:TP=-1.5,apad[a]"
    )
    cmd = [
        _resolve_ffmpeg(), "-y",
        "-i", video_path,
        "-i", new_vocal_path,
        "-i", background_path,
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",  # standard broadcast rate (loudnorm otherwise emits an odd 96kHz)
        "-shortest",     # end at the (finite) video stream; apad keeps audio >= video first
        output_video_path
    ]

    # encoding+errors guard: ffmpeg stderr referencing Korean/Japanese filenames must not
    # raise UnicodeDecodeError under a non-UTF-8 Windows code page and mask the real error.
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg mux failed (exit {result.returncode}):\n{result.stderr[-2000:]}"
        )
    print(f"[FFmpeg] Render thành công: {output_video_path}")

if __name__ == "__main__":
    # Test script if needed
    pass
