"""Data models for the dgen-ping service."""
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime

class RequestMetadata(BaseModel):
    """Metadata for API request telemetry."""
    client_id: str
    user_id: Optional[str] = None
    target_service: str
    endpoint: str
    method: str
    status_code: int
    latency_ms: float
    request_size: Optional[int] = None
    response_size: Optional[int] = None
    llm_model: Optional[str] = None
    llm_latency: Optional[float] = None
    additional_data: Optional[Dict[str, Any]] = None

class TelemetryEvent(BaseModel):
    """Telemetry event record."""
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: RequestMetadata
    client_ip: Optional[str] = None
    
class TokenPayload(BaseModel):
    """API token payload model."""
    token_id: str
    project_id: str
    expires_at: Optional[datetime] = None