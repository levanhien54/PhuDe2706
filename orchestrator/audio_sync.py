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
        # time_stretch tự động điều chỉnh tốc độ, giữ nguyên cao độ (pitch)
        y_stretched_2d = pedalboard.time_stretch(y_2d, sr, rate)
        y_stretched = y_stretched_2d[0] # Chuyển lại thành (samples,)
        print(f"[AudioSync] Phase-Vocoder applied successfully. Preserved pitch and formants.")
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
    # 1. Nhận video gốc (-i video)
    # 2. Nhận vocal mới (-i vocal)
    # 3. Nhận nhạc nền (-i bg)
    # 4. Filter_complex: mix 2 audio stream lại (amix)
    # 5. Map: lấy hình ảnh từ video gốc (0:v), âm thanh từ kết quả mix
    # 6. Mã hóa: copy hình ảnh, aac cho âm thanh
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", new_vocal_path,
        "-i", background_path,
        "-filter_complex", "[2:a]aformat=channel_layouts=stereo[bg];[1:a]loudnorm=I=-23:LRA=7:TP=-2,aformat=channel_layouts=stereo[voc];[bg][voc]sidechaincompress=threshold=0.05:ratio=4:attack=5:release=50[bg_ducked];[voc][bg_ducked]amix=inputs=2:duration=longest[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
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
