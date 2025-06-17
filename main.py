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
from fastapi.exceptions import RequestValidationError

from config import settings
from db import db
from auth import get_token_payload, TokenPayload, AuthManager, DGEN_KEY
from proxy import ProxyService
from models import TelemetryEvent, LlmRequest, LlmResponse, RequestMetadata
from middleware import TelemetryMiddleware, RateLimitMiddleware

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
    docs_url="/docs" if settings.DEBUG else None
)

# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors."""
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation error",
            "details": exc.errors(),
            "timestamp": datetime.utcnow().isoformat()
        }
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
    logger.info("Starting dgen-ping service...")
    
    try:
        await db.initialize()
        await ProxyService.initialize()
        
        await db.log_connection_event(
            "application_startup",
            "success",
            "dgen-ping started successfully",
            {
                "debug": settings.DEBUG,
                "database_connected": db.is_connected,
                "allow_default_token": settings.ALLOW_DEFAULT_TOKEN
            }
        )
        
        logger.info("dgen-ping started successfully")
    except Exception as e:
        logger.error(f"Startup error: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down dgen-ping...")
    try:
        await db.log_connection_event(
            "application_shutdown",
            "success",
            "dgen-ping shutdown"
        )
    except Exception as e:
        logger.error(f"Shutdown error: {e}")

# Health endpoints
@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint."""
    try:
        db_health = await db.health_check()
        
        return {
            "status": "healthy" if db.is_connected else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
            "database": db_health,
            "settings": {
                "debug": settings.DEBUG,
                "max_concurrency": settings.MAX_CONCURRENCY
            }
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@app.get("/info", tags=["System"])
async def get_info(token: TokenPayload = Depends(get_token_payload)):
    """Get service information."""
    return {
        "service": "dgen-ping",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "authentication": {
            "token_type": "JWT" if token.token_id != "default_user" else "default",
            "project_id": token.project_id,
            "user_id": token.token_id
        },
        "database": {
            "status": "connected" if db.is_connected else "csv_fallback"
        }
    }

@app.get("/metrics", tags=["System"])
async def get_metrics(token: TokenPayload = Depends(get_token_payload)):
    """Get system metrics."""
    try:
        metrics = await db.get_metrics()
        metrics["timestamp"] = datetime.utcnow().isoformat()
        return metrics
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
            "requests_total": 0,
            "database_status": "error"
        }

# LLM endpoints
@app.post("/api/llm/completion", response_model=LlmResponse, tags=["LLM"])
async def llm_completion(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: LlmRequest = Body(...),
    token: TokenPayload = Depends(get_token_payload)
):
    """Process LLM completion request."""
    start_time = time.time()
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    logger.info(f"LLM request {request_id} from {payload.soeid}")

    try:
        # Validate request
        if not payload.prompt or not payload.prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt cannot be empty")
        
        if len(payload.prompt) > 50000:
            raise HTTPException(status_code=400, detail="Prompt too long (max 50,000 characters)")

        # Process request
        result = await ProxyService.proxy_request("llm", request, payload, token)
        processing_time = (time.time() - start_time) * 1000

        # Log telemetry
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

        logger.info(f"LLM request {request_id} completed in {processing_time/1000:.2f}s")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = (time.time() - start_time) * 1000
        logger.error(f"LLM request {request_id} failed: {str(e)}")
        
        background_tasks.add_task(
            db.log_connection_event,
            "llm_request_error",
            "error",
            f"LLM request failed: {str(e)}",
            {"request_id": request_id, "soeid": payload.soeid}
        )
        
        raise HTTPException(
            status_code=500,
            detail=f"LLM request failed: {str(e)}"
        )

@app.post("/api/llm/chat", response_model=LlmResponse, tags=["LLM"])
async def llm_chat(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: LlmRequest = Body(...),
    token: TokenPayload = Depends(get_token_payload)
):
    """Process LLM chat request (alias for completion)."""
    return await llm_completion(request, background_tasks, payload, token)

# Authentication endpoints
@app.post("/generate-token", tags=["Authentication"])
async def generate_token_endpoint(
    payload: Dict[str, Any] = Body(...),
    x_token_secret: str = Header(..., alias="X-Token-Secret")
):
    """Generate JWT token."""
    if x_token_secret != DGEN_KEY:
        raise HTTPException(status_code=403, detail="Invalid token secret")

    try:
        soeid = payload.get("soeid")
        project_id = payload.get("project_id")
        
        if not soeid:
            raise HTTPException(status_code=400, detail="SOEID is required")
        
        token = AuthManager.generate_token(soeid=soeid.strip(), project_id=project_id)
        actual_project_id = project_id if project_id else soeid
        
        await db.log_connection_event(
            "token_generated",
            "success",
            f"Token generated for {soeid}",
            {"soeid": soeid, "project_id": actual_project_id}
        )
        
        return {
            "token": token,
            "soeid": soeid,
            "project_id": actual_project_id,
            "type": "JWT",
            "timestamp": datetime.utcnow().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token generation failed: {str(e)}")

@app.post("/generate-token-simple", tags=["Authentication"])
async def generate_token_simple_endpoint(
    payload: Dict[str, Any] = Body(...),
    x_token_secret: str = Header(..., alias="X-Token-Secret")
):
    """Generate JWT token with SOEID only."""
    if x_token_secret != DGEN_KEY:
        raise HTTPException(status_code=403, detail="Invalid token secret")

    try:
        soeid = payload.get("soeid")
        
        if not soeid:
            raise HTTPException(status_code=400, detail="SOEID is required")
        
        token = AuthManager.generate_token(soeid=soeid.strip())
        
        return {
            "token": token,
            "soeid": soeid,
            "project_id": soeid,
            "type": "JWT",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token generation failed: {str(e)}")

@app.post("/verify-token", tags=["Authentication"])
async def verify_token_endpoint(
    payload: Dict[str, Any] = Body(...),
    x_token_secret: str = Header(..., alias="X-Token-Secret")
):
    """Verify JWT token."""
    if x_token_secret != DGEN_KEY:
        raise HTTPException(status_code=403, detail="Invalid token secret")

    try:
        token = payload.get("token")
        if not token:
            return {"valid": False, "error": "Token is required"}
        
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

# Telemetry endpoints
@app.post("/telemetry", tags=["Telemetry"])
async def telemetry_event(
    event: TelemetryEvent,
    token: TokenPayload = Depends(get_token_payload),
):
    """Log telemetry event."""
    try:
        event.metadata.client_id = token.project_id
        success = await db.log_telemetry(event)
        return {
            "status": "success" if success else "partial",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Telemetry logging failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# Public endpoints
@app.get("/public/health", tags=["Public"])
async def public_health():
    """Public health check."""
    return {
        "status": "healthy" if db.is_connected else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }

# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint."""
    return {
        "service": "dgen-ping",
        "version": "1.0.0",
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": {
            "health": "/health",
            "docs": "/docs" if settings.DEBUG else "disabled",
            "llm_completion": "/api/llm/completion"
        }
    }

# Run with uvicorn if called directly
if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting dgen-ping on {settings.HOST}:{settings.PORT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"Max concurrency: {settings.MAX_CONCURRENCY}")
    
    try:
        uvicorn.run(
            "main:app",
            host=settings.HOST,
            port=settings.PORT,
            log_level="debug" if settings.DEBUG else "info",
            reload=settings.DEBUG
        )
    except Exception as e:
        logger.error(f"Server startup failed: {e}")
