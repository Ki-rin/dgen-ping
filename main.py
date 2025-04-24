"""dgen-ping: LLM proxy service with telemetry tracking."""
import logging
import os
import uuid
import time
import asyncio
from fastapi import FastAPI, Request, Depends, Body, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
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
        # Initialize database connection
        await db.initialize()
        
        # Initialize the ProxyService
        await ProxyService.initialize()
        
        # Determine environment
        env = "kubernetes" if os.environ.get("KUBERNETES_SERVICE_HOST") else "standalone"
        
        # Log application startup
        startup_metadata = {
            "environment": env,
            "concurrency": settings.MAX_CONCURRENCY,
            "host": settings.HOST,
            "port": settings.PORT,
            "debug": settings.DEBUG,
            "database_connected": db.is_connected
        }
        
        await db.log_connection_event(
            "application_startup",
            "success",
            f"dgen-ping LLM proxy started in {env} environment",
            startup_metadata
        )
        
        logger.info(f"dgen-ping LLM proxy started in {env} environment (concurrency: {settings.MAX_CONCURRENCY})")
    except Exception as e:
        logger.error(f"Startup error: {e}")
        
        # Try to log the error even if initialization failed
        try:
            await db.log_connection_event(
                "application_startup",
                "error",
                f"Startup error: {str(e)}",
                {"error": str(e)}
            )
        except:
            pass

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    try:
        # Log application shutdown
        await db.log_connection_event(
            "application_shutdown",
            "success",
            "dgen-ping service shutdown",
            {"shutdown_time": datetime.utcnow().isoformat()}
        )
        
        logger.info("dgen-ping service shutdown")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "database": "connected" if db.is_connected else "fallback (csv)",
        "default_token": settings.ALLOW_DEFAULT_TOKEN,
        "services": ["llm_direct"],  # Using direct llm_connection instead of downstream services
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
        # Process request using dgen_llm
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
    # Route to completion handler for API compatibility
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
    metrics = await db.get_metrics()
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "requests_total": metrics.get("requests_total", 0),
        "requests_last_hour": metrics.get("requests_last_hour", 0),
        "avg_latency_ms": metrics.get("avg_latency_ms", 0),
        "error_rate": metrics.get("error_rate", 0),
        "token_usage_total": metrics.get("token_usage_total", 0),
        "llm_runs_total": metrics.get("llm_runs_total", 0),
        "database_status": metrics.get("database_status", "unknown")
    }

@app.get("/llm-history", tags=["LLM"])
async def get_llm_history(
    request: Request,
    limit: int = 10,
    skip: int = 0,
    soeid: str = None,
    project: str = None,
    token: TokenPayload = Depends(get_token_payload)
):
    """Get historical LLM runs with filtering options."""
    try:
        if db.is_connected:
            # Build query filter
            query = {}
            if soeid:
                query["soeid"] = soeid
            if project:
                query["project_name"] = project
            
            # Get LLM runs from MongoDB
            llm_runs = await db.async_client[settings.DB_NAME].llm_runs.find(
                query
            ).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)
            
            # Format for response
            formatted_runs = []
            for run in llm_runs:
                # Convert ObjectId to string
                run["_id"] = str(run["_id"])
                # Format timestamps
                if isinstance(run.get("timestamp"), datetime):
                    run["timestamp"] = run["timestamp"].isoformat()
                formatted_runs.append(run)
            
            return {
                "total": await db.async_client[settings.DB_NAME].llm_runs.count_documents(query),
                "skip": skip,
                "limit": limit,
                "runs": formatted_runs
            }
        else:
            # If using CSV fallback, return empty list
            return {
                "total": 0,
                "skip": skip,
                "limit": limit,
                "runs": [],
                "note": "Database not connected, using CSV fallback. Historical data not available."
            }
    except Exception as e:
        logger.error(f"Error retrieving LLM history: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving LLM history: {str(e)}")

@app.get("/db-status", tags=["System"])
async def get_db_status(token: TokenPayload = Depends(get_token_payload)):
    """Get database connection status and information."""
    try:
        if db.is_connected:
            # If connected, get collection counts
            telemetry_count = await db.async_client[settings.DB_NAME].telemetry.count_documents({})
            llm_runs_count = await db.async_client[settings.DB_NAME].llm_runs.count_documents({})
            connection_logs_count = await db.async_client[settings.DB_NAME].connection_logs.count_documents({})
            
            # Get latest connection events
            latest_events = await db.async_client[settings.DB_NAME].connection_logs.find().sort(
                "timestamp", -1
            ).limit(5).to_list(5)
            
            # Format connection events
            formatted_events = []
            for event in latest_events:
                event["_id"] = str(event["_id"])
                if isinstance(event.get("timestamp"), datetime):
                    event["timestamp"] = event["timestamp"].isoformat()
                formatted_events.append(event)
            
            return {
                "status": "connected",
                "database": settings.DB_NAME,
                "collections": {
                    "telemetry": telemetry_count,
                    "llm_runs": llm_runs_count,
                    "connection_logs": connection_logs_count
                },
                "latest_connection_events": formatted_events
            }
        else:
            # If using CSV fallback
            csv_files = []
            if os.path.exists(settings.CSV_FALLBACK_DIR):
                csv_files = [f for f in os.listdir(settings.CSV_FALLBACK_DIR) if f.endswith('.csv')]
            
            return {
                "status": "fallback",
                "fallback_mode": "csv",
                "fallback_directory": settings.CSV_FALLBACK_DIR,
                "csv_files": csv_files
            }
    except Exception as e:
        logger.error(f"Error getting database status: {e}")
        return {
            "status": "error",
            "error": str(e)
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