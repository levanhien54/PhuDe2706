import asyncio
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from orchestrator.config import Settings
from orchestrator.clients.llm_client import LLMClient
from orchestrator.models import SrtSegment

async def main():
    settings = Settings()
    client = LLMClient(settings)
    
    segments = [
        SrtSegment(start=0.0, end=2.0, text="Hey guys, welcome back to my channel!", speaker="SPEAKER_00"),
        SrtSegment(start=2.0, end=4.5, text="Today we are going to look at this crazy new AI.", speaker="SPEAKER_00"),
        SrtSegment(start=4.5, end=6.0, text="It's literally blowing my mind right now.", speaker="SPEAKER_00"),
    ]
    
    print("Testing translation with Style: Hài hước / Bắt trend...")
    translated = await client.translate_batch(segments, target_lang="Tiếng Việt", target_style="Hài hước / Bắt trend")
    
    for s in translated:
        print(f"[{s.speaker}] {s.text} -> {s.translated}")

if __name__ == "__main__":
    asyncio.run(main())
