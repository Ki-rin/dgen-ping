"""Data models for the dgen-ping service."""
from pydantic import BaseModel, Field, validator
from typing import Dict, Any, Optional, List
from datetime import datetime

class LlmRequest(BaseModel):
    """LLM request model."""
    soeid: str
    project_name: str
    prompt: str
    model: Optional[str] = "gpt-4"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2000
    parameters: Optional[Dict[str, Any]] = None
    
    @validator('prompt')
    def validate_prompt_length(cls, v):
        """Validate prompt is not empty and calculate length."""
        if not v or not v.strip():
            raise ValueError("Prompt cannot be empty")
        return v

class RequestMetadata(BaseModel):
    """Metadata for API request telemetry."""
    client_id: str
    soeid: Optional[str] = None
    project_name: Optional[str] = None
    target_service: str
    endpoint: str
    method: str
    status_code: int
    latency_ms: float
    request_size: Optional[int] = None
    response_size: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    llm_model: Optional[str] = None
    llm_latency: Optional[float] = None
    additional_data: Optional[Dict[str, Any]] = None

class TelemetryEvent(BaseModel):
    """Telemetry event record."""
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: RequestMetadata
    client_ip: Optional[str] = None
    request_id: Optional[str] = None
    
class TokenPayload(BaseModel):
    """API token payload model."""
    token_id: str
    project_id: str
    expires_at: Optional[datetime] = None

class LlmResponse(BaseModel):
    """LLM response model."""
    completion: str
    model: str
    metadata: Dict[str, Any]