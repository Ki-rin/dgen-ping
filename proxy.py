
"""Proxy service for routing LLM requests using dgen_llm library with comprehensive telemetry."""
import time
import uuid
import logging
import asyncio
import concurrent.futures
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import Request, HTTPException
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE, HTTP_500_INTERNAL_SERVER_ERROR

from config import settings
from models import TelemetryEvent, RequestMetadata, LlmRequest, LlmResponse
from db import db

# Import the dgen_llm package with better error handling
try:
    from dgen_llm import llm_connection
    LLM_AVAILABLE = True
    logger = logging.getLogger("dgen-ping.proxy")
    logger.info("dgen_llm imported successfully")
except ImportError as e:
    try:
        # Try alternative import name
        from dgen_llm import llm_connector as llm_connection
        LLM_AVAILABLE = True
        logger = logging.getLogger("dgen-ping.proxy")
        logger.info("dgen_llm imported as llm_connector")
    except ImportError:
        LLM_AVAILABLE = False
        logger = logging.getLogger("dgen-ping.proxy")
        logger.error("dgen_llm package is not available. LLM functionality will be disabled.")
        logger.error(f"Import error: {e}")
        # Create a mock for development/testing
        class MockLLMConnection:
            @staticmethod
            def generate_content(prompt: str) -> str:
                return f"[MOCK RESPONSE] This is a simulated response to: {prompt[:50]}..."
        llm_connection = MockLLMConnection()

# Set up connection pool for high-concurrency
MAX_CONCURRENCY = settings.MAX_CONCURRENCY
RETRY_ATTEMPTS = settings.RETRY_ATTEMPTS
LLM_TIMEOUT = settings.LLM_TIMEOUT

class ProxyService:
    """Service for handling LLM requests using dgen_llm library with comprehensive telemetry."""
    
    # Semaphore for limiting concurrent requests
    _semaphore: Optional[asyncio.Semaphore] = None
    _executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
    
    @classmethod
    async def initialize(cls):
        """Initialize the proxy service with thread pool for blocking calls."""
        if cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        
        if cls._executor is None:
            # Create thread pool for blocking LLM calls
            cls._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=min(MAX_CONCURRENCY, 32),  # Reasonable thread limit
                thread_name_prefix="llm-worker"
            )
        
        logger.info(f"ProxyService initialized with max concurrency: {MAX_CONCURRENCY}")
        logger.info(f"Thread pool created with max workers: {min(MAX_CONCURRENCY, 32)}")
        logger.info(f"LLM library available: {LLM_AVAILABLE}")
        return cls
    
    @classmethod
    async def shutdown(cls):
        """Shutdown the proxy service and cleanup resources."""
        if cls._executor:
            logger.info("Shutting down LLM thread pool...")
            cls._executor.shutdown(wait=True, timeout=30)
            cls._executor = None
        logger.info("ProxyService shutdown completed")
    
    @staticmethod
    async def proxy_request(target: str, request: Request, payload: LlmRequest, token_payload) -> LlmResponse:
        """
        Process an LLM request using dgen_llm library with comprehensive telemetry logging.
        
        Args:
            target: Target service identifier (unused, for API compatibility)
            request: Original request
            payload: LLM request payload
            token_payload: Authentication token payload
            
        Returns:
            Response with LLM-generated content
            
        Raises:
            HTTPException: For various error conditions
        """
        if ProxyService._semaphore is None or ProxyService._executor is None:
            await ProxyService.initialize()
            
        start_time = time.time()
        request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
        
        # Extract request data with defaults
        prompt = payload.prompt.strip()
        model = payload.model or settings.DEFAULT_MODEL
        temperature = payload.temperature if payload.temperature is not None else settings.DEFAULT_TEMPERATURE
        max_tokens = payload.max_tokens or settings.DEFAULT_MAX_TOKENS
        
        # Additional validation
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt cannot be empty after stripping whitespace")
        
        # Calculate prompt length for telemetry
        request_size = len(prompt)
        
        logger.info(f"Proxy processing LLM request {request_id} - Model: {model}, Prompt length: {request_size}")

        # Log the start of the LLM request processing
        await ProxyService._log_llm_request_start(
            request=request,
            request_id=request_id,
            soeid=payload.soeid,
            project_name=payload.project_name,
            token_payload=token_payload,
            model=model,
            prompt_length=request_size,
            temperature=temperature,
            max_tokens=max_tokens
        )

        # Use semaphore to limit concurrent requests
        async with ProxyService._semaphore:
            for attempt in range(1, RETRY_ATTEMPTS + 1):
                attempt_start_time = time.time()
                
                try:
                    logger.info(f"Processing LLM request {request_id} (attempt {attempt}/{RETRY_ATTEMPTS})")
                    
                    # Check if LLM library is available
                    if not LLM_AVAILABLE:
                        logger.warning("LLM library not available, using mock response")
                    
                    # Call dgen_llm in thread pool to avoid blocking the event loop
                    try:
                        completion_text = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(
                                ProxyService._executor,
                                llm_connection.generate_content,
                                prompt
                            ),
                            timeout=LLM_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        raise HTTPException(
                            status_code=HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"LLM request timed out after {LLM_TIMEOUT} seconds"
                        )
                    
                    # Validate response
                    if completion_text is None:
                        raise ValueError("LLM returned None response")
                    
                    if not isinstance(completion_text, str):
                        completion_text = str(completion_text)
                    
                    # Calculate response size and latency
                    response_size = len(completion_text)
                    latency_ms = (time.time() - start_time) * 1000
                    attempt_latency_ms = (time.time() - attempt_start_time) * 1000
                    
                    # Token counting with better estimation
                    prompt_tokens = max(1, ProxyService._estimate_tokens(prompt))
                    completion_tokens = max(1, ProxyService._estimate_tokens(completion_text)) if completion_text else 0
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
                        "request_id": request_id,
                        "attempt": attempt,
                        "attempt_latency_ms": attempt_latency_ms,
                        "success": True,
                        "llm_available": LLM_AVAILABLE,
                        "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt,
                        "completion_preview": completion_text[:100] + "..." if len(completion_text) > 100 else completion_text,
                        "token_efficiency": completion_tokens / max_tokens if max_tokens > 0 else 0,
                        "chars_per_token_ratio": len(completion_text) / completion_tokens if completion_tokens > 0 else 0
                    }
                    
                    # Log successful completion telemetry
                    await ProxyService._log_llm_completion_success(
                        request=request,
                        request_id=request_id,
                        soeid=payload.soeid,
                        project_name=payload.project_name,
                        token_payload=token_payload,
                        model=model,
                        latency_ms=latency_ms,
                        token_counts=token_counts,
                        request_size=request_size,
                        response_size=response_size,
                        additional_data=additional_data
                    )
                    
                    # Log detailed LLM run for analytics (async to avoid blocking)
                    asyncio.create_task(ProxyService._log_detailed_llm_run(
                        request=request,
                        request_id=request_id,
                        soeid=payload.soeid,
                        project_name=payload.project_name,
                        token_payload=token_payload,
                        prompt=prompt,
                        completion=completion_text,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        latency_ms=latency_ms,
                        token_counts=token_counts
                    ))
                    
                    logger.info(f"LLM request {request_id} completed successfully in {latency_ms/1000:.2f}s (attempt {attempt})")
                    
                    # Return response
                    return LlmResponse(
                        completion=completion_text,
                        model=model,
                        metadata={
                            "request_id": request_id,
                            "latency": latency_ms / 1000,
                            "attempt_latency": attempt_latency_ms / 1000,
                            "tokens": token_counts,
                            "attempt": attempt,
                            "attempts_total": RETRY_ATTEMPTS,
                            "timestamp": datetime.utcnow().isoformat(),
                            "llm_available": LLM_AVAILABLE,
                            **additional_data
                        }
                    )
                    
                except asyncio.TimeoutError:
                    # Handle timeout specifically
                    attempt_latency_ms = (time.time() - attempt_start_time) * 1000
                    error_msg = f"LLM request timed out after {LLM_TIMEOUT} seconds"
                    
                    await ProxyService._log_llm_attempt_failure(
                        request=request,
                        request_id=request_id,
                        soeid=payload.soeid,
                        project_name=payload.project_name,
                        token_payload=token_payload,
                        model=model,
                        attempt=attempt,
                        latency_ms=attempt_latency_ms,
                        error=error_msg,
                        request_size=request_size,
                        error_type="TimeoutError"
                    )
                    
                    if attempt < RETRY_ATTEMPTS:
                        logger.warning(f"LLM request {request_id} timed out, retrying ({attempt}/{RETRY_ATTEMPTS})")
                        await asyncio.sleep(min(attempt * 2, 10))  # Exponential backoff, max 10s
                        continue
                    else:
                        raise HTTPException(
                            status_code=HTTP_503_SERVICE_UNAVAILABLE,
                            detail=error_msg
                        )
                
                except Exception as e:
                    attempt_latency_ms = (time.time() - attempt_start_time) * 1000
                    error_msg = str(e)
                    error_type = type(e).__name__
                    
                    # Log the failed attempt
                    await ProxyService._log_llm_attempt_failure(
                        request=request,
                        request_id=request_id,
                        soeid=payload.soeid,
                        project_name=payload.project_name,
                        token_payload=token_payload,
                        model=model,
                        attempt=attempt,
                        latency_ms=attempt_latency_ms,
                        error=error_msg,
                        request_size=request_size,
                        error_type=error_type
                    )
                    
                    if attempt < RETRY_ATTEMPTS:
                        logger.warning(f"LLM request {request_id} failed: {error_msg}, retrying ({attempt}/{RETRY_ATTEMPTS})")
                        await asyncio.sleep(min(attempt * 2, 10))  # Exponential backoff
                        continue
                    
                    # All attempts failed - log final failure and raise
                    final_latency_ms = (time.time() - start_time) * 1000
                    logger.error(f"Error processing LLM request {request_id} after {RETRY_ATTEMPTS} attempts: {error_msg}")
                    
                    await ProxyService._log_llm_final_failure(
                        request=request,
                        request_id=request_id,
                        soeid=payload.soeid,
                        project_name=payload.project_name,
                        token_payload=token_payload,
                        model=model,
                        latency_ms=final_latency_ms,
                        error=error_msg,
                        attempts=RETRY_ATTEMPTS,
                        request_size=request_size,
                        error_type=error_type
                    )
                    
                    # Determine appropriate HTTP status code
                    if isinstance(e, HTTPException):
                        raise e
                    elif "timeout" in error_msg.lower():
                        raise HTTPException(
                            status_code=HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"LLM request timed out after {RETRY_ATTEMPTS} attempts"
                        )
                    else:
                        raise HTTPException(
                            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"LLM request failed after {RETRY_ATTEMPTS} attempts: {error_msg}"
                        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """
        Estimate token count for text.
        This is a rough approximation - real token counting would require the actual tokenizer.
        """
        if not text:
            return 0
        
        # Better estimation based on common patterns
        # Average token length varies by language and content type
        # English: ~4 chars per token, Code: ~3 chars per token, Technical: ~5 chars per token
        
        # Simple heuristic: count words and adjust
        words = len(text.split())
        chars = len(text)
        
        # Estimate based on character count (conservative)
        char_based = max(1, chars // 4)
        
        # Estimate based on word count (liberal)
        word_based = max(1, int(words * 1.3))  # Account for subword tokens
        
        # Use the average of both methods
        estimated = max(1, (char_based + word_based) // 2)
        
        return estimated

    @staticmethod
    async def _log_llm_request_start(request, request_id, soeid, project_name, token_payload, 
                                   model, prompt_length, temperature, max_tokens):
        """Log the start of an LLM request."""
        try:
            event = TelemetryEvent(
                event_type="llm_request_start",
                request_id=request_id,
                client_ip=request.client.host,
                metadata=RequestMetadata(
                    client_id=token_payload.project_id,
                    soeid=soeid,
                    project_name=project_name,
                    target_service="llm_proxy",
                    endpoint="/proxy/llm",
                    method=request.method,
                    status_code=0,  # Not yet determined
                    latency_ms=0,  # Not yet calculated
                    request_size=prompt_length,
                    llm_model=model,
                    additional_data={
                        "model": model,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "prompt_length": prompt_length,
                        "stage": "request_start",
                        "llm_available": LLM_AVAILABLE,
                        "max_attempts": RETRY_ATTEMPTS,
                        "timeout_seconds": LLM_TIMEOUT
                    }
                )
            )
            await db.log_telemetry(event)
        except Exception as e:
            logger.error(f"Failed to log LLM request start: {e}")

    @staticmethod
    async def _log_llm_completion_success(request, request_id, soeid, project_name, token_payload,
                                        model, latency_ms, token_counts, request_size, response_size,
                                        additional_data):
        """Log successful LLM completion."""
        try:
            event = TelemetryEvent(
                event_type="llm_completion_success",
                request_id=request_id,
                client_ip=request.client.host,
                metadata=RequestMetadata(
                    client_id=token_payload.project_id,
                    soeid=soeid,
                    project_name=project_name,
                    target_service="llm_proxy",
                    endpoint="/proxy/llm/completion",
                    method=request.method,
                    status_code=200,
                    latency_ms=latency_ms,
                    request_size=request_size,
                    response_size=response_size,
                    prompt_tokens=token_counts["prompt"],
                    completion_tokens=token_counts["completion"],
                    total_tokens=token_counts["total"],
                    llm_model=model,
                    llm_latency=latency_ms,
                    additional_data=additional_data
                )
            )
            await db.log_telemetry(event)
        except Exception as e:
            logger.error(f"Failed to log LLM completion success: {e}")

    @staticmethod
    async def _log_detailed_llm_run(request, request_id, soeid, project_name, token_payload,
                                  prompt, completion, model, temperature, max_tokens, latency_ms, token_counts):
        """Log detailed LLM run for analytics and debugging."""
        try:
            # Truncate long content for storage efficiency
            truncated_prompt = prompt[:1000] + "..." if len(prompt) > 1000 else prompt
            truncated_completion = completion[:1000] + "..." if len(completion) > 1000 else completion
            
            event = TelemetryEvent(
                event_type="llm_run_detailed",
                request_id=request_id,
                client_ip=request.client.host,
                metadata=RequestMetadata(
                    client_id=token_payload.project_id,
                    soeid=soeid,
                    project_name=project_name,
                    target_service="llm_direct",
                    endpoint="/llm/generate",
                    method="INTERNAL",
                    status_code=200,
                    latency_ms=latency_ms,
                    request_size=len(prompt),
                    response_size=len(completion),
                    prompt_tokens=token_counts["prompt"],
                    completion_tokens=token_counts["completion"],
                    total_tokens=token_counts["total"],
                    llm_model=model,
                    llm_latency=latency_ms,
                    additional_data={
                        "prompt": truncated_prompt,
                        "completion": truncated_completion,
                        "model": model,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "request_id": request_id,
                        "timestamp": datetime.utcnow().isoformat(),
                        "token_efficiency": token_counts["completion"] / max_tokens if max_tokens > 0 else 0,
                        "chars_per_token_prompt": len(prompt) / token_counts["prompt"] if token_counts["prompt"] > 0 else 0,
                        "chars_per_token_completion": len(completion) / token_counts["completion"] if token_counts["completion"] > 0 else 0,
                        "prompt_length": len(prompt),
                        "completion_length": len(completion),
                        "llm_available": LLM_AVAILABLE
                    }
                )
            )
            await db.log_telemetry(event)
        except Exception as e:
            logger.error(f"Failed to log detailed LLM run: {e}")

    @staticmethod
    async def _log_llm_attempt_failure(request, request_id, soeid, project_name, token_payload,
                                     model, attempt, latency_ms, error, request_size, error_type="Unknown"):
        """Log individual attempt failure."""
        try:
            event = TelemetryEvent(
                event_type="llm_attempt_failure",
                request_id=request_id,
                client_ip=request.client.host,
                metadata=RequestMetadata(
                    client_id=token_payload.project_id,
                    soeid=soeid,
                    project_name=project_name,
                    target_service="llm_proxy",
                    endpoint="/proxy/llm",
                    method=request.method,
                    status_code=500,
                    latency_ms=latency_ms,
                    request_size=request_size,
                    llm_model=model,
                    llm_latency=latency_ms,
                    additional_data={
                        "attempt": attempt,
                        "max_attempts": RETRY_ATTEMPTS,
                        "error": error[:500],  # Truncate long errors
                        "error_type": error_type,
                        "model": model,
                        "stage": "attempt_failure",
                        "llm_available": LLM_AVAILABLE,
                        "timeout_seconds": LLM_TIMEOUT
                    }
                )
            )
            await db.log_telemetry(event)
        except Exception as e:
            logger.error(f"Failed to log LLM attempt failure: {e}")

    @staticmethod
    async def _log_llm_final_failure(request, request_id, soeid, project_name, token_payload,
                                   model, latency_ms, error, attempts, request_size, error_type="Unknown"):
        """Log final failure after all attempts exhausted."""
        try:
            event = TelemetryEvent(
                event_type="llm_request_failure",
                request_id=request_id,
                client_ip=request.client.host,
                metadata=RequestMetadata(
                    client_id=token_payload.project_id,
                    soeid=soeid,
                    project_name=project_name,
                    target_service="llm_proxy",
                    endpoint="/proxy/llm",
                    method=request.method,
                    status_code=503,
                    latency_ms=latency_ms,
                    request_size=request_size,
                    llm_model=model,
                    llm_latency=latency_ms,
                    additional_data={
                        "total_attempts": attempts,
                        "final_error": error[:500],  # Truncate long errors
                        "error_type": error_type,
                        "model": model,
                        "stage": "final_failure",
                        "llm_available": LLM_AVAILABLE,
                        "timeout_seconds": LLM_TIMEOUT
                    }
                )
            )
            await db.log_telemetry(event)
        except Exception as e:
            logger.error(f"Failed to log LLM final failure: {e}")

    @staticmethod
    async def get_telemetry_summary(time_window_minutes: int = 60) -> Dict[str, Any]:
        """Get telemetry summary for LLM requests."""
        try:
            if not db.is_connected:
                return {
                    "error": "Database not connected",
                    "fallback_mode": True,
                    "time_window_minutes": time_window_minutes
                }
            
            window_start = datetime.utcnow() - timedelta(minutes=time_window_minutes)
            
            collection = db.async_client[settings.DB_NAME].telemetry
            
            # Aggregate telemetry data
            pipeline = [
                {
                    "$match": {
                        "timestamp": {"$gte": window_start},
                        "event_type": {"$in": [
                            "llm_request_start", 
                            "llm_completion_success", 
                            "llm_request_failure",
                            "llm_attempt_failure"
                        ]}
                    }
                },
                {
                    "$group": {
                        "_id": "$event_type",
                        "count": {"$sum": 1},
                        "avg_latency": {"$avg": "$metadata.latency_ms"},
                        "total_tokens": {"$sum": "$metadata.total_tokens"},
                        "avg_tokens": {"$avg": "$metadata.total_tokens"},
                        "total_prompt_tokens": {"$sum": "$metadata.prompt_tokens"},
                        "total_completion_tokens": {"$sum": "$metadata.completion_tokens"}
                    }
                }
            ]
            
            results = await collection.aggregate(pipeline).to_list(None)
            
            summary = {
                "time_window_minutes": time_window_minutes,
                "window_start": window_start.isoformat(),
                "window_end": datetime.utcnow().isoformat(),
                "requests_started": 0,
                "requests_completed": 0,
                "requests_failed": 0,
                "attempts_failed": 0,
                "avg_latency_ms": 0,
                "total_tokens_used": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "avg_tokens_per_request": 0,
                "success_rate": 0,
                "failure_rate": 0,
                "retry_rate": 0,
                "llm_available": LLM_AVAILABLE
            }
            
            for result in results:
                event_type = result["_id"]
                count = result["count"]
                
                if event_type == "llm_request_start":
                    summary["requests_started"] = count
                elif event_type == "llm_completion_success":
                    summary["requests_completed"] = count
                    summary["avg_latency_ms"] = round(result.get("avg_latency", 0), 2)
                    summary["total_tokens_used"] = result.get("total_tokens", 0)
                    summary["total_prompt_tokens"] = result.get("total_prompt_tokens", 0)
                    summary["total_completion_tokens"] = result.get("total_completion_tokens", 0)
                    summary["avg_tokens_per_request"] = round(result.get("avg_tokens", 0), 2)
                elif event_type == "llm_request_failure":
                    summary["requests_failed"] = count
                elif event_type == "llm_attempt_failure":
                    summary["attempts_failed"] = count
            
            # Calculate rates
            total_requests = summary["requests_completed"] + summary["requests_failed"]
            if total_requests > 0:
                summary["success_rate"] = round(summary["requests_completed"] / total_requests, 4)
                summary["failure_rate"] = round(summary["requests_failed"] / total_requests, 4)
            
            if summary["requests_completed"] > 0:
                summary["retry_rate"] = round(summary["attempts_failed"] / summary["requests_completed"], 2)
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting telemetry summary: {e}")
            return {
                "error": str(e),
                "time_window_minutes": time_window_minutes,
                "llm_available": LLM_AVAILABLE
            }

    @staticmethod
    async def get_service_stats() -> Dict[str, Any]:
        """Get current service statistics."""
        try:
            stats = {
                "llm_available": LLM_AVAILABLE,
                "max_concurrency": MAX_CONCURRENCY,
                "retry_attempts": RETRY_ATTEMPTS,
                "timeout_seconds": LLM_TIMEOUT,
                "semaphore_initialized": ProxyService._semaphore is not None,
                "executor_initialized": ProxyService._executor is not None
            }
            
            if ProxyService._semaphore:
                stats["available_slots"] = ProxyService._semaphore._value
                stats["active_requests"] = MAX_CONCURRENCY - ProxyService._semaphore._value
                stats["utilization_percent"] = round(
                    (stats["active_requests"] / MAX_CONCURRENCY) * 100, 2
                ) if MAX_CONCURRENCY > 0 else 0
            
            if ProxyService._executor:
                stats["thread_pool_size"] = ProxyService._executor._max_workers
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting service stats: {e}")
            return {
                "error": str(e),
                "llm_available": LLM_AVAILABLE
            }

    @staticmethod
    async def _log_error_telemetry(
        request, request_id, soeid, project_name, target, path, 
        status_code, start_time, token_payload, request_size, error
    ):
        """Log telemetry for failed requests (legacy method for backward compatibility)."""
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
        """Record telemetry for proxied request (legacy method for backward compatibility)."""
        try:
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
                response
