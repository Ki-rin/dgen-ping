"""LLM proxy service for dgen-ping."""
import logging
from fastapi import HTTPException
from models import LlmRequest, LlmResponse

# Import dgen_llm with fallback
try:
    from dgen_llm import llm_connection
    LLM_AVAILABLE = True
except ImportError:
    class MockLLM:
        @staticmethod
        def generate_content(prompt: str) -> str:
            return f"[MOCK] Response to: {prompt[:50]}..."
    llm_connection = MockLLM()
    LLM_AVAILABLE = False

logger = logging.getLogger("dgen-ping.proxy")

async def process_llm_request(payload: LlmRequest) -> LlmResponse:
    """Process LLM request using dgen_llm."""
    if not payload.prompt or not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    
    try:
        completion = llm_connection.generate_content(payload.prompt.strip())
        
        if not completion:
            raise HTTPException(status_code=500, detail="LLM returned empty response")
        
        # Token estimation
        prompt_tokens = max(1, len(payload.prompt) // 4)
        completion_tokens = max(1, len(completion) // 4)
        
        return LlmResponse(
            completion=completion,
            model=payload.model or "gpt-4",
            metadata={
                "tokens": {
                    "prompt": prompt_tokens,
                    "completion": completion_tokens,
                    "total": prompt_tokens + completion_tokens
                },
                "llm_available": LLM_AVAILABLE
            }
        )
        
    except Exception as e:
        logger.error(f"LLM request failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"LLM request failed: {str(e)}")
