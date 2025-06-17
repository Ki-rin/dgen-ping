"""Data models for dgen-ping."""
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime

class LlmRequest(BaseModel):
    soeid: str
    project_name: str
    prompt: str
    model: Optional[str] = "gemini"
    temperature: Optional[float] = 0.3
    max_tokens: Optional[int] = 10000

class LlmResponse(BaseModel):
    completion: str
    model: str
    metadata: Dict[str, Any]

class TelemetryEvent(BaseModel):
    event_type: str
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any]
    client_ip: Optional[str] = None
    request_id: Optional[str] = None
