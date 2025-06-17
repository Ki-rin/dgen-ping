"""dgen-ping: LLM proxy service with telemetry tracking."""
import os
import uuid
import time
import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, Request, Depends, Body, BackgroundTasks, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from config import settings
from db import db
from auth import get_token_payload, TokenPayload, AuthManager, DGEN_KEY
from proxy import ProxyService
from models import TelemetryEvent, LlmRequest, LlmResponse, RequestMetadata

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("dgen-ping")


# Create FastAPI app
app = FastAPI(
    title="dgen-ping",
    description="LLM proxy with telemetry tracking",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
)

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    logger.info("Starting dgen-ping service...")
    await db.initialize()
    await ProxyService.initialize()
    logger.info("dgen-ping started successfully")

# Health endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    db_health = await db.health_check()
    return {
        "status": "healthy" if db.is_connected else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_health
    }

# Token generation
@app.post("/generate-token")
async def generate_token_endpoint(
    payload: Dict[str, Any] = Body(...),
    x_token_secret: str = Header(..., alias="X-Token-Secret")
):
    """Generate JWT token."""
    if x_token_secret != DGEN_KEY:
        raise HTTPException(status_code=403, detail="Invalid token secret")

    soeid = payload.get("soeid")
    if not soeid:
        raise HTTPException(status_code=400, detail="SOEID is required")
    
    token = AuthManager.generate_token(soeid=soeid.strip())
    
    return {
        "token": token,
        "soeid": soeid,
        "project_id": soeid,
        "timestamp": datetime.utcnow().isoformat()
    }

# Token verification
@app.post("/verify-token")
async def verify_token_endpoint(
    payload: Dict[str, Any] = Body(...),
    x_token_secret: str = Header(..., alias="X-Token-Secret")
):
    """Verify JWT token."""
    if x_token_secret != DGEN_KEY:
        raise HTTPException(status_code=403, detail="Invalid token secret")

    token = payload.get("token")
    if not token:
        return {"valid": False, "error": "Token is required"}
    
    try:
        token_payload = AuthManager.verify_token(token=token.strip())
        return {
            "valid": True,
            "data": {
                "soeid": token_payload.token_id,
                "project_id": token_payload.project_id
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# LLM completion
@app.post("/api/llm/completion", response_model=LlmResponse)
async def llm_completion(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: LlmRequest = Body(...),
    token: TokenPayload = Depends(get_token_payload)
):
    """Process LLM completion request."""
    start_time = time.time()
    request_id = str(uuid.uuid4())

    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    # Process LLM request
    result = await ProxyService.proxy_request("llm", request, payload, token)
    processing_time = (time.time() - start_time) * 1000

    # Log telemetry in background
    background_tasks.add_task(
        db.log_telemetry,
        TelemetryEvent(
            event_type="llm_completion",
            request_id=request_id,
            client_ip=request.client.host if request.client else "unknown",
            metadata=RequestMetadata(
                client_id=token.project_id,
                soeid=payload.soeid,
                project_name=payload.project_name,
                target_service="llm",
                endpoint="/api/llm/completion",
                method=request.method,
                status_code=200,
                latency_ms=processing_time,
                request_size=len(payload.prompt),
                response_size=len(result.completion),
                llm_model=payload.model or settings.DEFAULT_MODEL,
                additional_data={
                    "request_id": request_id,
                    "completion_preview": result.completion[:100]
                }
            )
        )
    )

    return result

# Telemetry endpoint
@app.post("/telemetry")
async def telemetry_event(
    event: TelemetryEvent,
    token: TokenPayload = Depends(get_token_payload),
):
    """Log telemetry event."""
    event.metadata.client_id = token.project_id
    success = await db.log_telemetry(event)
    return {
        "status": "success" if success else "partial",
        "timestamp": datetime.utcnow().isoformat()
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "dgen-ping",
        "version": "1.0.0",
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
