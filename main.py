"""dgen-ping: API proxy with telemetry tracking."""
import logging
import os
from fastapi import FastAPI, Request, Depends, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
from config import settings
from db import db
from auth import get_token_payload, TokenPayload, DEFAULT_TOKEN
from proxy import ProxyService
from models import TelemetryEvent
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
    description="API proxy with telemetry tracking",
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
    app.add_middleware(RateLimitMiddleware, rate_limit_per_minute=120)

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    try:
        await db.initialize()
        env = "kubernetes" if os.environ.get("KUBERNETES_SERVICE_HOST") else "standalone"
        logger.info(f"dgen-ping started in {env} environment")
    except Exception as e:
        logger.error(f"Startup error: {e}")

@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "database": "connected" if db.is_connected else "fallback (csv)",
        "default_token": settings.ALLOW_DEFAULT_TOKEN,
        "services": list(settings.DOWNSTREAM_SERVICES.keys())
    }

@app.post("/api/classifier/{path:path}", tags=["Proxy"])
async def proxy_classifier(
    request: Request,
    path: str,
    token: TokenPayload = Depends(get_token_payload),
    payload: dict = Body(...)
):
    """Proxy requests to the classifier service."""
    return await ProxyService.proxy_request("classifier", request, payload, token)

@app.post("/api/enhancer/{path:path}", tags=["Proxy"])
async def proxy_enhancer(
    request: Request,
    path: str,
    token: TokenPayload = Depends(get_token_payload),
    payload: dict = Body(...)
):
    """Proxy requests to the enhancer service."""
    return await ProxyService.proxy_request("enhancer", request, payload, token)

@app.post("/telemetry", tags=["Telemetry"])
async def log_telemetry(
    request: Request,
    event: TelemetryEvent,
    token: TokenPayload = Depends(get_token_payload)
):
    """Log a telemetry event."""
    event.client_ip = request.client.host
    event.metadata.client_id = token.project_id
    await db.log_telemetry(event)
    return {"status": "success", "message": "Telemetry recorded"}

@app.get("/info", tags=["System"])
async def get_info(token: TokenPayload = Depends(get_token_payload)):
    """Get system information."""
    return {
        "service": "dgen-ping",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "project_id": token.project_id,
        "token_type": "default" if token.token_id == DEFAULT_TOKEN else "standard",
        "database": "connected" if db.is_connected else "fallback (csv)"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )