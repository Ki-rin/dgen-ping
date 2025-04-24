"""Proxy service for routing LLM requests using dgen_llm library."""
import time
import uuid
import logging
import asyncio
from fastapi import Request, HTTPException
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE
from config import settings
from models import TelemetryEvent, RequestMetadata, LlmRequest, LlmResponse
from db import db

# Import the dgen_llm package
try:
    from dgen_llm import llm_connection
except ImportError:
    raise ImportError("dgen_llm package is required. Please install it using pip.")

logger = logging.getLogger("dgen-ping.proxy")

# Set up connection pool for high-concurrency
MAX_CONCURRENCY = settings.MAX_CONCURRENCY
RETRY_ATTEMPTS = settings.RETRY_ATTEMPTS

class ProxyService:
    """Service for handling LLM requests using dgen_llm library."""
    
    # Semaphore for limiting concurrent requests
    _semaphore = None
    
    @classmethod
    async def initialize(cls):
        """Initialize the proxy service."""
        if cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        logger.info(f"ProxyService initialized with max concurrency: {MAX_CONCURRENCY}")
        return cls
    
    @staticmethod
    async def proxy_request(target: str, request: Request, payload: LlmRequest, token_payload):
        """
        Process an LLM request using dgen_llm library.
        
        Args:
            target: Target service identifier (unused, for API compatibility)
            request: Original request
            payload: LLM request payload
            token_payload: Authentication token payload
            
        Returns:
            Response with LLM-generated content
        """
        if ProxyService._semaphore is None:
            await ProxyService.initialize()
            
        start_time = time.time()
        request_id = str(uuid.uuid4())
        
        # Extract request data
        prompt = payload.prompt
        model = payload.model or settings.DEFAULT_MODEL
        temperature = payload.temperature or settings.DEFAULT_TEMPERATURE
        max_tokens = payload.max_tokens or settings.DEFAULT_MAX_TOKENS
        
        # Calculate prompt length for telemetry
        request_size = len(prompt)
        
        # Use semaphore to limit concurrent requests
        async with ProxyService._semaphore:
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    logger.info(f"Processing LLM request {request_id} (attempt {attempt+1}/{RETRY_ATTEMPTS})")
                    
                    # Call dgen_llm to generate content
                    # Note: This is a blocking call, but we're handling it with a semaphore
                    # to limit concurrency and not overwhelm the system
                    completion_text = llm_connection.generate_content(prompt)
                    
                    # Calculate response size
                    response_size = len(completion_text) if completion_text else 0
                    
                    # Calculate latency
                    latency_ms = (time.time() - start_time) * 1000
                    
                    # Simple token counting approximation
                    # ~4 characters per token is a rough estimate
                    prompt_tokens = max(1, len(prompt) // 4)
                    completion_tokens = max(1, len(completion_text) // 4) if completion_text else 0
                    total_tokens = prompt_tokens + completion_tokens
                    
                    # Prepare token counts for telemetry
                    token_counts = {
                        "prompt": prompt_tokens,
                        "completion": completion_tokens,
                        "total": total_tokens
                    }
                    
                    # Additional metadata
                    additional_data = {
                        "model": model,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "request_id": request_id
                    }
                    
                    # Log telemetry
                    await ProxyService._log_telemetry(
                        request=request,
                        request_id=request_id,
                        soeid=payload.soeid,
                        project_name=payload.project_name,
                        target="llm",
                        service_path="/completion",
                        status_code=200,
                        latency_ms=latency_ms,
                        token_payload=token_payload,
                        llm_model=model,
                        llm_latency=latency_ms,
                        token_counts=token_counts,
                        additional_data=additional_data,
                        request_size=request_size,
                        response_size=response_size
                    )
                    
                    logger.info(f"LLM request {request_id} completed in {latency_ms/1000:.2f}s")
                    
                    # Return response
                    return LlmResponse(
                        completion=completion_text,
                        model=model,
                        metadata={
                            "request_id": request_id,
                            "latency": latency_ms / 1000,
                            "tokens": token_counts,
                            **additional_data
                        }
                    )
                    
                except Exception as e:
                    if attempt < RETRY_ATTEMPTS - 1:
                        logger.warning(f"LLM request failed: {str(e)}, retrying ({attempt+1}/{RETRY_ATTEMPTS})")
                        continue
                    
                    logger.error(f"Error processing LLM request: {str(e)}")
                    
                    # Log error telemetry
                    await ProxyService._log_error_telemetry(
                        request, request_id, payload.soeid, payload.project_name, "llm", "/completion", 
                        500, start_time, token_payload, request_size, str(e)
                    )
                    
                    raise HTTPException(
                        status_code=HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Error processing LLM request: {str(e)}"
                    )
    
    @staticmethod
    async def _log_error_telemetry(
        request, request_id, soeid, project_name, target, path, 
        status_code, start_time, token_payload, request_size, error
    ):
        """Log telemetry for failed requests."""
        latency_ms = (time.time() - start_time) * 1000
        await ProxyService._log_telemetry(
            request=request,
            request_id=request_id,
            soeid=soeid,
            project_name=project_name,
            target=target,
            service_path=path,
            status_code=status_code,
            latency_ms=latency_ms,
            token_payload=token_payload,
            additional_data={"error": error},
            request_size=request_size
        )
    
    @staticmethod
    async def _log_telemetry(
        request, request_id, soeid, project_name, target, service_path, status_code, latency_ms, token_payload,
        llm_model=None, llm_latency=None, token_counts=None, additional_data=None,
        request_size=None, response_size=None
    ):
        """Record telemetry for proxied request."""
        metadata = RequestMetadata(
            client_id=token_payload.project_id,
            soeid=soeid,
            project_name=project_name,
            target_service=target,
            endpoint=service_path,
            method=request.method,
            status_code=status_code,
            latency_ms=latency_ms,
            request_size=request_size,
            response_size=response_size,
            prompt_tokens=token_counts["prompt"] if token_counts else None,
            completion_tokens=token_counts["completion"] if token_counts else None,
            total_tokens=token_counts["total"] if token_counts else None,
            llm_model=llm_model,
            llm_latency=llm_latency,
            additional_data=additional_data
        )
        
        event = TelemetryEvent(
            event_type="llm_request",
            request_id=request_id,
            metadata=metadata,
            client_ip=request.client.host
        )
        
        await db.log_telemetry(event)