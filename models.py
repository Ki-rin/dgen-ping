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

class RequestMetadata(BaseModel):
    client_id: str
    soeid: str
    project_name: str
    target_service: str
    endpoint: str
    method: str
    status_code: int
    latency_ms: float
    request_size: int
    response_size: int
    llm_model: Optional[str] = None
    additional_data: Optional[Dict[str, Any]] = None

class TelemetryEvent(BaseModel):
    event_type: str
    request_id: str
    client_ip: str
    metadata: RequestMetadata
    timestamp: Optional[datetime] = None

class TokenPayload(BaseModel):
    token_id: str
    project_id: str
