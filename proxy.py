"""Proxy service for routing requests to downstream services."""
import time
import httpx
import logging
from fastapi import Request, HTTPException
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE
from config import settings
from models import TelemetryEvent, RequestMetadata
from db import db

logger = logging.getLogger("dgen-ping.proxy")

class ProxyService:
    """Service for proxying requests to downstream services."""
    
    @staticmethod
    async def proxy_request(target: str, request: Request, payload: dict, token_payload):
        """Proxy a request to a downstream service and record telemetry."""
        start_time = time.time()
        
        # Check if target service exists
        if target not in settings.DOWNSTREAM_SERVICES:
            raise HTTPException(status_code=404, detail=f"Service '{target}' not found")
            
        target_url = settings.DOWNSTREAM_SERVICES[target]
        
        # Extract path and build target URL
        path = request.url.path
        service_path = path.replace(f"/api/{target}", "", 1) or "/"
        full_url = f"{target_url}{service_path}"
        
        # Prepare headers
        headers = dict(request.headers)
        headers["X-Forwarded-For"] = request.client.host
        headers["X-Project-ID"] = token_payload.project_id
        if "host" in headers:
            del headers["host"]
            
        try:
            # Make request to downstream service
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=request.method,
                    url=full_url,
                    json=payload,
                    headers=headers,
                    params=request.query_params,
                    timeout=30.0
                )
                
            # Extract metrics and log telemetry
            latency_ms = (time.time() - start_time) * 1000
            llm_model, llm_latency, metrics = ProxyService._extract_metrics(response)
            
            # Log telemetry
            await ProxyService._log_telemetry(
                request, target, service_path, response.status_code, latency_ms,
                token_payload, llm_model, llm_latency, metrics,
                len(str(payload)) if payload else None,
                len(response.content) if response.content else None
            )
            
            return response.json()
            
        except httpx.RequestError as e:
            logger.error(f"Error proxying to {target}: {str(e)}")
            
            # Log error telemetry
            await ProxyService._log_telemetry(
                request, target, service_path, 503, 
                (time.time() - start_time) * 1000, token_payload,
                additional_data={"error": str(e)}
            )
            
            raise HTTPException(
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Error communicating with {target} service: {str(e)}"
            )
    
    @staticmethod
    def _extract_metrics(response):
        """Extract metrics from response."""
        llm_model = None
        llm_latency = None
        additional_data = {}
        
        if response.status_code == 200:
            try:
                response_json = response.json()
                if "metadata" in response_json:
                    meta = response_json["metadata"]
                    llm_model = meta.get("model")
                    llm_latency = meta.get("latency")
                    if "metrics" in meta:
                        additional_data["metrics"] = meta["metrics"]
            except Exception as e:
                logger.warning(f"Error parsing response JSON: {e}")
                
        return llm_model, llm_latency, additional_data
    
    @staticmethod
    async def _log_telemetry(
        request, target, path, status_code, latency_ms, token_payload,
        llm_model=None, llm_latency=None, additional_data=None,
        request_size=None, response_size=None
    ):
        """Record telemetry for proxied request."""
        metadata = RequestMetadata(
            client_id=token_payload.project_id,
            user_id=request.headers.get("X-User-ID"),
            target_service=target,
            endpoint=path,
            method=request.method,
            status_code=status_code,
            latency_ms=latency_ms,
            request_size=request_size,
            response_size=response_size,
            llm_model=llm_model,
            llm_latency=llm_latency,
            additional_data=additional_data
        )
        
        event = TelemetryEvent(
            event_type="api_request",
            metadata=metadata,
            client_ip=request.client.host
        )
        
        await db.log_telemetry(event)