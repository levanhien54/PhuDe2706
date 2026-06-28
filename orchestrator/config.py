from pydantic_settings import BaseSettings
from pydantic import Field
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
    llm_backend: str = Field("ollama", validation_alias="LLM_BACKEND")
    llm_model: str = Field("qwen2.5:14b", validation_alias="LLM_MODEL")
    vram_profile: str = Field("16gb", validation_alias="VRAM_PROFILE")
    enable_lipsync: bool = Field(False, validation_alias="ENABLE_LIPSYNC")
    enable_propainter: bool = Field(False, validation_alias="ENABLE_PROPAINTER")
    enable_cpu_offload: bool = Field(False, validation_alias="ENABLE_CPU_OFFLOAD")
    enable_kvcached: bool = Field(False, validation_alias="ENABLE_KVCACHED")

    # Paths
    data_dir: str = Field("/app/data", validation_alias="DATA_DIR")

    # Tuning
    http_timeout: float = Field(300.0, validation_alias="HTTP_TIMEOUT")
    http_retries: int = Field(3, validation_alias="HTTP_RETRIES")
    ocr_fps: float = Field(2.0, validation_alias="OCR_FPS")
    tts_max_ratio: float = Field(1.5, validation_alias="TTS_MAX_RATIO")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
        "extra": "ignore",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
