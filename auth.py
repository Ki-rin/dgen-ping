"""Authentication and authorization for dgen-ping with JWT-based tokens."""
import os
import jwt
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_401_UNAUTHORIZED
from typing import Optional
from models import TokenPayload

# Load secret key from environment variable
DGEN_KEY = os.getenv("TOKEN_SECRET", "dgen_secret_key")

# API key header security scheme
api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)

class AuthManager:
    """JWT-based authentication and authorization manager."""

    @staticmethod
    def generate_token(soeid: str, project_id: str = "default") -> str:
        """
        Generate a JWT token based on soeid and project_id.
        No expiration - tokens are permanent until secret changes.
        """
        if not soeid:
            raise HTTPException(status_code=400, detail="SOEID is required to generate a token")

        payload = {
            "soeid": soeid,
            "project_id": project_id,
            "iat": datetime.now(timezone.utc).timestamp(),  # Issued at
            "jti": str(uuid.uuid4())  # JWT ID for uniqueness
        }

        try:
            token = jwt.encode(payload, DGEN_KEY, algorithm="HS256")
            return token
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Token generation failed: {str(e)}")

    @staticmethod
    def verify_token(token: str) -> TokenPayload:
        """
        Verify JWT token using shared secret - no database lookup required.
        """
        if not token:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED, 
                detail="Missing API token"
            )

        try:
            # Decode and verify token
            payload = jwt.decode(token, DGEN_KEY, algorithms=["HS256"])
            
            # Extract claims
            soeid = payload.get("soeid")
            project_id = payload.get("project_id", "default")
            
            if not soeid:
                raise HTTPException(
                    status_code=HTTP_401_UNAUTHORIZED,
                    detail="Invalid token: missing soeid"
                )

            return TokenPayload(
                token_id=soeid,  # Use soeid as token_id for compatibility
                project_id=project_id,
                expires_at=None  # No expiration
            )

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Token expired"
            )
        except jwt.InvalidTokenError as e:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail=f"Token verification failed: {str(e)}"
            )

    @staticmethod
    async def verify_token_async(token: str = Security(api_key_header)) -> TokenPayload:
        """
        Async wrapper for token verification - for FastAPI dependency injection.
        Fallback to default token "1" if ALLOW_DEFAULT_TOKEN is enabled.
        """
        from config import settings
        
        # Handle missing token
        if not token:
            if settings.ALLOW_DEFAULT_TOKEN:
                # Use default token for development
                return TokenPayload(
                    token_id="default_user",
                    project_id="default",
                    expires_at=None
                )
            else:
                raise HTTPException(
                    status_code=HTTP_401_UNAUTHORIZED,
                    detail="Missing API token"
                )
        
        # Handle default token for development
        if token == "1" and settings.ALLOW_DEFAULT_TOKEN:
            return TokenPayload(
                token_id="default_user",
                project_id="default",
                expires_at=None
            )
        
        # Verify JWT token
        return AuthManager.verify_token(token)

# Authentication dependency for FastAPI routes
async def get_token_payload(token: str = Security(api_key_header)) -> TokenPayload:
    """Get token payload for protected routes."""
    return await AuthManager.verify_token_async(token)

# Alternative dependency that allows anonymous access
async def get_token_payload_optional(token: str = Security(api_key_header)) -> Optional[TokenPayload]:
    """Get token payload for routes that allow anonymous access."""
    try:
        return await AuthManager.verify_token_async(token)
    except HTTPException:
        return None
