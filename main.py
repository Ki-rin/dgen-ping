"""dgen-ping: LLM proxy service with telemetry tracking."""
import logging
import os
import uuid
import time
import asyncio
from fastapi import FastAPI, Request, Depends, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
from config import settings
from db import db
from auth import get_token_payload, TokenPayload, DEFAULT_TOKEN
from proxy import ProxyService
from models import TelemetryEvent, LlmRequest, LlmResponse
from middleware import TelemetryMiddleware, RateLimitMiddleware

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("dgen-ping")

# Create FastAPI app with increased concurrency limits
app = FastAPI(
    title="dgen-ping",
    description="LLM proxy with telemetry tracking",
    version="1.0.0"
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TelemetryMiddleware)
if not settings.DEBUG:
    app.add_middleware(RateLimitMiddleware, rate_limit_per_minute=settings.RATE_LIMIT)

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    try:
        await db.initialize()
        # Initialize the ProxyService client and semaphore
        if not hasattr(ProxyService, "_client") or not ProxyService._client:
            await ProxyService.get_client()
        env = "kubernetes" if os.environ.get("KUBERNETES_SERVICE_HOST") else "standalone"
        logger.info(f"dgen-ping LLM proxy started in {env} environment (concurrency: {settings.MAX_CONCURRENCY})")
    except Exception as e:
        logger.error(f"Startup error: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    # Close any open connections
    if hasattr(ProxyService, "_client") and ProxyService._client:
        await ProxyService._client.aclose()
    logger.info("dgen-ping service shutdown")

@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "database": "connected" if db.is_connected else "fallback (csv)",
        "default_token": settings.ALLOW_DEFAULT_TOKEN,
        "services": list(settings.DOWNSTREAM_SERVICES.keys()),
        "concurrency": settings.MAX_CONCURRENCY
    }

@app.post("/api/llm/completion", response_model=LlmResponse, tags=["LLM"])
async def llm_completion(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: LlmRequest = Body(...),
    token: TokenPayload = Depends(get_token_payload)
):
    """Process an LLM completion request."""
    start_time = time.time()
    request_id = str(uuid.uuid4())
    
    logger.info(f"LLM request from {payload.soeid} (project: {payload.project_name}), prompt length: {len(payload.prompt)}")
    
    try:
        # Forward to LLM service
        result = await ProxyService.proxy_request("llm", request, payload, token)
        
        # Log response metrics with current timestamp
        processing_time = time.time() - start_time
        logger.info(f"LLM request {request_id} completed in {processing_time:.2f}s, response length: {len(result.completion)}")
        
        return result
    except Exception as e:
        logger.error(f"Error processing LLM request: {str(e)}")
        raise

@app.post("/api/llm/chat", response_model=LlmResponse, tags=["LLM"])
async def llm_chat(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: LlmRequest = Body(...),
    token: TokenPayload = Depends(get_token_payload)
):
    """Process an LLM chat request."""
    # Route to chat-specific endpoint if needed
    return await llm_completion(request, background_tasks, payload, token)

@app.post("/telemetry", tags=["Telemetry"])
async def log_telemetry(
    request: Request,
    event: TelemetryEvent,
    token: TokenPayload = Depends(get_token_payload)
):
    """Log a telemetry event."""
    event.client_ip = request.client.host
    event.metadata.client_id = token.project_id
    event.request_id = event.request_id or str(uuid.uuid4())
    await db.log_telemetry(event)
    return {"status": "success", "message": "Telemetry recorded", "request_id": event.request_id}

@app.get("/info", tags=["System"])
async def get_info(token: TokenPayload = Depends(get_token_payload)):
    """Get system information."""
    # Count pending requests if possible
    active_requests = 0
    if hasattr(ProxyService, "_semaphore") and ProxyService._semaphore is not None:
        try:
            active_requests = settings.MAX_CONCURRENCY - ProxyService._semaphore._value
        except AttributeError:
            active_requests = "unknown"
        
    return {
        "service": "dgen-ping",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "project_id": token.project_id,
        "token_type": "default" if token.token_id == DEFAULT_TOKEN else "standard",
        "database": "connected" if db.is_connected else "fallback (csv)",
        "active_requests": active_requests,
        "max_concurrency": settings.MAX_CONCURRENCY
    }

@app.get("/metrics", tags=["System"])
async def get_metrics(token: TokenPayload = Depends(get_token_payload)):
    """Get system metrics."""
    # This would be expanded in a production system to provide
    # detailed metrics about request rates, latencies, etc.
    metrics = await db.get_metrics()
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "requests_total": metrics.get("requests_total", 0),
        "requests_last_hour": metrics.get("requests_last_hour", 0),
        "avg_latency_ms": metrics.get("avg_latency_ms", 0),
        "error_rate": metrics.get("error_rate", 0),
        "token_usage_total": metrics.get("token_usage_total", 0)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=settings.WORKERS
    )