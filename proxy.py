"""Minimal proxy service for routing LLM requests using dgen_llm library."""
import time
import uuid
import logging
import asyncio
import concurrent.futures
from datetime import datetime
from typing import Optional
from fastapi import Request, HTTPException
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE, HTTP_500_INTERNAL_SERVER_ERROR

from config import settings
from models import LlmRequest, LlmResponse
from db import db

# Import dgen_llm with fallback to mock
try:
    from dgen_llm import llm_connection
    LLM_AVAILABLE = True
except ImportError:
    # Mock for development/testing
    class MockLLMConnection:
        @staticmethod
        def generate_content(prompt: str) -> str:
            return f"[MOCK] Response to: {prompt[:50]}..."
    llm_connection = MockLLMConnection()
    LLM_AVAILABLE = False

logger = logging.getLogger("dgen-ping.proxy")

class ProxyService:
    """Minimal service for handling LLM requests."""
    
    _semaphore: Optional[asyncio.Semaphore] = None
    _executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
    
    @classmethod
    async def initialize(cls):
        """Initialize the proxy service."""
        if cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENCY)
        
        if cls._executor is None:
            cls._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=min(settings.MAX_CONCURRENCY, 32),
                thread_name_prefix="llm-worker"
            )
        
        logger.info(f"ProxyService initialized - LLM available: {LLM_AVAILABLE}")
        return cls
    
    @staticmethod
    async def proxy_request(target: str, request: Request, payload: LlmRequest, token_payload) -> LlmResponse:
        """Process an LLM request using dgen_llm library."""
        
        if ProxyService._semaphore is None or ProxyService._executor is None:
            await ProxyService.initialize()
            
        start_time = time.time()
        request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
        
        # Validate prompt
        if payload.prompt is None:
            raise HTTPException(status_code=400, detail="Prompt is None")
        
        if not isinstance(payload.prompt, str):
            raise HTTPException(status_code=400, detail=f"Prompt must be string, got {type(payload.prompt)}")
        
        prompt = payload.prompt.strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt is empty")
        
        # Extract parameters
        model = payload.model or settings.DEFAULT_MODEL
        max_tokens = payload.max_tokens or settings.DEFAULT_MAX_TOKENS
        
        logger.info(f"LLM request {request_id}: {len(prompt)} chars")

        # Use semaphore to limit concurrent requests
        async with ProxyService._semaphore:
            for attempt in range(1, settings.RETRY_ATTEMPTS + 1):
                try:
                    logger.debug(f"Attempt {attempt}/{settings.RETRY_ATTEMPTS} for {request_id}")
                    
                    # Call dgen_llm in thread pool
                    completion_text = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            ProxyService._executor,
                            lambda: llm_connection.generate_content(prompt)
                        ),
                        timeout=settings.LLM_TIMEOUT
                    )
                    
                    # Validate response
                    if completion_text is None:
                        raise ValueError("LLM returned None")
                    
                    if not isinstance(completion_text, str):
                        completion_text = str(completion_text)
                    
                    # Calculate metrics
                    latency_ms = (time.time() - start_time) * 1000
                    prompt_tokens = max(1, len(prompt) // 4)  # Simple token estimation
                    completion_tokens = max(1, len(completion_text) // 4)
                    
                    logger.info(f"LLM request {request_id} completed in {latency_ms/1000:.2f}s")
                    
                    # Log basic telemetry
                    try:
                        await db.log_connection_event(
                            "llm_completion",
                            "success",
                            f"LLM request completed",
                            {
                                "request_id": request_id,
                                "soeid": payload.soeid,
                                "model": model,
                                "latency_ms": latency_ms,
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens
                            }
                        )
                    except Exception as e:
                        logger.error(f"Failed to log telemetry: {e}")
                    
                    # Return response
                    return LlmResponse(
                        completion=completion_text,
                        model=model,
                        metadata={
                            "request_id": request_id,
                            "latency": latency_ms / 1000,
                            "tokens": {
                                "prompt": prompt_tokens,
                                "completion": completion_tokens,
                                "total": prompt_tokens + completion_tokens
                            },
                            "attempt": attempt,
                            "timestamp": datetime.utcnow().isoformat(),
                            "llm_available": LLM_AVAILABLE
                        }
                    )
                    
                except asyncio.TimeoutError:
                    error_msg = f"LLM request timed out after {settings.LLM_TIMEOUT} seconds"
                    logger.warning(f"Request {request_id} attempt {attempt}: {error_msg}")
                    
                    if attempt < settings.RETRY_ATTEMPTS:
                        await asyncio.sleep(attempt * 2)  # Exponential backoff
                        continue
                    else:
                        raise HTTPException(
                            status_code=HTTP_503_SERVICE_UNAVAILABLE,
                            detail=error_msg
                        )
                
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Request {request_id} attempt {attempt}: {error_msg}")
                    
                    if attempt < settings.RETRY_ATTEMPTS:
                        await asyncio.sleep(attempt * 2)
                        continue
                    
                    # All attempts failed
                    logger.error(f"LLM request {request_id} failed after {settings.RETRY_ATTEMPTS} attempts")
                    
                    # Log error
                    try:
                        await db.log_connection_event(
                            "llm_error",
                            "error",
                            f"LLM request failed: {error_msg}",
                            {
                                "request_id": request_id,
                                "soeid": payload.soeid,
                                "attempts": settings.RETRY_ATTEMPTS,
                                "error": error_msg
                            }
                        )
                    except Exception:
                        pass
                    
                    # Determine appropriate HTTP status code
                    if isinstance(e, HTTPException):
                        raise e
                    elif "timeout" in error_msg.lower():
                        raise HTTPException(
                            status_code=HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"LLM request timed out"
                        )
                    else:
                        raise HTTPException(
                            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"LLM request failed: {error_msg}"
                        )

    @staticmethod
    async def get_service_stats():
        """Get current service statistics."""
        stats = {
            "llm_available": LLM_AVAILABLE,
            "max_concurrency": settings.MAX_CONCURRENCY,
            "retry_attempts": settings.RETRY_ATTEMPTS,
            "timeout_seconds": settings.LLM_TIMEOUT
        }
        
        if ProxyService._semaphore:
            available = ProxyService._semaphore._value
            active = settings.MAX_CONCURRENCY - available
            stats.update({
                "available_slots": available,
                "active_requests": active,
                "utilization_percent": round((active / settings.MAX_CONCURRENCY) * 100, 1)
            })
        
        return stats
