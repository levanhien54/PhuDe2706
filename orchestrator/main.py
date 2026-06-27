import asyncio
import os
import httpx
import json
from audio_sync import mix_audio_to_video
from video_process import remove_watermark_from_video
# Đọc cấu hình môi trường từ Docker
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
WHISPERX_API = os.getenv("WHISPERX_API", "http://localhost:8001")
DEMUCS_API = os.getenv("DEMUCS_API", "http://localhost:8000")
TTS_API = os.getenv("TTS_API", "http://localhost:9880")
OMNIVOICE_API = os.getenv("OMNIVOICE_API", "http://localhost:3900")
TTS_ENGINE = os.getenv("TTS_ENGINE", "omnivoice")

DATA_DIR = "/app/data"
INPUT_DIR = os.path.join(DATA_DIR, "input")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")
TEMP_DIR = os.path.join(DATA_DIR, "temp")

async def separate_audio(video_path: str, filename: str) -> dict:
    """Gọi API Demucs để tách âm."""
    print(f"[Demucs] Đang tách âm: {filename}")
    # Chú ý: Ở hệ thống thực tế, dùng httpx.post để gửi file tới Demucs API
    # Trong demo/pipeline chuẩn:
    vocal_path = os.path.join(TEMP_DIR, f"{filename}_vocal.wav")
    bg_path = os.path.join(TEMP_DIR, f"{filename}_bg.wav")
    
    # Mocking delay / API call
    # async with httpx.AsyncClient() as client:
    #    response = await client.post(f"{DEMUCS_API}/separate", files={"file": open(video_path, "rb")}, timeout=None)
    await asyncio.sleep(2) 
    
    print(f"[Demucs] Tách âm xong: {vocal_path}, {bg_path}")
    return {"vocal": vocal_path, "background": bg_path}

async def speech_to_text(vocal_path: str) -> list:
    """Gọi API WhisperX để lấy STT (kèm Word-level timestamp)."""
    print(f"[WhisperX] Bắt đầu nhận diện giọng nói...")
    
    # async with httpx.AsyncClient() as client:
    #    response = await client.post(f"{WHISPERX_API}/transcribe", files={"file": open(vocal_path, "rb")}, timeout=None)
    await asyncio.sleep(2)
    
    # Giả lập kết quả trả về từ WhisperX
    mock_srt = [
        {"start": 0.0, "end": 2.5, "text": "Hello everyone, welcome to the channel."},
        {"start": 2.5, "end": 5.0, "text": "Today we are building an AI pipeline."}
    ]
    print(f"[WhisperX] Nhận diện xong: {len(mock_srt)} câu.")
    return mock_srt

async def translate_text(srt_data: list) -> list:
    """Sử dụng Ollama để dịch nội dung."""
    print(f"[Ollama] Bắt đầu dịch thuật (Mô hình Qwen2.5/Llama3)...")
    
    translated_srt = []
    async with httpx.AsyncClient() as client:
        for line in srt_data:
            prompt = f"Dịch câu tiếng Anh sau sang tiếng Việt một cách tự nhiên. Chỉ trả về kết quả dịch, không giải thích: '{line['text']}'"
            try:
                # payload = {
                #     "model": "qwen2.5:14b", # Hoặc model bạn đã cài (e.g., llama3.1)
                #     "prompt": prompt,
                #     "stream": False
                # }
                # response = await client.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=60.0)
                # trans_text = response.json().get("response", "").strip()
                
                # Mocking
                trans_text = "Xin chào mọi người, chào mừng đến với kênh." if "Hello" in line["text"] else "Hôm nay chúng ta sẽ xây dựng một hệ thống AI."
                await asyncio.sleep(0.5)
                
                translated_srt.append({
                    "start": line["start"],
                    "end": line["end"],
                    "text": trans_text
                })
            except Exception as e:
                print(f"[Ollama] Lỗi khi gọi Ollama: {e}")
                
    print("[Ollama] Dịch thuật hoàn tất.")
    return translated_srt

async def rewrite_comments(json_path: str):
    """Viết lại file comment."""
    if not os.path.exists(json_path):
        return
    print(f"[Ollama] Viết lại các bình luận từ {json_path}")
    # Logic tương tự translate_text nhưng áp dụng cho mảng json
    await asyncio.sleep(1)

async def text_to_speech(translated_srt: list, original_vocal_path: str, filename: str) -> str:
    """Gọi GPT-SoVITS để clone giọng và sinh âm thanh."""
    print("[TTS] Đang sinh giọng nói (Voice Cloning)...")
    
    final_vocal_path = os.path.join(TEMP_DIR, f"{filename}_new_vocal.wav")
    
    # Pipeline TTS cần:
    # 1. Trích xuất âm thanh tham chiếu 5s-10s từ original_vocal_path (để lấy âm sắc).
    # 2. Vòng lặp:
    #    - Gọi TTS API tạo âm thanh tiếng Việt.
    #    - Đo độ dài.
    #    - Dùng audio_sync.stretch_audio() để ép độ dài trùng với (end - start).
    # 3. Nối các đoạn âm thanh lại theo đúng vị trí timestamp.
    # 4. Xuất ra final_vocal_path
    
    await asyncio.sleep(3) # Mock processing time
    print(f"[TTS] Sinh âm thanh hoàn tất: {final_vocal_path}")
    return final_vocal_path

async def text_to_speech_omnivoice(translated_srt: list, original_vocal_path: str, filename: str) -> str:
    """Gọi OmniVoice-Studio API để clone giọng (Zero-shot) và sinh âm thanh."""
    print(f"[TTS] Đang sinh giọng nói bằng OmniVoice (Zero-shot Cloning) trên server {OMNIVOICE_API}...")
    
    final_vocal_path = os.path.join(TEMP_DIR, f"{filename}_new_vocal.wav")
    
    # Thực tế sẽ post dữ liệu audio sample gốc (original_vocal_path) và text tới API
    # async with httpx.AsyncClient() as client:
    #     response = await client.post(f"{OMNIVOICE_API}/v1/audio/speech", ...)
    
    await asyncio.sleep(3) # Mock processing time
    print(f"[TTS] OmniVoice sinh âm thanh hoàn tất: {final_vocal_path}")
    return final_vocal_path

async def process_video_pipeline(video_filename: str):
    """Luồng (Pipeline) chính xử lý 1 video."""
    video_path = os.path.join(INPUT_DIR, video_filename)
    json_path = os.path.join(INPUT_DIR, video_filename.replace(".mp4", ".json"))
    base_name = os.path.splitext(video_filename)[0]
    
    print(f"=== Bắt đầu xử lý Video: {video_filename} ===")
    
    # 1. Tách âm (Demucs) và Xóa Watermark (chạy song song)
    video_no_watermark_path = os.path.join(TEMP_DIR, f"{base_name}_cleaned.mp4")
    
    audio_task = asyncio.create_task(separate_audio(video_path, base_name))
    watermark_task = asyncio.to_thread(remove_watermark_from_video, video_path, video_no_watermark_path)
    
    # Chờ cả 2 hoàn tất
    audio_files, _ = await asyncio.gather(audio_task, watermark_task)
    
    vocal_path = audio_files["vocal"]
    bg_path = audio_files["background"]
    
    # 2. Nhận diện giọng nói (WhisperX)
    # Lưu ý: Ở kiến trúc 16GB VRAM, sau bước này có thể thêm logic gửi API unload WhisperX (nếu API support) 
    # để giải phóng VRAM cho Ollama/TTS. Hoặc để hệ thống tự quản lý.
    original_srt = await speech_to_text(vocal_path)
    
    # 3. Dịch thuật & Viết lại bình luận (Ollama) - Chạy song song (Asynchronous)
    translate_task = asyncio.create_task(translate_text(original_srt))
    comment_task = asyncio.create_task(rewrite_comments(json_path))
    
    translated_srt, _ = await asyncio.gather(translate_task, comment_task)
    
    # 4. Text-to-Speech
    if TTS_ENGINE == "omnivoice":
        new_vocal_path = await text_to_speech_omnivoice(translated_srt, vocal_path, base_name)
    else:
        new_vocal_path = await text_to_speech(translated_srt, vocal_path, base_name)
    
    # 5. Mix Audio và Render Video cuối cùng (FFmpeg)
    output_video_path = os.path.join(OUTPUT_DIR, f"{base_name}_dubbed.mp4")
    mix_audio_to_video(video_no_watermark_path, new_vocal_path, bg_path, output_video_path)
    
    print(f"=== Hoàn tất xử lý: {output_video_path} ===")

async def main():
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    videos = [f for f in os.listdir(INPUT_DIR) if f.endswith(".mp4")]
    if not videos:
        print(f"Không tìm thấy video nào trong thư mục {INPUT_DIR}.")
        print("Vui lòng thả file vào ./data/input và chạy lại.")
        return
    
    for video in videos:
        await process_video_pipeline(video)

if __name__ == "__main__":
    asyncio.run(main())
