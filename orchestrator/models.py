from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SrtSegment(BaseModel):
    start: float
    end: float
    text: str
    translated: Optional[str] = None
    speaker: Optional[str] = None

    @property
    def duration(self) -> float:
        return self.end - self.start


class PipelineJob(BaseModel):
    job_id: str
    filename: str
    base_name: str
    vram_profile: str = "16gb"
    target_language: str = "Tiếng Việt"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StageResult(BaseModel):
    stage: str
    success: bool
    output_path: Optional[str] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0
