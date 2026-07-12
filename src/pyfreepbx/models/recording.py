"""System-recording models returned by the FreePBX Recordings module."""

from pydantic import BaseModel, Field


class SystemRecording(BaseModel):
    id: str
    name: str
    description: str = ""
    feature_code: str = ""
    language: str = ""
    playback: list[str] = Field(default_factory=list)
