"""Authentication and authorization for dgen-ping with JWT-based tokens."""
import os
import jwt
import uuid
import re
import urllib.parse
from datetime import datetime, timezone
from fastapi import HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_401_UNAUTHORIZED
from typing import Optional
from models import TokenPayload

# Load secret key from environment variable
DGEN_KEY = os.getenv("TOKEN_SECRET", "dgen_secret_key_change_in_production")

# API key header security scheme
api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)

class AuthManager:
    """JWT-based authentication and authorization manager."""

    @staticmethod
    def generate_token(soeid: str, project_id: str = None) -> str:
        """
        Generate a JWT token based on soeid and project_id.
        No expiration - tokens are permanent until secret changes.
        
        Args:
            soeid: User's SOEID (required)
            project_id: Project identifier (optional, defaults to soeid)
        
        Returns:
            JWT token as string
        """
        if not soeid:
            raise HTTPException(status_code=400, detail="SOEID is required to generate a token")

        # Clean and validate soeid
        soeid = str(soeid).strip()
        if not re.match(r'^[a-zA-Z0-9._-]+$', soeid):
            raise HTTPException(
                status_code=400, 
                detail="SOEID contains invalid characters. Use only letters, numbers, dots, hyphens, and underscores."
            )

        # Use soeid as project_id if not provided
        if not project_id:
            project_id = soeid
        else:
            project_id = str(project_id).strip()

        payload = {
            "soeid": soeid,
            "project_id": project_id,
            "iat": int(datetime.now(timezone.utc).timestamp()),  # Issued at as integer
            "jti": str(uuid.uuid4())  # JWT ID for uniqueness
        }

        try:
            # Generate token with explicit encoding
            token = jwt.encode(payload, DGEN_KEY, algorithm="HS256")
            
            # Ensure token is returned as string (PyJWT 2.x compatibility)
            if isinstance(token, bytes):
                token = token.decode('utf-8')
                
            return token
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Token generation failed: {str(e)}")

    @staticmethod
    def verify_token(token: str) -> TokenPayload:
        """
        Verify JWT token using shared secret - no database lookup required.
        
        Args:
            token: JWT token string
            
        Returns:
            TokenPayload with user information
        """
        if not token:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED, 
                detail="Missing API token"
            )

        try:
            # Clean and validate token format
            token = token.strip()
            
            # Handle potential encoding issues
            if isinstance(token, bytes):
                try:
                    token = token.decode('utf-8')
                except UnicodeDecodeError:
                    raise HTTPException(
                        status_code=HTTP_401_UNAUTHORIZED,
                        detail="Invalid token encoding"
                    )
            
            # Ensure token contains only valid characters for JWT
            if not re.match(r'^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$', token):
                raise HTTPException(
                    status_code=HTTP_401_UNAUTHORIZED,
                    detail="Invalid token format"
                )

            # Decode and verify token
            payload = jwt.decode(token, DGEN_KEY, algorithms=["HS256"])
            
            # Extract claims
            soeid = payload.get("soeid")
            project_id = payload.get("project_id")
            
            if not soeid:
                raise HTTPException(
                    status_code=HTTP_401_UNAUTHORIZED,
                    detail="Invalid token: missing soeid"
                )

            # If no project_id in token, use soeid as project_id for backward compatibility
            if not project_id:
                project_id = soeid

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
        except HTTPException:
            # Re-raise HTTP exceptions as-is
            raise
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
        
        Args:
            token: Token from API header
            
        Returns:
            TokenPayload with user information
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
        
        # Clean token input
        token = str(token).strip()
        
        # Handle default token for development
        if token == "1" and settings.ALLOW_DEFAULT_TOKEN:
            return TokenPayload(
                token_id="default_user",
                project_id="default",
                expires_at=None
            )
        
        # Handle potential URL encoding issues
        try:
            # Try to decode if it looks URL encoded
            if '%' in token:
                decoded_token = urllib.parse.unquote(token)
                if decoded_token != token:
                    token = decoded_token
        except Exception:
            pass  # Continue with original token if URL decoding fails
        
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
