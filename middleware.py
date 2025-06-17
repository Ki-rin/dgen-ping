"""Middleware for request/response processing in dgen-ping."""
import time
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR
from starlette.responses import JSONResponse
from models import TelemetryEvent, RequestMetadata
from db import db

logger = logging.getLogger("dgen-ping.middleware")

class TelemetryMiddleware(BaseHTTPMiddleware):
    """Middleware for capturing request/response telemetry."""
    
    async def dispatch(self, request: Request, call_next):
        """Process request and capture telemetry."""
        # Skip telemetry for system endpoints
        path = request.url.path
        if path in ["/health", "/docs", "/openapi.json", "/redoc"] or path.startswith("/static"):
            return await call_next(request)
            
        # Start timing
        start_time = time.time()
        request_id = f"req-{int(start_time * 1000)}"
        request.state.request_id = request_id
        
        # Process request
        status_code = 500  # Default status code if something goes wrong
        response = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as e:
            logger.error(f"Request error: {str(e)}")
            status_code = HTTP_500_INTERNAL_SERVER_ERROR
            raise
        finally:
            # Only log if response completed or errored out
            try:
                # Skip logging for insignificant requests
                if request.method not in ["OPTIONS"] and not path.startswith("/docs"):
                    duration_ms = (time.time() - start_time) * 1000
                    
                    # Get client ID from auth token if available
                    client_id = getattr(request.state, "token_payload", None)
                    client_id = getattr(client_id, "project_id", "anonymous") if client_id else "anonymous"
                    
                    # Create and log telemetry record
                    metadata = RequestMetadata(
                        client_id=client_id,
                        soeid=request.headers.get("X-User-ID") or "anonymous",
                        target_service="dgen-ping",
                        endpoint=path,
                        method=request.method,
                        status_code=status_code,
                        latency_ms=duration_ms,
                        request_size=int(request.headers.get("content-length", 0)) or None,
                        response_size=getattr(response, "content_length", None) if response else None
                    )
                    
                    event = TelemetryEvent(
                        event_type="direct_request",
                        metadata=metadata,
                        client_ip=request.client.host if request.client else "unknown",
                        request_id=request_id
                    )
                    
                    # Log telemetry asynchronously to avoid blocking
                    try:
                        await db.log_telemetry(event)
                    except Exception as log_error:
                        logger.error(f"Failed to log telemetry: {log_error}")
            except Exception as e:
                logger.error(f"Error logging telemetry: {str(e)}")

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware."""
    
    def __init__(self, app, rate_limit_per_minute=120):
        super().__init__(app)
        self.rate_limit = rate_limit_per_minute
        self.clients = {}
    
    async def dispatch(self, request: Request, call_next):
        """Apply rate limiting to requests."""
        # Skip rate limiting for health checks and docs
        if request.url.path in ["/health", "/public/health", "/docs", "/openapi.json", "/redoc"]:
            return await call_next(request)
            
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()
        
        # Clean up old entries
        self._cleanup(current_time)
        
        # Check rate limit
        if client_ip in self.clients:
            requests = self.clients[client_ip]["requests"]
            window_start = self.clients[client_ip]["window_start"]
            
            if current_time - window_start < 60:
                if requests >= self.rate_limit:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": "Rate limit exceeded",
                            "message": f"Maximum {self.rate_limit} requests per minute allowed",
                            "retry_after": 60 - int(current_time - window_start),
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(current_time))
                        }
                    )
                self.clients[client_ip]["requests"] += 1
            else:
                # Reset window
                self.clients[client_ip] = {
                    "requests": 1,
                    "window_start": current_time
                }
        else:
            # New client
            self.clients[client_ip] = {
                "requests": 1,
                "window_start": current_time
            }
        
        return await call_next(request)
    
    def _cleanup(self, current_time):
        """Clean up expired rate limit entries."""
        to_delete = [ip for ip, data in self.clients.items() 
                     if current_time - data["window_start"] >= 60]
        for ip in to_delete:
            del self.clients[ip]
