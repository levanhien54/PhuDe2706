import os
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from functools import lru_cache


class Settings(BaseSettings):
    # Service endpoints
    ollama_host: str = Field("http://127.0.0.1:11434", validation_alias="OLLAMA_HOST")
    vllm_host: str = Field("http://127.0.0.1:8080", validation_alias="VLLM_HOST")
    whisperx_api: str = Field("http://127.0.0.1:8001", validation_alias="WHISPERX_API")
    demucs_api: str = Field("local", validation_alias="DEMUCS_API")
    tts_api: str = Field("http://127.0.0.1:9880", validation_alias="TTS_API")
    omnivoice_api: str = Field("http://127.0.0.1:3900", validation_alias="OMNIVOICE_API")
    lipsync_api: str = Field("http://127.0.0.1:8010", validation_alias="LIPSYNC_API")

    # Engine selection
    tts_engine: str = Field("omnivoice", validation_alias="TTS_ENGINE")
    # TTS voice mode: "multi" = clone each detected speaker/segment (đa nhân vật);
    # "single" = one consistent narrator voice for the whole video (một giọng đọc).
    voice_mode: str = Field("multi", validation_alias="VOICE_MODE")
    # Optional preset voice id (from the voices/ library) to clone in single-voice mode.
    # Empty = clone the video's own main speaker (default audio).
    voice_preset: str = Field("", validation_alias="VOICE_PRESET")
    llm_backend: str = Field("ollama", validation_alias="LLM_BACKEND")
    llm_model: str = Field("qwen2.5:14b", validation_alias="LLM_MODEL")
    # ASR model served by whisperx-service. large-v3-turbo (~3GB, MIT) is the v2.0 default:
    # ~50% faster than large-v3 at near-parity WER. Set WHISPER_MODEL=large-v3 to revert.
    whisper_model: str = Field("large-v3-turbo", validation_alias="WHISPER_MODEL")
    vram_profile: str = Field("16gb", validation_alias="VRAM_PROFILE")
    enable_lipsync: bool = Field(False, validation_alias="ENABLE_LIPSYNC")
    enable_ocr: bool = Field(False, validation_alias="ENABLE_OCR")
    ocr_mode: str = Field("blur", validation_alias="OCR_MODE")
    enable_propainter: bool = Field(False, validation_alias="ENABLE_PROPAINTER")
    enable_cpu_offload: bool = Field(False, validation_alias="ENABLE_CPU_OFFLOAD")
    enable_kvcached: bool = Field(False, validation_alias="ENABLE_KVCACHED")

    # Paths
    data_dir: str = Field("./data", validation_alias="DATA_DIR")

    @field_validator("data_dir")
    @classmethod
    def _abs_data_dir(cls, v: str) -> str:
        return os.path.abspath(v)

    # Tuning
    http_timeout: float = Field(300.0, validation_alias="HTTP_TIMEOUT")
    http_retries: int = Field(3, validation_alias="HTTP_RETRIES")
    ocr_fps: float = Field(2.0, validation_alias="OCR_FPS")
    tts_max_ratio: float = Field(1.5, validation_alias="TTS_MAX_RATIO")
    ocr_batch_size: int = Field(4, validation_alias="OCR_BATCH_SIZE")
    # Number of concurrent TTS requests the orchestrator dispatches. Must match the
    # OmniVoice replica count (OMNIVOICE_REPLICAS) so each request lands on a free replica.
    tts_concurrency: int = Field(2, validation_alias="TTS_CONCURRENCY")
    # Number of translation chunks sent to the LLM concurrently. Real speedup requires the
    # Ollama server to serve parallel requests (OLLAMA_NUM_PARALLEL>1).
    llm_concurrency: int = Field(4, validation_alias="LLM_CONCURRENCY")
    # Gentle background-noise reduction on the separated bg track during the final mux.
    enable_bg_denoise: bool = Field(True, validation_alias="BG_DENOISE")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
        "extra": "ignore",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
