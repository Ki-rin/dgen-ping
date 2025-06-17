"""dgen-ping: LLM proxy service with telemetry tracking and robust error handling."""
import os
import uuid
import time
import logging
from fastapi import FastAPI, Request, Depends, Body, BackgroundTasks, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
from config import settings
from db import db
from auth import get_token_payload, get_token_payload_optional, TokenPayload, AuthManager, DGEN_KEY
from proxy import ProxyService
from models import TelemetryEvent, LlmRequest, LlmResponse
from middleware import TelemetryMiddleware, RateLimitMiddleware

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("dgen-ping")

# Create FastAPI app with error handling
app = FastAPI(
    title="dgen-ping",
    description="LLM proxy with telemetry tracking and robust error handling",
    version="1.0.0"
)

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for better error reporting."""
    logger.error(f"Unhandled exception in {request.url.path}: {str(exc)}", exc_info=True)
    
    # Try to log the error (best effort)
    try:
        await db.log_connection_event(
            "unhandled_exception",
            "error", 
            f"Unhandled exception in {request.url.path}: {str(exc)}",
            {"path": str(request.url.path), "method": request.method}
        )
    except:
        pass  # Don't fail if logging fails
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": "An unexpected error occurred",
            "request_id": getattr(request.state, 'request_id', 'unknown')
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
    """Initialize services on startup with comprehensive error handling."""
    startup_success = True
    startup_errors = []

    try:
        # Initialize database connection (with fallback)
        await db.initialize()
        logger.info(f"Database initialization: {'Connected' if db.is_connected else 'CSV Fallback'}")
    except Exception as e:
        startup_errors.append(f"Database initialization failed: {e}")
        logger.error(f"Database initialization failed: {e}")

    try:
        # Initialize the ProxyService
        await ProxyService.initialize()
        logger.info("ProxyService initialized successfully")
    except Exception as e:
        startup_errors.append(f"ProxyService initialization failed: {e}")
        logger.error(f"ProxyService initialization failed: {e}")
        startup_success = False

    # Determine environment
    env = "kubernetes" if os.environ.get("KUBERNETES_SERVICE_HOST") else "standalone"

    # Create startup metadata
    startup_metadata = {
        "environment": env,
        "concurrency": settings.MAX_CONCURRENCY,
        "host": settings.HOST,
        "port": settings.PORT,
        "debug": settings.DEBUG,
        "database_connected": db.is_connected,
        "csv_fallback": not db.is_connected,
        "startup_success": startup_success,
        "errors": startup_errors
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
        logger.info(f"dgen-ping started successfully in {env} environment (concurrency: {settings.MAX_CONCURRENCY})")
    else:
        logger.warning(f"dgen-ping started with errors in {env} environment")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
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

@app.get("/health", tags=["system"])
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
            except:
                proxy_health["active_requests"] = "unknown"

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
                "debug": settings.DEBUG
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "error",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }

@app.post("/api/llm/completion", response_model=LlmResponse, tags=["LLM"])
async def llm_completion(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: LlmRequest = Body(...),
    token: TokenPayload = Depends(get_token_payload)
):
    """Process an LLM completion request with comprehensive error handling."""
    start_time = time.time()
    request_id = str(uuid.uuid4())

    logger.info(f"LLM request from {payload.soeid} (project: {payload.project_name}), prompt length: {len(payload.prompt)}")

    try:
        # Process request using ProxyService
        result = await ProxyService.proxy_request("llm", request, payload, token)

        # Log response metrics
        processing_time = time.time() - start_time
        logger.info(f"LLM request {request_id} completed in {processing_time:.2f}s, response length: {len(result.completion)}")

        return result
        
    except HTTPException:
        # Re-raise HTTP exceptions (they're already properly formatted)
        raise
    except Exception as e:
        logger.error(f"Error processing LLM request: {str(e)}")
        
        # Try to log the error
        try:
            await db.log_connection_event(
                "llm_request_error",
                "error",
                f"LLM request failed: {str(e)}",
                {
                    "request_id": request_id,
                    "soeid": payload.soeid,
                    "project": payload.project_name,
                    "error": str(e)
                }
            )
        except:
            pass  # Don't fail if logging fails
        
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
    """Process an LLM chat request (alias for completion)."""
    return await llm_completion(request, background_tasks, payload, token)

@app.post("/telemetry", tags=["Telemetry"])
async def telemetry_event(
    request: Request,
    event: TelemetryEvent,
    token: TokenPayload = Depends(get_token_payload),
):
    """Log a telemetry event with error handling."""
    event.metadata.client_id = token.project_id
    event.request_id = event.request_id or str(uuid.uuid4())

    try:
        success = await db.log_telemetry(event)
        return {
            "status": "success" if success else "partial",
            "message": "Telemetry recorded" if success else "Telemetry recorded with fallback",
            "request_id": event.request_id
        }
    except Exception as e:
        logger.error(f"Telemetry logging failed: {e}")
        return {
            "status": "error",
            "message": f"Telemetry logging failed: {str(e)}",
            "request_id": event.request_id
        }

@app.get("/info", tags=["System"])
async def get_info(token: TokenPayload = Depends(get_token_payload)):
    """Get detailed service information."""
    try:
        active_requests = "unknown"
        if hasattr(ProxyService, "_semaphore") and ProxyService._semaphore is not None:
            try:
                active_requests = settings.MAX_CONCURRENCY - ProxyService._semaphore._value
            except AttributeError:
                active_requests = "unknown"

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
                "status": "connected" if db.is_connected else "csv_fallback",
                "fallback_active": not db.is_connected
            },
            "performance": {
                "active_requests": active_requests,
                "max_concurrency": settings.MAX_CONCURRENCY
            }
        }
    except Exception as e:
        logger.error(f"Error getting service info: {e}")
        return {
            "service": "dgen-ping",
            "version": "1.0.0",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }

@app.get("/metrics", tags=["System"])
async def get_metrics(token: TokenPayload = Depends(get_token_payload)):
    """Get system metrics with error handling."""
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
            "requests_last_hour": 0,
            "avg_latency_ms": 0,
            "error_rate": 0,
            "token_usage_total": 0,
            "llm_runs_total": 0,
            "database_status": "error"
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
    """Get historical LLM runs with filtering options and error handling."""
    try:
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
                "source": "database"
            }
        else:
            return {
                "total": 0,
                "skip": skip,
                "limit": limit,
                "results": [],
                "source": "csv_fallback",
                "note": "Database not connected, using CSV fallback. Historical data limited."
            }

    except Exception as e:
        logger.error(f"Error retrieving LLM history: {e}")
        return {
            "total": 0,
            "skip": skip,
            "limit": limit,
            "results": [],
            "error": str(e),
            "source": "error"
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

        return health

    except Exception as e:
        logger.error(f"Error getting database status: {e}")
        return {
            "status": "error",
            "error": str(e),
            "database_connected": False
        }

# Token management endpoints
@app.post("/generate-token", tags=["Authentication"])
async def generate_token_endpoint(
    soeid: str = Body(..., embed=True),
    project_id: str = Body(default=None, embed=True),
    x_token_secret: str = Header(...)
):
    """Generate a JWT token for a user. Only SOEID is required."""
    if x_token_secret != DGEN_KEY:
        raise HTTPException(status_code=403, detail="Invalid token secret")

    try:
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
            "note": "project_id defaults to soeid if not specified"
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
    soeid: str = Body(..., embed=True),
    x_token_secret: str = Header(...)
):
    """Generate a JWT token for a user with only SOEID required."""
    if x_token_secret != DGEN_KEY:
        raise HTTPException(status_code=403, detail="Invalid token secret")

    try:
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
            "algorithm": "HS256"
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
    token: str = Body(..., embed=True),
    x_token_secret: str = Header(...)
):
    """Verify a JWT token with enhanced error handling."""
    if x_token_secret != DGEN_KEY:
        raise HTTPException(status_code=403, detail="Invalid token secret")

    try:
        # Clean token input
        clean_token = str(token).strip()
        
        # Basic validation
        if not clean_token:
            return {
                "valid": False,
                "error": "Empty token",
                "type": "JWT"
            }
        
        # Check for common encoding issues
        if len(clean_token.encode('utf-8')) != len(clean_token):
            return {
                "valid": False,
                "error": "Token contains non-ASCII characters",
                "type": "JWT"
            }
        
        # Verify token
        payload = AuthManager.verify_token(token=clean_token)
        return {
            "valid": True,
            "data": {
                "soeid": payload.token_id,
                "project_id": payload.project_id,
                "expires_at": payload.expires_at
            },
            "type": "JWT"
        }
    except HTTPException as e:
        return {
            "valid": False,
            "error": e.detail,
            "type": "JWT",
            "status_code": e.status_code
        }
    except UnicodeDecodeError as e:
        return {
            "valid": False,
            "error": f"Token encoding error: {str(e)}",
            "type": "JWT",
            "suggestion": "Ensure token contains only valid UTF-8 characters"
        }
    except Exception as e:
        return {
            "valid": False,
            "error": f"Unexpected error: {str(e)}",
            "type": "JWT"
        }

# Optional public endpoints (no authentication required)
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
            except:
                active_requests = 0

        return {
            "service": "dgen-ping",
            "status": "operational",
            "timestamp": datetime.utcnow().isoformat(),
            "load": {
                "active_requests": active_requests,
                "max_concurrency": settings.MAX_CONCURRENCY,
                "utilization_percent": round((active_requests / settings.MAX_CONCURRENCY) * 100, 1)
            }
        }
    except Exception as e:
        return {
            "service": "dgen-ping",
            "status": "error",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=settings.WORKERS if not settings.DEBUG else 1
    )
