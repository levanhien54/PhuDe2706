import os
import soundfile as sf
import pyrubberband as pyrb
import librosa
import subprocess

def stretch_audio(input_path: str, output_path: str, target_duration: float):
    """
    Kéo dãn hoặc nén file âm thanh để đạt được target_duration bằng pyrubberband (thuật toán bảo toàn pitch).
    """
    print(f"[AudioSync] Xử lý file {input_path} -> target: {target_duration}s")
    
    # Load audio
    y, sr = librosa.load(input_path, sr=None)
    current_duration = librosa.get_duration(y=y, sr=sr)
    
    if current_duration <= 0:
        return
    
    # Tính tỉ lệ (rate)
    # rate > 1: chạy nhanh hơn (thời lượng ngắn lại)
    # rate < 1: chạy chậm lại (thời lượng dài ra)
    rate = current_duration / target_duration
    
    print(f" - Original duration: {current_duration:.2f}s, Rate: {rate:.4f}")
    
    # Dùng pyrubberband để stretch (bảo toàn cao độ tốt hơn librosa.effects.time_stretch)
    y_stretched = pyrb.time_stretch(y, sr, rate)
    
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
        "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=longest[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        output_video_path
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        print(f"[FFmpeg] Render thành công: {output_video_path}")
    except subprocess.CalledProcessError as e:
        print(f"[FFmpeg] Lỗi khi render: {e}")

if __name__ == "__main__":
    # Test script if needed
    pass
