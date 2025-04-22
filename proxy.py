"""Proxy service for routing LLM requests to downstream services."""
import time
import uuid
import httpx
import logging
import asyncio
from fastapi import Request, HTTPException
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE
from config import settings
from models import TelemetryEvent, RequestMetadata, LlmRequest, LlmResponse
from db import db

logger = logging.getLogger("dgen-ping.proxy")

# Set up connection pool for high-concurrency
MAX_CONNECTIONS = 100
TIMEOUT_SECONDS = 60
RETRY_ATTEMPTS = 3

class ProxyService:
    """Service for proxying requests to downstream LLM services."""
    
    # Create a shared httpx client for connection pooling
    _client = None
    _semaphore = None
    
    @classmethod
    async def get_client(cls):
        """Get or create httpx client with connection pooling."""
        if cls._client is None:
            limits = httpx.Limits(
                max_connections=MAX_CONNECTIONS,
                max_keepalive_connections=MAX_CONNECTIONS // 2
            )
            cls._client = httpx.AsyncClient(
                limits=limits,
                timeout=TIMEOUT_SECONDS,
                follow_redirects=True
            )
            # Initialize semaphore
            cls._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENCY)
            logger.info(f"Initialized proxy client with {settings.MAX_CONCURRENCY} concurrent connections")
        return cls._client
    
    @staticmethod
    async def proxy_request(target: str, request: Request, payload: LlmRequest, token_payload):
        """
        Proxy an LLM request to a downstream service and record telemetry.
        
        Args:
            target: Target service identifier
            request: Original request
            payload: LLM request payload
            token_payload: Authentication token payload
            
        Returns:
            Response from downstream service
        """
        # Make sure client is initialized
        if ProxyService._client is None or ProxyService._semaphore is None:
            await ProxyService.get_client()
            
        start_time = time.time()
        request_id = str(uuid.uuid4())
        
        # Check if target service exists
        if target not in settings.DOWNSTREAM_SERVICES:
            raise HTTPException(status_code=404, detail=f"Service '{target}' not found")
            
        target_url = settings.DOWNSTREAM_SERVICES[target]
        
        # Extract path and build target URL
        path = request.url.path
        service_path = path.replace(f"/api/{target}", "", 1) or "/"
        full_url = f"{target_url}{service_path}"
        
        # Calculate prompt length
        request_size = len(payload.prompt)
        
        # Prepare headers
        headers = dict(request.headers)
        headers["X-Forwarded-For"] = request.client.host
        headers["X-Project-ID"] = token_payload.project_id
        headers["X-Request-ID"] = request_id
        headers["X-SOEID"] = payload.soeid
        headers["X-Project-Name"] = payload.project_name
        
        if "host" in headers:
            del headers["host"]
            
        # Use semaphore to limit concurrent requests
        async with ProxyService._semaphore:
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    # Make request to downstream service
                    response = await ProxyService._client.request(
                        method=request.method,
                        url=full_url,
                        json=payload.model_dump(),
                        headers=headers,
                        timeout=TIMEOUT_SECONDS
                    )
                    
                    # Calculate request time
                    latency_ms = (time.time() - start_time) * 1000
                    
                    # Extract metrics and response data
                    response_json = response.json()
                    response_size = len(response.content)
                    
                    # Extract token counts and model info
                    llm_model, llm_latency, token_counts, additional_data = ProxyService._extract_llm_metrics(response_json)
                    
                    # Log telemetry
                    await ProxyService._log_telemetry(
                        request=request,
                        request_id=request_id,
                        soeid=payload.soeid,
                        project_name=payload.project_name,
                        target=target,
                        service_path=service_path,
                        status_code=response.status_code,
                        latency_ms=latency_ms,
                        token_payload=token_payload,
                        llm_model=llm_model,
                        llm_latency=llm_latency,
                        token_counts=token_counts,
                        additional_data=additional_data,
                        request_size=request_size,
                        response_size=response_size
                    )
                    
                    # Return response as LlmResponse
                    if response.status_code == 200:
                        return LlmResponse(
                            completion=response_json.get("completion") or response_json.get("text") or response_json.get("content", ""),
                            model=llm_model or "unknown",
                            metadata={
                                "request_id": request_id,
                                "latency": latency_ms / 1000,
                                "tokens": token_counts,
                                **additional_data
                            }
                        )
                    else:
                        # Handle non-200 responses
                        raise HTTPException(
                            status_code=response.status_code,
                            detail=response_json.get("detail") or "Error from LLM service"
                        )
                        
                except httpx.TimeoutException:
                    if attempt < RETRY_ATTEMPTS - 1:
                        logger.warning(f"Request to {target} timed out, retrying ({attempt+1}/{RETRY_ATTEMPTS})")
                        continue
                    logger.error(f"Request to {target} timed out after {RETRY_ATTEMPTS} attempts")
                    await ProxyService._log_error_telemetry(
                        request, request_id, payload.soeid, payload.project_name, target, service_path, 
                        503, start_time, token_payload, request_size, "Timeout"
                    )
                    raise HTTPException(
                        status_code=HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Request to {target} service timed out"
                    )
                
                except httpx.RequestError as e:
                    if attempt < RETRY_ATTEMPTS - 1:
                        logger.warning(f"Request to {target} failed: {str(e)}, retrying ({attempt+1}/{RETRY_ATTEMPTS})")
                        continue
                    logger.error(f"Error proxying to {target}: {str(e)}")
                    await ProxyService._log_error_telemetry(
                        request, request_id, payload.soeid, payload.project_name, target, service_path, 
                        503, start_time, token_payload, request_size, str(e)
                    )
                    raise HTTPException(
                        status_code=HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Error communicating with {target} service: {str(e)}"
                    )
                
                except Exception as e:
                    logger.error(f"Unexpected error proxying to {target}: {str(e)}")
                    await ProxyService._log_error_telemetry(
                        request, request_id, payload.soeid, payload.project_name, target, service_path, 
                        500, start_time, token_payload, request_size, str(e)
                    )
                    raise HTTPException(
                        status_code=500,
                        detail=f"Unexpected error: {str(e)}"
                    )
    
    @staticmethod
    def _extract_llm_metrics(response_json):
        """Extract LLM metrics from response."""
        llm_model = None
        llm_latency = None
        token_counts = {"prompt": 0, "completion": 0, "total": 0}
        additional_data = {}
        
        try:
            # Try to extract standard fields
            if "model" in response_json:
                llm_model = response_json["model"]
            
            if "latency" in response_json:
                llm_latency = response_json["latency"]
            
            # Extract token counts
            usage = response_json.get("usage", {})
            if usage:
                token_counts["prompt"] = usage.get("prompt_tokens", 0)
                token_counts["completion"] = usage.get("completion_tokens", 0)
                token_counts["total"] = usage.get("total_tokens", 0)
            
            # Extract any additional metadata
            metadata = response_json.get("metadata", {})
            if metadata:
                additional_data = metadata
        except Exception as e:
            logger.warning(f"Error extracting LLM metrics: {e}")
            
        return llm_model, llm_latency, token_counts, additional_data
    
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
        except Exception as e:
            logger.error(f"Error logging telemetry: {e}")
"""Proxy service for routing LLM requests to downstream services."""
import time
import uuid
import httpx
import logging
import asyncio
from fastapi import Request, HTTPException
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE
from config import settings
from models import TelemetryEvent, RequestMetadata, LlmRequest, LlmResponse
from db import db

logger = logging.getLogger("dgen-ping.proxy")

# Set up connection pool for high-concurrency
MAX_CONNECTIONS = 100
TIMEOUT_SECONDS = 60
RETRY_ATTEMPTS = 3

class ProxyService:
    """Service for proxying requests to downstream LLM services."""
    
    # Create a shared httpx client for connection pooling
    _client = None
    _semaphore = None
    
    @classmethod
    async def get_client(cls):
        """Get or create httpx client with connection pooling."""
        if cls._client is None:
            limits = httpx.Limits(
                max_connections=MAX_CONNECTIONS,
                max_keepalive_connections=MAX_CONNECTIONS // 2
            )
            cls._client = httpx.AsyncClient(
                limits=limits,
                timeout=TIMEOUT_SECONDS,
                follow_redirects=True
            )
            # Initialize semaphore
            cls._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENCY)
            logger.info(f"Initialized proxy client with {settings.MAX_CONCURRENCY} concurrent connections")
        return cls._client
    
    @staticmethod
    async def proxy_request(target: str, request: Request, payload: LlmRequest, token_payload):
        """
        Proxy an LLM request to a downstream service and record telemetry.
        
        Args:
            target: Target service identifier
            request: Original request
            payload: LLM request payload
            token_payload: Authentication token payload
            
        Returns:
            Response from downstream service
        """
        # Make sure client is initialized
        if ProxyService._client is None or ProxyService._semaphore is None:
            await ProxyService.get_client()
            
        start_time = time.time()
        request_id = str(uuid.uuid4())
        
        # Check if target service exists
        if target not in settings.DOWNSTREAM_SERVICES:
            raise HTTPException(status_code=404, detail=f"Service '{target}' not found")
            
        target_url = settings.DOWNSTREAM_SERVICES[target]
        
        # Extract path and build target URL
        path = request.url.path
        service_path = path.replace(f"/api/{target}", "", 1) or "/"
        full_url = f"{target_url}{service_path}"
        
        # Calculate prompt length
        request_size = len(payload.prompt)
        
        # Prepare headers
        headers = dict(request.headers)
        headers["X-Forwarded-For"] = request.client.host
        headers["X-Project-ID"] = token_payload.project_id
        headers["X-Request-ID"] = request_id
        headers["X-SOEID"] = payload.soeid
        headers["X-Project-Name"] = payload.project_name
        
        if "host" in headers:
            del headers["host"]
            
        # Use semaphore to limit concurrent requests
        async with ProxyService._semaphore:
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    # Make request to downstream service
                    response = await ProxyService._client.request(
                        method=request.method,
                        url=full_url,
                        json=payload.model_dump(),
                        headers=headers,
                        timeout=TIMEOUT_SECONDS
                    )
                    
                    # Calculate request time
                    latency_ms = (time.time() - start_time) * 1000
                    
                    # Extract metrics and response data
                    response_json = response.json()
                    response_size = len(response.content)
                    
                    # Extract token counts and model info
                    llm_model, llm_latency, token_counts, additional_data = ProxyService._extract_llm_metrics(response_json)
                    
                    # Log telemetry
                    await ProxyService._log_telemetry(
                        request=request,
                        request_id=request_id,
                        soeid=payload.soeid,
                        project_name=payload.project_name,
                        target=target,
                        service_path=service_path,
                        status_code=response.status_code,
                        latency_ms=latency_ms,
                        token_payload=token_payload,
                        llm_model=llm_model,
                        llm_latency=llm_latency,
                        token_counts=token_counts,
                        additional_data=additional_data,
                        request_size=request_size,
                        response_size=response_size
                    )
                    
                    # Return response as LlmResponse
                    if response.status_code == 200:
                        return LlmResponse(
                            completion=response_json.get("completion") or response_json.get("text") or response_json.get("content", ""),
                            model=llm_model or "unknown",
                            metadata={
                                "request_id": request_id,
                                "latency": latency_ms / 1000,
                                "tokens": token_counts,
                                **additional_data
                            }
                        )
                    else:
                        # Handle non-200 responses
                        raise HTTPException(
                            status_code=response.status_code,
                            detail=response_json.get("detail") or "Error from LLM service"
                        )
                        
                except httpx.TimeoutException:
                    if attempt < RETRY_ATTEMPTS - 1:
                        logger.warning(f"Request to {target} timed out, retrying ({attempt+1}/{RETRY_ATTEMPTS})")
                        continue
                    logger.error(f"Request to {target} timed out after {RETRY_ATTEMPTS} attempts")
                    await ProxyService._log_error_telemetry(
                        request, request_id, payload.soeid, payload.project_name, target, service_path, 
                        503, start_time, token_payload, request_size, "Timeout"
                    )
                    raise HTTPException(
                        status_code=HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Request to {target} service timed out"
                    )
                
                except httpx.RequestError as e:
                    if attempt < RETRY_ATTEMPTS - 1:
                        logger.warning(f"Request to {target} failed: {str(e)}, retrying ({attempt+1}/{RETRY_ATTEMPTS})")
                        continue
                    logger.error(f"Error proxying to {target}: {str(e)}")
                    await ProxyService._log_error_telemetry(
                        request, request_id, payload.soeid, payload.project_name, target, service_path, 
                        503, start_time, token_payload, request_size, str(e)
                    )
                    """Proxy service for routing LLM requests to downstream services."""
import time
import uuid
import httpx
import logging
import asyncio
from fastapi import Request, HTTPException
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE
from config import settings
from models import TelemetryEvent, RequestMetadata, LlmRequest, LlmResponse
from db import db

logger = logging.getLogger("dgen-ping.proxy")

# Set up connection pool for high-concurrency
MAX_CONNECTIONS = 100
TIMEOUT_SECONDS = 60
RETRY_ATTEMPTS = 3

class ProxyService:
    """Service for proxying requests to downstream LLM services."""
    
    # Create a shared httpx client for connection pooling
    _client = None
    _semaphore = None
    
    @classmethod
    async def get_client(cls):
        """Get or create httpx client with connection pooling."""
        if cls._client is None:
            limits = httpx.Limits(
                max_connections=MAX_CONNECTIONS,
                max_keepalive_connections=MAX_CONNECTIONS // 2
            )
            cls._client = httpx.AsyncClient(
                limits=limits,
                timeout=TIMEOUT_SECONDS,
                follow_redirects=True
            )
            cls._semaphore = asyncio.Semaphore(MAX_CONNECTIONS * 2)
        return cls._client
    
    @staticmethod
    async def proxy_request(target: str, request: Request, payload: LlmRequest, token_payload):
        """
        Proxy an LLM request to a downstream service and record telemetry.
        
        Args:
            target: Target service identifier
            request: Original request
            payload: LLM request payload
            token_payload: Authentication token payload
            
        Returns:
            Response from downstream service
        """
        start_time = time.time()
        request_id = str(uuid.uuid4())
        
        # Check if target service exists
        if target not in settings.DOWNSTREAM_SERVICES:
            raise HTTPException(status_code=404, detail=f"Service '{target}' not found")
            
        target_url = settings.DOWNSTREAM_SERVICES[target]
        
        # Extract path and build target URL
        path = request.url.path
        service_path = path.replace(f"/api/{target}", "", 1) or "/"
        full_url = f"{target_url}{service_path}"
        
        # Calculate prompt length
        request_size = len(payload.prompt)
        
        # Prepare headers
        headers = dict(request.headers)
        headers["X-Forwarded-For"] = request.client.host
        headers["X-Project-ID"] = token_payload.project_id
        headers["X-Request-ID"] = request_id
        headers["X-SOEID"] = payload.soeid
        headers["X-Project-Name"] = payload.project_name
        
        if "host" in headers:
            del headers["host"]
            
        # Get httpx client
        client = await ProxyService.get_client()
        
        # Use semaphore to limit concurrent requests
        async with ProxyService._semaphore:
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    # Make request to downstream service
                    response = await client.request(
                        method=request.method,
                        url=full_url,
                        json=payload.model_dump(),
                        headers=headers,
                        timeout=TIMEOUT_SECONDS
                    )
                    
                    # Calculate request time
                    latency_ms = (time.time() - start_time) * 1000
                    
                    # Extract metrics and response data
                    response_json = response.json()
                    response_size = len(response.content)
                    
                    # Extract token counts and model info
                    llm_model, llm_latency, token_counts, additional_data = ProxyService._extract_llm_metrics(response_json)
                    
                    # Log telemetry
                    await ProxyService._log_telemetry(
                        request=request,
                        request_id=request_id,
                        soeid=payload.soeid,
                        project_name=payload.project_name,
                        target=target,
                        service_path=service_path,
                        status_code=response.status_code,
                        latency_ms=latency_ms,
                        token_payload=token_payload,
                        llm_model=llm_model,
                        llm_latency=llm_latency,
                        token_counts=token_counts,
                        additional_data=additional_data,
                        request_size=request_size,
                        response_size=response_size
                    )
                    
                    # Return response as LlmResponse
                    if response.status_code == 200:
                        return LlmResponse(
                            completion=response_json.get("completion") or response_json.get("text") or response_json.get("content", ""),
                            model=llm_model or "unknown",
                            metadata={
                                "request_id": request_id,
                                "latency": latency_ms / 1000,
                                "tokens": token_counts,
                                **additional_data
                            }
                        )
                    else:
                        # Handle non-200 responses
                        raise HTTPException(
                            status_code=response.status_code,
                            detail=response_json.get("detail") or "Error from LLM service"
                        )
                        
                except httpx.TimeoutException:
                    if attempt < RETRY_ATTEMPTS - 1:
                        logger.warning(f"Request to {target} timed out, retrying ({attempt+1}/{RETRY_ATTEMPTS})")
                        continue
                    logger.error(f"Request to {target} timed out after {RETRY_ATTEMPTS} attempts")
                    await ProxyService._log_error_telemetry(
                        request, request_id, payload.soeid, payload.project_name, target, service_path, 
                        503, start_time, token_payload, request_size, "Timeout"
                    )
                    raise HTTPException(
                        status_code=HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Request to {target} service timed out"
                    )
                
                except httpx.RequestError as e:
                    if attempt < RETRY_ATTEMPTS - 1:
                        logger.warning(f"Request to {target} failed: {str(e)}, retrying ({attempt+1}/{RETRY_ATTEMPTS})")
                        continue
                    logger.error(f"Error proxying to {target}: {str(e)}")
                    await ProxyService._log_error_telemetry(
                        request, request_id, payload.soeid, payload.project_name, target, service_path, 
                        503, start_time, token_payload, request_size, str(e)
                    )
                    raise HTTPException(
                        status_code=HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"Error communicating with {target} service: {str(e)}"
                    )
                
                except Exception as e:
                    logger.error(f"Unexpected error proxying to {target}: {str(e)}")
                    await ProxyService._log_error_telemetry(
                        request, request_id, payload.soeid, payload.project_name, target, service_path, 
                        500, start_time, token_payload, request_size, str(e)
                    )
                    raise HTTPException(
                        status_code=500,
                        detail=f"Unexpected error: {str(e)}"
                    )
    
    @staticmethod
    def _extract_llm_metrics(response_json):
        """Extract LLM metrics from response."""
        llm_model = None
        llm_latency = None
        token_counts = {"prompt": 0, "completion": 0, "total": 0}
        additional_data = {}
        
        # Try to extract standard fields
        if "model" in response_json:
            llm_model = response_json["model"]
        
        if "latency" in response_json:
            llm_latency = response_json["latency"]
        
        # Extract token counts
        usage = response_json.get("usage", {})
        if usage:
            token_counts["prompt"] = usage.get("prompt_tokens", 0)
            token_counts["completion"] = usage.get("completion_tokens", 0)
            token_counts["total"] = usage.get("total_tokens", 0)
        
        # Extract any additional metadata
        metadata = response_json.get("metadata", {})
        if metadata:
            additional_data = metadata
        
        return llm_model, llm_latency, token_counts, additional_data
    
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