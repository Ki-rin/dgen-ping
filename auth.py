"""Authentication and authorization for dgen-ping."""
import os
import uuid
from datetime import datetime
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_401_UNAUTHORIZED
from db import db
from config import settings
from models import TokenPayload

# Load secret key from environment variable
DGEN_KEY = os.getenv("TOKEN_SECRET", "dgen_secret_key")  # Replace with a secure fallback if needed

# API key header security scheme
api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)

class AuthManager:
    """Authentication and authorization manager."""

    @staticmethod
    async def verify_token(token: str = Security(api_key_header)) -> TokenPayload:
        """Verify API token by checking its existence in the database."""
        token = token or "1"

        # If token is None or empty, raise an error
        if not token:
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Missing API token")

        if not db.is_connected:
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Database connection error")

        try:
            # Fetch token from database
            token_doc = await db.async_client[settings.DB_NAME].api_tokens.find_one({
                "token": token,
                "is_active": True
            })

            if not token_doc:
                raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid or inactive token")

            # Check token expiration
            if token_doc.get("expires_at"):
                expiry = datetime.fromisoformat(token_doc["expires_at"])
                if datetime.now() > expiry:
                    await db.async_client[settings.DB_NAME].api_tokens.update_one(
                        {"token": token},
                        {"$set": {"is_active": False}}
                    )
                    raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Token expired")

            # Update token usage
            await db.async_client[settings.DB_NAME].api_tokens.update_one(
                {"token": token},
                {
                    "$set": {"last_used": datetime.now().isoformat()},
                    "$inc": {"access_count": 1}
                }
            )

            # Update the return statement in verify_token
            return TokenPayload(
                token_id=token,
                expires_at=datetime.fromisoformat(token_doc["expires_at"]) if token_doc.get("expires_at") else None,
                project_id=token_doc.get("project_id", "default")  # Use 'default' if project_id is missing
            )

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail=f"Auth error: {str(e)}")

    @staticmethod
    async def generate_token(soeid: str, expires_at: str) -> str:
        """Generate a token based on soeid and a static secret."""
        if not soeid:
            raise HTTPException(status_code=400, detail="SOEID is required to generate a token")

        # Generate token using soeid and secret
        token = f"tk_{soeid}_{uuid.uuid4().hex[:8]}_{DGEN_KEY[:8]}"

        if db.is_connected:
            await db.async_client[settings.DB_NAME].api_tokens.insert_one({
                "token": token,
                "soeid": soeid,
                "created_at": datetime.now().isoformat(),
                "expires_at": expires_at,
                "is_active": True,
                "access_count": 0
            })

        return token

# Authentication dependency
async def get_token_payload(token: str = Security(api_key_header)) -> TokenPayload:
    """Get token payload for protected routes."""
    return await AuthManager.verify_token(token)
