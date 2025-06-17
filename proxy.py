"""LLM proxy service for dgen-ping."""
import time
import logging
from datetime import datetime
from fastapi import HTTPException, Request
from models import LlmRequest, LlmResponse, TokenPayload
from config import settings

# Import dgen_llm
try:
    from dgen_llm import llm_connection
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    raise ImportError("dgen_llm package is required. Please install it using pip.")

logger = logging.getLogger("dgen-ping.proxy")

class ProxyService:
    @staticmethod
    async def initialize():
        """Initialize proxy service."""
        logger.info(f"ProxyService initialized - LLM Available: {LLM_AVAILABLE}")
    
    @staticmethod
    async def proxy_request(service_type: str, request: Request, payload: LlmRequest, token: TokenPayload) -> LlmResponse:
        """Proxy request to LLM service."""
        if service_type != "llm":
            raise HTTPException(status_code=400, detail=f"Unknown service type: {service_type}")
        
        if not payload.prompt or not payload.prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt cannot be empty")
        
        start_time = time.time()
        
        try:
            # Call dgen_llm for completion
            completion = llm_connection.generate_content(
                prompt=payload.prompt.strip(),
                model=payload.model or settings.DEFAULT_MODEL,
                temperature=payload.temperature or settings.DEFAULT_TEMPERATURE,
                max_tokens=payload.max_tokens or settings.DEFAULT_MAX_TOKENS
            )
            
            if not completion:
                raise HTTPException(status_code=500, detail="LLM returned empty response")
            
            # Calculate metrics
            latency_ms = (time.time() - start_time) * 1000
            prompt_tokens = max(1, len(payload.prompt) // 4)
            completion_tokens = max(1, len(completion) // 4)
            
            return LlmResponse(
                completion=completion,
                model=payload.model or settings.DEFAULT_MODEL,
                metadata={
                    "request_id": getattr(request.state, 'request_id', None),
                    "latency": latency_ms / 1000,
                    "tokens": {
                        "prompt": prompt_tokens,
                        "completion": completion_tokens,
                        "total": prompt_tokens + completion_tokens
                    },
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
        except Exception as e:
            logger.error(f"LLM request failed: {str(e)}")
            raise HTTPException(status_code=500, detail=f"LLM request failed: {str(e)}")
