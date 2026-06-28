import os
import soundfile as sf
import subprocess
import numpy as np

def stretch_audio(input_path: str, output_path: str, target_duration: float):
    """
    Kéo dãn hoặc nén file âm thanh để đạt được target_duration bằng Pedalboard (chứa lõi thuật toán C++ của Rubberband).
    Chất lượng cao, không bị méo tiếng như librosa, và không phụ thuộc vào ứng dụng ngoài.
    """
    print(f"[AudioSync] Xử lý file {input_path} -> target: {target_duration}s")
    
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
    
    # Pedalboard đòi hỏi mảng đầu vào có dạng (channels, samples)
    y_2d = y.reshape(1, -1)
    
    try:
        import pedalboard
        print(f"[AudioSync] Using Pedalboard (Rubberband Phase-Vocoder) for high-quality time stretching...")
        
        # 1. Kéo dãn thời gian (Phase Vocoder)
        y_stretched_2d = pedalboard.time_stretch(y_2d, sr, rate)
        
        # 2. Vocal Mastering Chain (Làm rõ giọng, nén âm lượng, chống rè)
        board = pedalboard.Pedalboard([
            pedalboard.HighpassFilter(cutoff_frequency_hz=80),  # Cắt tiếng lụp bụp ở dải trầm
            pedalboard.Compressor(threshold_db=-15, ratio=3.0, attack_ms=5.0, release_ms=50.0), # Làm đều âm lượng giọng
            pedalboard.Limiter(threshold_db=-1.5) # Chống rè (clipping)
        ])
        y_stretched_2d = board(y_stretched_2d, sr)
        
        y_stretched = y_stretched_2d[0] # Chuyển lại thành (samples,)
        print(f"[AudioSync] Phase-Vocoder & Vocal Mastering applied successfully.")
    except ImportError:
        print("[AudioSync] CẢNH BÁO: Thư viện pedalboard chưa được cài đặt, fallback về librosa (chất lượng kém hơn)...")
        import librosa
        y_stretched = librosa.effects.time_stretch(y, rate=rate)
    
    # Ghi ra file
    sf.write(output_path, y_stretched, sr)
    print(f" - Đã lưu output: {output_path}")

def mix_audio_to_video(video_path: str, new_vocal_path: str, background_path: str, output_video_path: str):
    """
    Sử dụng FFmpeg để mix audio giọng nói mới và âm thanh nền, sau đó ghép vào video gốc.
    """
    print(f"[FFmpeg] Đang mix và render video cuối cùng...")
    
    # Lệnh FFmpeg:
    # - afftdn: Khử nhiễu tĩnh điện từ quá trình AI TTS
    # - acompressor: Cân bằng giọng nói
    # - sidechaincompress (bg_ducking): threshold=-18dB, ratio=4 để nhạc nền lùi tự nhiên
    # - loudnorm (chuẩn Web): I=-14 LUFS (YouTube/Tiktok standard) thay vì -23 LUFS (TV cũ)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", new_vocal_path,
        "-i", background_path,
        "-filter_complex", 
        "[2:a]aformat=channel_layouts=stereo[bg];"
        "[1:a]afftdn=nf=-20,highpass=f=80,acompressor=threshold=-15dB:ratio=3:attack=5:release=50,loudnorm=I=-14:LRA=7:TP=-1.5,aformat=channel_layouts=stereo[voc];"
        "[bg][voc]sidechaincompress=threshold=0.063:ratio=4:attack=5:release=100[bg_ducked];" # 0.063 amplitude ~ -24dB
        "[voc][bg_ducked]amix=inputs=2:duration=longest,loudnorm=I=-14:LRA=11:TP=-1.5[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        output_video_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg mux failed (exit {result.returncode}):\n{result.stderr[-2000:]}"
        )
    print(f"[FFmpeg] Render thành công: {output_video_path}")

if __name__ == "__main__":
    # Test script if needed
    pass
