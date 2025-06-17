"""dgen-ping: LLM proxy service with telemetry tracking and robust error handling."""
import os
import uuid
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from fastapi import FastAPI, Request, Depends, Body, BackgroundTasks, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import settings
from db import db
from auth import get_token_payload, get_token_payload_optional, TokenPayload, AuthManager, DGEN_KEY
from proxy import ProxyService
from models import TelemetryEvent, LlmRequest, LlmResponse, RequestMetadata, TokenPayload
from middleware import TelemetryMiddleware, RateLimitMiddleware

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("dgen-ping")

# Create FastAPI app with comprehensive configuration
app = FastAPI(
    title="dgen-ping",
    description="LLM proxy with telemetry tracking and robust error handling",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None
)

# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for better error reporting."""
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    error_msg = f"Unhandled exception in {request.url.path}: {str(exc)}"
    
    logger.error(error_msg, exc_info=True)
    
    # Try to log the error (best effort)
    try:
        await db.log_connection_event(
            "unhandled_exception",
            "error", 
            error_msg,
            {
                "path": str(request.url.path), 
                "method": request.method,
                "request_id": request_id,
                "error_type": type(exc).__name__
            }
        )
    except Exception as log_error:
        logger.error(f"Failed to log exception: {log_error}")
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": "An unexpected error occurred",
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors."""
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation error",
            "message": "Invalid request data",
            "details": exc.errors(),
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions with consistent format."""
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "HTTP error",
            "message": exc.detail,
            "status_code": exc.status_code,
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# Add middleware with proper ordering
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add custom middleware
app.add_middleware(TelemetryMiddleware)

# Add rate limiting only in production
if not settings.DEBUG:
    app.add_middleware(RateLimitMiddleware, rate_limit_per_minute=settings.RATE_LIMIT)

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup with comprehensive error handling."""
    startup_success = True
    startup_errors = []
    startup_start_time = time.time()

    logger.info("Starting dgen-ping service initialization...")

    # Initialize database connection (with fallback)
    try:
        await db.initialize()
        db_status = "Connected" if db.is_connected else "CSV Fallback"
        logger.info(f"Database initialization: {db_status}")
    except Exception as e:
        startup_errors.append(f"Database initialization failed: {e}")
        logger.error(f"Database initialization failed: {e}")

    # Initialize the ProxyService
    try:
        await ProxyService.initialize()
        logger.info("ProxyService initialized successfully")
    except Exception as e:
        startup_errors.append(f"ProxyService initialization failed: {e}")
        logger.error(f"ProxyService initialization failed: {e}")
        startup_success = False

    # Determine environment
    env = "kubernetes" if os.environ.get("KUBERNETES_SERVICE_HOST") else "standalone"
    startup_time = time.time() - startup_start_time

    # Create startup metadata
    startup_metadata = {
        "environment": env,
        "startup_time_seconds": round(startup_time, 2),
        "concurrency": settings.MAX_CONCURRENCY,
        "host": settings.HOST,
        "port": settings.PORT,
        "debug": settings.DEBUG,
        "database_connected": db.is_connected,
        "csv_fallback": not db.is_connected,
        "startup_success": startup_success,
        "errors": startup_errors,
        "allow_default_token": settings.ALLOW_DEFAULT_TOKEN
    }

    # Log application startup
    try:
        status = "success" if startup_success else "partial"
        message = f"dgen-ping started in {env} environment"
        if startup_errors:
            message += f" with {len(startup_errors)} warnings"

        await db.log_connection_event(
            "application_startup",
            status,
            message,
            startup_metadata
        )
    except Exception as e:
        logger.error(f"Failed to log startup event: {e}")

    if startup_success:
        logger.info(f"dgen-ping started successfully in {env} environment (startup time: {startup_time:.2f}s)")
    else:
        logger.warning(f"dgen-ping started with errors in {env} environment")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down dgen-ping service...")
    
    try:
        await db.log_connection_event(
            "application_shutdown",
            "success",
            "dgen-ping service shutdown",
            {"shutdown_time": datetime.utcnow().isoformat()}
        )
        logger.info("dgen-ping service shutdown completed")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

# Health and system endpoints
@app.get("/health", tags=["System"])
async def health_check():
    """Comprehensive health check endpoint."""
    try:
        db_health = await db.health_check()
        
        # Check ProxyService health
        proxy_health = {
            "initialized": hasattr(ProxyService, '_semaphore') and ProxyService._semaphore is not None
        }
        
        if proxy_health["initialized"]:
            try:
                active_requests = settings.MAX_CONCURRENCY - ProxyService._semaphore._value
                proxy_health["active_requests"] = active_requests
                proxy_health["available_slots"] = ProxyService._semaphore._value
            except Exception:
                proxy_health["active_requests"] = "unknown"
                proxy_health["available_slots"] = "unknown"

        overall_status = "healthy"
        if not db_health.get("database_connected", False):
            overall_status = "degraded" if db_health.get("csv_fallback_active", False) else "unhealthy"

        return {
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
            "database": db_health,
            "proxy": proxy_health,
            "settings": {
                "allow_default_token": settings.ALLOW_DEFAULT_TOKEN,
                "max_concurrency": settings.MAX_CONCURRENCY,
                "debug": settings.DEBUG,
                "rate_limit": settings.RATE_LIMIT
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e)
            }
        )

@app.get("/info", tags=["System"])
async def get_info(token: TokenPayload = Depends(get_token_payload)):
    """Get detailed service information."""
    try:
        active_requests = "unknown"
        available_slots = "unknown"
        
        if hasattr(ProxyService, "_semaphore") and ProxyService._semaphore is not None:
            try:
                active_requests = settings.MAX_CONCURRENCY - ProxyService._semaphore._value
                available_slots = ProxyService._semaphore._value
            except AttributeError:
                pass

        return {
            "service": "dgen-ping",
            "version": "1.0.0",
            "timestamp": datetime.utcnow().isoformat(),
            "authentication": {
                "token_type": "JWT" if token.token_id != "default_user" else "default",
                "project_id": token.project_id,
                "user_id": token.token_id,
                "expires_at": token.expires_at.isoformat() if token.expires_at else None
            },
            "database": {
                "status": "connected" if db.is_connected else "csv_fallback",
                "fallback_active": not db.is_connected
            },
            "performance": {
                "active_requests": active_requests,
                "available_slots": available_slots,
                "max_concurrency": settings.MAX_CONCURRENCY,
                "utilization_percent": round((active_requests / settings.MAX_CONCURRENCY) * 100, 1) if isinstance(active_requests, int) else "unknown"
            }
        }
    except Exception as e:
        logger.error(f"Error getting service info: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get service info: {str(e)}")

@app.get("/metrics", tags=["System"])
async def get_metrics(token: TokenPayload = Depends(get_token_payload)):
    """Get system metrics with error handling."""
    try:
        metrics = await db.get_metrics()
        metrics["timestamp"] = datetime.utcnow().isoformat()
        
        # Add real-time performance metrics
        if hasattr(ProxyService, "_semaphore") and ProxyService._semaphore is not None:
            try:
                active_requests = settings.MAX_CONCURRENCY - ProxyService._semaphore._value
                metrics["active_requests"] = active_requests
                metrics["system_utilization_percent"] = round((active_requests / settings.MAX_CONCURRENCY) * 100, 1)
            except Exception:
                metrics["active_requests"] = "unknown"
                metrics["system_utilization_percent"] = "unknown"
        
        return metrics
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
            "requests_total": 0,
            "requests_last_hour": 0,
            "avg_latency_ms": 0,
            "error_rate": 0,
            "token_usage_total": 0,
            "llm_runs_total": 0,
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
    """Process an LLM completion request with comprehensive error handling and telemetry."""
    start_time = time.time()
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    logger.info(f"LLM request {request_id} from {payload.soeid} (project: {payload.project_name}), prompt length: {len(payload.prompt)}")

    # Create initial telemetry event for the API call
    def create_llm_telemetry_event(status_code: int, latency_ms: float, error: str = None, 
                                  result: LlmResponse = None) -> TelemetryEvent:
        """Helper to create telemetry events for LLM calls."""
        additional_data = {
            "request_id": request_id,
            "model": payload.model or settings.DEFAULT_MODEL,
            "temperature": payload.temperature or settings.DEFAULT_TEMPERATURE,
            "max_tokens": payload.max_tokens or settings.DEFAULT_MAX_TOKENS,
            "prompt_length": len(payload.prompt),
            "endpoint": "/api/llm/completion"
        }
        
        if error:
            additional_data["error"] = error
            additional_data["error_type"] = type(error).__name__ if hasattr(error, '__class__') else "Unknown"
        
        if result:
            additional_data["completion_length"] = len(result.completion)
            additional_data["completion"] = result.completion[:500] + "..." if len(result.completion) > 500 else result.completion
            if "tokens" in result.metadata:
                additional_data["token_usage"] = result.metadata["tokens"]

        return TelemetryEvent(
            event_type="llm_api_call",
            request_id=request_id,
            client_ip=request.client.host if request.client else "unknown",
            metadata=RequestMetadata(
                client_id=token.project_id,
                soeid=payload.soeid,
                project_name=payload.project_name,
                target_service="llm",
                endpoint="/api/llm/completion",
                method=request.method,
                status_code=status_code,
                latency_ms=latency_ms,
                request_size=len(payload.prompt),
                response_size=len(result.completion) if result else 0,
                prompt_tokens=result.metadata.get("tokens", {}).get("prompt", 0) if result else 0,
                completion_tokens=result.metadata.get("tokens", {}).get("completion", 0) if result else 0,
                total_tokens=result.metadata.get("tokens", {}).get("total", 0) if result else 0,
                llm_model=payload.model or settings.DEFAULT_MODEL,
                llm_latency=latency_ms,
                additional_data=additional_data
            )
        )

    try:
        # Validate request parameters
        if not payload.prompt or not payload.prompt.strip():
            processing_time = (time.time() - start_time) * 1000
            # Log validation error to telemetry
            background_tasks.add_task(
                db.log_telemetry, 
                create_llm_telemetry_event(400, processing_time, "Empty prompt")
            )
            raise HTTPException(status_code=400, detail="Prompt cannot be empty")
        
        if len(payload.prompt) > 50000:  # Reasonable limit
            processing_time = (time.time() - start_time) * 1000
            # Log validation error to telemetry
            background_tasks.add_task(
                db.log_telemetry, 
                create_llm_telemetry_event(400, processing_time, "Prompt too long")
            )
            raise HTTPException(status_code=400, detail="Prompt too long (max 50,000 characters)")

        # Process request using ProxyService
        result = await ProxyService.proxy_request("llm", request, payload, token)
        processing_time = (time.time() - start_time) * 1000

        # Log successful completion to telemetry
        background_tasks.add_task(
            db.log_telemetry, 
            create_llm_telemetry_event(200, processing_time, result=result)
        )

        # Log response metrics
        logger.info(f"LLM request {request_id} completed in {processing_time/1000:.2f}s, response length: {len(result.completion)}")

        return result
        
    except HTTPException as e:
        processing_time = (time.time() - start_time) * 1000
        # Log HTTP error to telemetry
        background_tasks.add_task(
            db.log_telemetry, 
            create_llm_telemetry_event(e.status_code, processing_time, e.detail)
        )
        raise
    except Exception as e:
        processing_time = (time.time() - start_time) * 1000
        error_msg = f"Error processing LLM request: {str(e)}"
        logger.error(f"LLM request {request_id} failed after {processing_time/1000:.2f}s: {error_msg}")
        
        # Log error to telemetry
        background_tasks.add_task(
            db.log_telemetry, 
            create_llm_telemetry_event(500, processing_time, str(e))
        )
        
        # Also log to connection events for critical errors
        background_tasks.add_task(
            db.log_connection_event,
            "llm_request_error",
            "error",
            error_msg,
            {
                "request_id": request_id,
                "soeid": payload.soeid,
                "project": payload.project_name,
                "processing_time": processing_time,
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
        
        raise HTTPException(
            status_code=500,
            detail=f"LLM request processing failed: {str(e)}"
        )

@app.post("/api/llm/chat", response_model=LlmResponse, tags=["LLM"])
async def llm_chat(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: LlmRequest = Body(...),
    token: TokenPayload = Depends(get_token_payload)
):
    """Process an LLM chat request (alias for completion) with full telemetry logging."""
    start_time = time.time()
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    logger.info(f"LLM chat request {request_id} from {payload.soeid} (project: {payload.project_name}), prompt length: {len(payload.prompt)}")

    # Create telemetry event helper specific to chat endpoint
    def create_chat_telemetry_event(status_code: int, latency_ms: float, error: str = None, 
                                   result: LlmResponse = None) -> TelemetryEvent:
        """Helper to create telemetry events for LLM chat calls."""
        additional_data = {
            "request_id": request_id,
            "model": payload.model or settings.DEFAULT_MODEL,
            "temperature": payload.temperature or settings.DEFAULT_TEMPERATURE,
            "max_tokens": payload.max_tokens or settings.DEFAULT_MAX_TOKENS,
            "prompt_length": len(payload.prompt),
            "endpoint": "/api/llm/chat",
            "chat_mode": True
        }
        
        if error:
            additional_data["error"] = error
            additional_data["error_type"] = type(error).__name__ if hasattr(error, '__class__') else "Unknown"
        
        if result:
            additional_data["completion_length"] = len(result.completion)
            additional_data["completion"] = result.completion[:500] + "..." if len(result.completion) > 500 else result.completion
            if "tokens" in result.metadata:
                additional_data["token_usage"] = result.metadata["tokens"]

        return TelemetryEvent(
            event_type="llm_chat_call",
            request_id=request_id,
            client_ip=request.client.host if request.client else "unknown",
            metadata=RequestMetadata(
                client_id=token.project_id,
                soeid=payload.soeid,
                project_name=payload.project_name,
                target_service="llm",
                endpoint="/api/llm/chat",
                method=request.method,
                status_code=status_code,
                latency_ms=latency_ms,
                request_size=len(payload.prompt),
                response_size=len(result.completion) if result else 0,
                prompt_tokens=result.metadata.get("tokens", {}).get("prompt", 0) if result else 0,
                completion_tokens=result.metadata.get("tokens", {}).get("completion", 0) if result else 0,
                total_tokens=result.metadata.get("tokens", {}).get("total", 0) if result else 0,
                llm_model=payload.model or settings.DEFAULT_MODEL,
                llm_latency=latency_ms,
                additional_data=additional_data
            )
        )

    try:
        # Validate request parameters
        if not payload.prompt or not payload.prompt.strip():
            processing_time = (time.time() - start_time) * 1000
            # Log validation error to telemetry
            background_tasks.add_task(
                db.log_telemetry, 
                create_chat_telemetry_event(400, processing_time, "Empty prompt")
            )
            raise HTTPException(status_code=400, detail="Prompt cannot be empty")
        
        if len(payload.prompt) > 50000:  # Reasonable limit
            processing_time = (time.time() - start_time) * 1000
            # Log validation error to telemetry
            background_tasks.add_task(
                db.log_telemetry, 
                create_chat_telemetry_event(400, processing_time, "Prompt too long")
            )
            raise HTTPException(status_code=400, detail="Prompt too long (max 50,000 characters)")

        # Process request using ProxyService
        result = await ProxyService.proxy_request("llm", request, payload, token)
        processing_time = (time.time() - start_time) * 1000

        # Log successful completion to telemetry
        background_tasks.add_task(
            db.log_telemetry, 
            create_chat_telemetry_event(200, processing_time, result=result)
        )

        # Log response metrics
        logger.info(f"LLM chat request {request_id} completed in {processing_time/1000:.2f}s, response length: {len(result.completion)}")

        return result
        
    except HTTPException as e:
        processing_time = (time.time() - start_time) * 1000
        # Log HTTP error to telemetry
        background_tasks.add_task(
            db.log_telemetry, 
            create_chat_telemetry_event(e.status_code, processing_time, e.detail)
        )
        raise
    except Exception as e:
        processing_time = (time.time() - start_time) * 1000
        error_msg = f"Error processing LLM chat request: {str(e)}"
        logger.error(f"LLM chat request {request_id} failed after {processing_time/1000:.2f}s: {error_msg}")
        
        # Log error to telemetry
        background_tasks.add_task(
            db.log_telemetry, 
            create_chat_telemetry_event(500, processing_time, str(e))
        )
        
        # Also log to connection events for critical errors
        background_tasks.add_task(
            db.log_connection_event,
            "llm_chat_error",
            "error",
            error_msg,
            {
                "request_id": request_id,
                "soeid": payload.soeid,
                "project": payload.project_name,
                "processing_time": processing_time,
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
        
        raise HTTPException(
            status_code=500,
            detail=f"LLM chat request processing failed: {str(e)}"
        )

# Telemetry endpoints
@app.post("/telemetry", tags=["Telemetry"])
async def telemetry_event(
    request: Request,
    event: TelemetryEvent,
    token: TokenPayload = Depends(get_token_payload),
):
    """Log a telemetry event with error handling."""
    try:
        event.metadata.client_id = token.project_id
        event.request_id = event.request_id or str(uuid.uuid4())

        success = await db.log_telemetry(event)
        return {
            "status": "success" if success else "partial",
            "message": "Telemetry recorded" if success else "Telemetry recorded with fallback",
            "request_id": event.request_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Telemetry logging failed: {e}")
        return {
            "status": "error",
            "message": f"Telemetry logging failed: {str(e)}",
            "request_id": getattr(event, 'request_id', 'unknown'),
            "timestamp": datetime.utcnow().isoformat()
        }

@app.get("/telemetry/summary", tags=["Telemetry"])
async def get_telemetry_summary(
    time_window_minutes: int = 60,
    token: TokenPayload = Depends(get_token_payload)
):
    """Get comprehensive telemetry summary for LLM requests."""
    try:
        summary = await ProxyService.get_telemetry_summary(time_window_minutes)
        summary["timestamp"] = datetime.utcnow().isoformat()
        summary["requested_by"] = {
            "soeid": token.token_id,
            "project_id": token.project_id
        }
        return summary
    except Exception as e:
        logger.error(f"Error getting telemetry summary: {e}")
        return {
            "error": str(e),
            "time_window_minutes": time_window_minutes,
            "timestamp": datetime.utcnow().isoformat()
        }

@app.get("/telemetry/events", tags=["Telemetry"])
async def get_telemetry_events(
    limit: int = 50,
    skip: int = 0,
    event_type: str = None,
    soeid: str = None,
    project: str = None,
    time_window_hours: int = 24,
    token: TokenPayload = Depends(get_token_payload)
):
    """Get telemetry events with filtering options."""
    try:
        # Validate parameters
        if limit > 1000:
            limit = 1000  # Cap at 1000 for performance
        if limit < 1:
            limit = 50
        if skip < 0:
            skip = 0

        if db.is_connected:
            # Build query filter
            query = {"event_type": "llm_run"}
            if soeid:
                query["metadata.soeid"] = soeid
            if project:
                query["metadata.project_name"] = project

            # Get LLM runs from MongoDB
            collection = db.async_client[settings.DB_NAME].telemetry
            cursor = collection.find(query).sort("timestamp", -1).skip(skip).limit(limit)
            llm_runs = await cursor.to_list(limit)

            # Format for response
            formatted_runs = []
            for run in llm_runs:
                run["run_id"] = str(run["_id"])  # Convert ObjectId to string
                run.pop("_id", None)  # Remove original _id
                if isinstance(run.get("timestamp"), datetime):
                    run["timestamp"] = run["timestamp"].isoformat()
                formatted_runs.append(run)

            total_count = await collection.count_documents(query)

            return {
                "total": total_count,
                "skip": skip,
                "limit": limit,
                "results": formatted_runs,
                "source": "database",
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            return {
                "total": 0,
                "skip": skip,
                "limit": limit,
                "results": [],
                "source": "csv_fallback",
                "note": "Database not connected, using CSV fallback. Historical data limited.",
                "timestamp": datetime.utcnow().isoformat()
            }

    except Exception as e:
        logger.error(f"Error retrieving LLM history: {e}")
        return {
            "total": 0,
            "skip": skip,
            "limit": limit,
            "results": [],
            "error": str(e),
            "source": "error",
            "timestamp": datetime.utcnow().isoformat()
        }

@app.get("/db-status", tags=["System"])
async def get_db_status(token: TokenPayload = Depends(get_token_payload)):
    """Get comprehensive database status and information."""
    try:
        health = await db.health_check()
        
        if db.is_connected:
            # Get collection information
            try:
                db_client = db.async_client[settings.DB_NAME]
                collections_info = {}
                
                for collection_name in ["telemetry", "connection_logs"]:
                    try:
                        count = await db_client[collection_name].count_documents({})
                        collections_info[collection_name] = count
                    except Exception as e:
                        collections_info[collection_name] = f"Error: {str(e)}"

                # Get latest connection events
                try:
                    latest_events = await db_client.connection_logs.find().sort(
                        "timestamp", -1).limit(5).to_list(5)
                    
                    formatted_events = []
                    for event in latest_events:
                        event["event_id"] = str(event["_id"])
                        event.pop("_id", None)
                        if isinstance(event.get("timestamp"), datetime):
                            event["timestamp"] = event["timestamp"].isoformat()
                        formatted_events.append(event)
                except Exception as e:
                    formatted_events = [{"error": f"Could not retrieve events: {str(e)}"}]

                health.update({
                    "database_name": settings.DB_NAME,
                    "collections": collections_info,
                    "latest_connection_events": formatted_events
                })
            except Exception as e:
                health["collection_error"] = str(e)
        else:
            # CSV fallback information
            csv_info = {"csv_files": []}
            if os.path.exists(settings.CSV_FALLBACK_DIR):
                try:
                    csv_files = [f for f in os.listdir(settings.CSV_FALLBACK_DIR) if f.endswith('.csv')]
                    csv_info = {
                        "csv_files": csv_files,
                        "csv_directory": settings.CSV_FALLBACK_DIR
                    }
                except Exception as e:
                    csv_info["error"] = str(e)
            
            health.update(csv_info)

        health["timestamp"] = datetime.utcnow().isoformat()
        return health

    except Exception as e:
        logger.error(f"Error getting database status: {e}")
        return {
            "status": "error",
            "error": str(e),
            "database_connected": False,
            "timestamp": datetime.utcnow().isoformat()
        }

# Authentication endpoints
@app.post("/generate-token", tags=["Authentication"])
async def generate_token_endpoint(
    payload: Dict[str, Any] = Body(...),
    x_token_secret: str = Header(..., alias="X-Token-Secret")
):
    """Generate a JWT token for a user. Only SOEID is required."""
    if x_token_secret != DGEN_KEY:
        raise HTTPException(status_code=403, detail="Invalid token secret")

    try:
        # Extract parameters from payload
        soeid = payload.get("soeid")
        project_id = payload.get("project_id")
        
        if not soeid:
            raise HTTPException(status_code=400, detail="SOEID is required")
        
        # Clean and validate input
        soeid = str(soeid).strip()
        
        if not soeid:
            raise HTTPException(status_code=400, detail="SOEID cannot be empty")
        
        # Project ID is optional - defaults to soeid if not provided
        if project_id:
            project_id = str(project_id).strip()
        
        token = AuthManager.generate_token(soeid=soeid, project_id=project_id)
        
        # Determine the actual project_id used
        actual_project_id = project_id if project_id else soeid
        
        # Log token generation
        await db.log_connection_event(
            "token_generated",
            "success",
            f"Token generated for user {soeid}",
            {"soeid": soeid, "project_id": actual_project_id}
        )
        
        return {
            "token": token,
            "soeid": soeid,
            "project_id": actual_project_id,
            "type": "JWT",
            "expires": "never",
            "algorithm": "HS256",
            "note": "project_id defaults to soeid if not specified",
            "timestamp": datetime.utcnow().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.log_connection_event(
            "token_generation_failed",
            "error",
            f"Token generation failed for user {soeid}: {str(e)}",
            {"soeid": soeid, "error": str(e)}
        )
        raise HTTPException(status_code=500, detail=f"Token generation failed: {str(e)}")

@app.post("/generate-token-simple", tags=["Authentication"])
async def generate_token_simple_endpoint(
    payload: Dict[str, Any] = Body(...),
    x_token_secret: str = Header(..., alias="X-Token-Secret")
):
    """Generate a JWT token for a user with only SOEID required."""
    if x_token_secret != DGEN_KEY:
        raise HTTPException(status_code=403, detail="Invalid token secret")

    try:
        # Extract SOEID from payload
        soeid = payload.get("soeid")
        
        if not soeid:
            raise HTTPException(status_code=400, detail="SOEID is required")
        
        # Clean and validate input
        soeid = str(soeid).strip()
        
        if not soeid:
            raise HTTPException(status_code=400, detail="SOEID cannot be empty")
        
        # Generate token with soeid only (project_id will default to soeid)
        token = AuthManager.generate_token(soeid=soeid)
        
        # Log token generation
        await db.log_connection_event(
            "token_generated_simple",
            "success",
            f"Simple token generated for user {soeid}",
            {"soeid": soeid, "project_id": soeid}
        )
        
        return {
            "token": token,
            "soeid": soeid,
            "project_id": soeid,  # Same as soeid
            "type": "JWT",
            "expires": "never",
            "algorithm": "HS256",
            "timestamp": datetime.utcnow().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.log_connection_event(
            "token_generation_failed",
            "error",
            f"Simple token generation failed for user {soeid}: {str(e)}",
            {"soeid": soeid, "error": str(e)}
        )
        raise HTTPException(status_code=500, detail=f"Token generation failed: {str(e)}")

@app.post("/verify-token", tags=["Authentication"])
async def verify_token_endpoint(
    payload: Dict[str, Any] = Body(...),
    x_token_secret: str = Header(..., alias="X-Token-Secret")
):
    """Verify a JWT token with enhanced error handling."""
    if x_token_secret != DGEN_KEY:
        raise HTTPException(status_code=403, detail="Invalid token secret")

    try:
        # Extract token from payload
        token = payload.get("token")
        
        if not token:
            return {
                "valid": False,
                "error": "Token is required",
                "type": "JWT",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        # Clean token input
        clean_token = str(token).strip()
        
        # Basic validation
        if not clean_token:
            return {
                "valid": False,
                "error": "Empty token",
                "type": "JWT",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        # Check for common encoding issues
        try:
            clean_token.encode('utf-8')
        except UnicodeEncodeError:
            return {
                "valid": False,
                "error": "Token contains invalid characters",
                "type": "JWT",
                "suggestion": "Ensure token contains only valid UTF-8 characters",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        # Verify token
        token_payload = AuthManager.verify_token(token=clean_token)
        return {
            "valid": True,
            "data": {
                "soeid": token_payload.token_id,
                "project_id": token_payload.project_id,
                "expires_at": token_payload.expires_at.isoformat() if token_payload.expires_at else None
            },
            "type": "JWT",
            "timestamp": datetime.utcnow().isoformat()
        }
    except HTTPException as e:
        return {
            "valid": False,
            "error": e.detail,
            "type": "JWT",
            "status_code": e.status_code,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "valid": False,
            "error": f"Unexpected error: {str(e)}",
            "type": "JWT",
            "timestamp": datetime.utcnow().isoformat()
        }

# Public endpoints (no authentication required)
@app.get("/public/health", tags=["Public"])
async def public_health():
    """Public health check endpoint (no authentication required)."""
    return {
        "status": "healthy" if db.is_connected else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "database": "connected" if db.is_connected else "fallback"
    }

@app.get("/public/status", tags=["Public"])
async def public_status():
    """Public status endpoint with minimal information."""
    try:
        active_requests = 0
        if hasattr(ProxyService, "_semaphore") and ProxyService._semaphore is not None:
            try:
                active_requests = settings.MAX_CONCURRENCY - ProxyService._semaphore._value
            except Exception:
                active_requests = 0

        return {
            "service": "dgen-ping",
            "status": "operational",
            "timestamp": datetime.utcnow().isoformat(),
            "load": {
                "active_requests": active_requests,
                "max_concurrency": settings.MAX_CONCURRENCY,
                "utilization_percent": round((active_requests / settings.MAX_CONCURRENCY) * 100, 1) if settings.MAX_CONCURRENCY > 0 else 0
            }
        }
    except Exception as e:
        logger.error(f"Error in public status: {e}")
        return {
            "service": "dgen-ping",
            "status": "error",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }

# Development utilities (only in debug mode)
if settings.DEBUG:
    @app.get("/debug/config", tags=["Debug"])
    async def debug_config(token: TokenPayload = Depends(get_token_payload)):
        """Get configuration information (debug only)."""
        return {
            "debug": settings.DEBUG,
            "allow_default_token": settings.ALLOW_DEFAULT_TOKEN,
            "max_concurrency": settings.MAX_CONCURRENCY,
            "rate_limit": settings.RATE_LIMIT,
            "database_connected": db.is_connected,
            "csv_fallback_dir": settings.CSV_FALLBACK_DIR,
            "host": settings.HOST,
            "port": settings.PORT,
            "jwt_algorithm": settings.JWT_ALGORITHM,
            "timestamp": datetime.utcnow().isoformat()
        }

    @app.get("/debug/state", tags=["Debug"])
    async def debug_state(token: TokenPayload = Depends(get_token_payload)):
        """Get internal state information (debug only)."""
        proxy_state = {}
        if hasattr(ProxyService, "_semaphore") and ProxyService._semaphore is not None:
            try:
                proxy_state = {
                    "semaphore_value": ProxyService._semaphore._value,
                    "active_requests": settings.MAX_CONCURRENCY - ProxyService._semaphore._value,
                    "max_concurrency": settings.MAX_CONCURRENCY
                }
            except Exception as e:
                proxy_state = {"error": str(e)}
        
        return {
            "proxy_service": proxy_state,
            "database": {
                "connected": db.is_connected,
                "connection_attempts": getattr(db, '_connection_attempts', 0),
                "use_csv_fallback": getattr(db, '_use_csv_fallback', False)
            },
            "authentication": {
                "token_type": "JWT" if token.token_id != "default_user" else "default",
                "project_id": token.project_id,
                "user_id": token.token_id
            },
            "timestamp": datetime.utcnow().isoformat()
        }

# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with service information."""
    return {
        "service": "dgen-ping",
        "version": "1.0.0",
        "description": "LLM proxy with telemetry tracking and robust error handling",
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": {
            "health": "/health",
            "docs": "/docs" if settings.DEBUG else "disabled",
            "llm_completion": "/api/llm/completion",
            "metrics": "/metrics",
            "info": "/info"
        }
    }

# Application entry point
if __name__ == "__main__":
    import asyncio
    import uvicorn
    import signal
    import sys
    
    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        sys.exit(0)
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Validate configuration before starting
    try:
        logger.info("Validating configuration...")
        settings.validate_settings()
        logger.info("✅ Configuration valid")
    except Exception as e:
        logger.error(f"❌ Configuration validation failed: {e}")
        sys.exit(1)
    
    # Determine number of workers based on environment
    # Use single worker for development/debug mode to enable reload
    workers = 1 if settings.DEBUG else min(settings.WORKERS, 4)
    
    # Log startup information
    logger.info("=" * 60)
    logger.info("🚀 Starting dgen-ping LLM Proxy Service")
    logger.info("=" * 60)
    logger.info(f"Host: {settings.HOST}")
    logger.info(f"Port: {settings.PORT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"Workers: {workers}")
    logger.info(f"Max concurrency: {settings.MAX_CONCURRENCY}")
    logger.info(f"Rate limit: {settings.RATE_LIMIT} req/min")
    logger.info(f"Allow default token: {settings.ALLOW_DEFAULT_TOKEN}")
    logger.info(f"Database: {'MongoDB' if settings.MONGO_URI else 'CSV Fallback'}")
    logger.info("=" * 60)
    
    # Configure uvicorn settings
    uvicorn_config = {
        "app": "main:app",
        "host": settings.HOST,
        "port": settings.PORT,
        "log_level": "debug" if settings.DEBUG else "info",
        "access_log": settings.DEBUG,
        "server_header": False,  # Don't expose server version
        "date_header": False,    # Don't include date header
    }
    
    # Add reload only in debug mode and single worker
    if settings.DEBUG and workers == 1:
        uvicorn_config.update({
            "reload": True,
            "reload_dirs": ["."],
            "reload_includes": ["*.py"],
            "reload_excludes": ["*.pyc", "__pycache__", ".git"]
        })
        logger.info("🔄 Auto-reload enabled (debug mode)")
    else:
        uvicorn_config["workers"] = workers
        logger.info(f"👥 Multi-worker mode: {workers} workers")
    
    # Additional production settings
    if not settings.DEBUG:
        uvicorn_config.update({
            "loop": "uvloop",  # Use uvloop for better performance
            "http": "httptools",  # Use httptools for better HTTP parsing
            "backlog": 2048,   # Increase connection backlog
            "timeout_keep_alive": 5,  # Keep-alive timeout
            "timeout_graceful_shutdown": 30,  # Graceful shutdown timeout
        })
        logger.info("⚡ Production optimizations enabled")
    
    try:
        # Pre-flight checks
        logger.info("🔍 Running pre-flight checks...")
        
        # Check if port is available
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((settings.HOST, settings.PORT))
                logger.info(f"✅ Port {settings.PORT} is available")
            except OSError as e:
                logger.error(f"❌ Port {settings.PORT} is not available: {e}")
                logger.error(f"   Please choose a different port or stop the service using port {settings.PORT}")
                sys.exit(1)
        
        # Test imports
        try:
            from db import db
            from proxy import ProxyService
            logger.info("✅ Core modules imported successfully")
        except ImportError as e:
            logger.error(f"❌ Failed to import core modules: {e}")
            sys.exit(1)
        
        # Initialize async components if needed
        if hasattr(asyncio, 'run'):
            # Python 3.7+
            async def async_startup_check():
                """Async startup validation."""
                try:
                    # Quick database connection test
                    await db.initialize()
                    logger.info(f"✅ Database status: {'Connected' if db.is_connected else 'CSV Fallback'}")
                    
                    # Initialize proxy service
                    await ProxyService.initialize()
                    logger.info("✅ Proxy service initialized")
                    
                    return True
                except Exception as e:
                    logger.warning(f"⚠️  Startup check warning: {e}")
                    return True  # Continue anyway, services will handle errors
            
            # Run async startup check
            startup_ok = asyncio.run(async_startup_check())
            if not startup_ok:
                logger.error("❌ Startup checks failed")
                sys.exit(1)
        
        logger.info("✅ All pre-flight checks passed")
        logger.info(f"🌐 API will be available at: http://{settings.HOST}:{settings.PORT}")
        if settings.DEBUG:
            logger.info(f"📚 API documentation: http://{settings.HOST}:{settings.PORT}/docs")
        logger.info("🏥 Health check: http://{settings.HOST}:{settings.PORT}/health")
        logger.info("=" * 60)
        
        # Start the server
        uvicorn.run(**uvicorn_config)
        
    except KeyboardInterrupt:
        logger.info("\n⏹️  Server stopped by user (Ctrl+C)")
        sys.exit(0)
    except SystemExit:
        # Re-raise SystemExit to allow proper exit
        raise
    except Exception as e:
        logger.error(f"❌ Server startup failed: {e}")
        logger.error("Full error details:", exc_info=True)
        
        # Provide helpful error messages
        if "port" in str(e).lower() or "address" in str(e).lower():
            logger.error(f"💡 Port {settings.PORT} might be in use. Try:")
            logger.error(f"   - Use a different port: PORT=8002 python main.py")
            logger.error(f"   - Kill existing process: lsof -ti:{settings.PORT} | xargs kill")
        
        if "permission" in str(e).lower():
            logger.error("💡 Permission denied. Try:")
            logger.error("   - Use a port > 1024 (e.g., 8001)")
            logger.error("   - Run with appropriate permissions")
        
        sys.exit(1)
    finally:
        logger.info("🔚 Server shutdown complete") = 0
        if time_window_hours > 168:  # Max 1 week
            time_window_hours = 168

        if db.is_connected:
            # Build query filter
            from datetime import timedelta
            window_start = datetime.utcnow() - timedelta(hours=time_window_hours)
            
            query = {
                "timestamp": {"$gte": window_start}
            }
            
            if event_type:
                query["event_type"] = event_type
            if soeid:
                query["metadata.soeid"] = soeid
            if project:
                query["metadata.project_name"] = project

            # Get telemetry events from MongoDB
            collection = db.async_client[settings.DB_NAME].telemetry
            cursor = collection.find(query).sort("timestamp", -1).skip(skip).limit(limit)
            events = await cursor.to_list(limit)

            # Format for response
            formatted_events = []
            for event in events:
                event["event_id"] = str(event["_id"])  # Convert ObjectId to string
                event.pop("_id", None)  # Remove original _id
                if isinstance(event.get("timestamp"), datetime):
                    event["timestamp"] = event["timestamp"].isoformat()
                formatted_events.append(event)

            total_count = await collection.count_documents(query)

            return {
                "total": total_count,
                "skip": skip,
                "limit": limit,
                "time_window_hours": time_window_hours,
                "filters": {
                    "event_type": event_type,
                    "soeid": soeid,
                    "project": project
                },
                "results": formatted_events,
                "source": "database",
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            return {
                "total": 0,
                "skip": skip,
                "limit": limit,
                "time_window_hours": time_window_hours,
                "results": [],
                "source": "csv_fallback",
                "note": "Database not connected, using CSV fallback. Telemetry data limited.",
                "timestamp": datetime.utcnow().isoformat()
            }

    except Exception as e:
        logger.error(f"Error retrieving telemetry events: {e}")
        return {
            "total": 0,
            "skip": skip,
            "limit": limit,
            "time_window_hours": time_window_hours,
            "results": [],
            "error": str(e),
            "source": "error",
            "timestamp": datetime.utcnow().isoformat()
        }

# History and data endpoints
@app.get("/llm-history", tags=["LLM"])
async def get_llm_history(
    request: Request,
    limit: int = 10,
    skip: int = 0,
    soeid: str = None,
    project: str = None,
    token: TokenPayload = Depends(get_token_payload)
):
    """Get historical LLM runs with filtering options and error handling."""
    try:
        # Validate parameters
        if limit > 100:
            limit = 100  # Cap at 100 for performance
        if limit < 1:
            limit = 10
        if skip < 0:
            skip
