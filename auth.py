"""Authentication and authorization for dgen-ping."""
import uuid
import time
from datetime import datetime, timedelta
from fastapi import HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_503_SERVICE_UNAVAILABLE
from db import db
from config import settings
from models import TokenPayload

# Default token values
DEFAULT_TOKEN = "1"
DEFAULT_PROJECT = "default-project"

# API key header security scheme
api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)

class AuthManager:
    """Authentication and authorization manager."""
    
    @staticmethod
    async def verify_token(token: str = Security(api_key_header)) -> TokenPayload:
        """Verify API token and return payload if valid."""
        # Handle missing token or default token
        if not token or (token == DEFAULT_TOKEN and settings.ALLOW_DEFAULT_TOKEN):
            if settings.ALLOW_DEFAULT_TOKEN:
                return TokenPayload(token_id=DEFAULT_TOKEN, project_id=DEFAULT_PROJECT)
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Missing API token")
            
        # If DB is not available and default token allowed
        if not db.is_connected and settings.ALLOW_DEFAULT_TOKEN:
            return TokenPayload(token_id=DEFAULT_TOKEN, project_id=DEFAULT_PROJECT)
            
        try:
            # Get token from database
            token_doc = await db.async_client[settings.DB_NAME].api_tokens.find_one({
                "token": token, "is_active": True
            })
            
            if not token_doc:
                raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid token")
                
            # Check token expiration
            if token_doc.get("expires_at"):
                expiry = datetime.fromisoformat(token_doc["expires_at"])
                if datetime.now() > expiry:
                    await db.async_client[settings.DB_NAME].api_tokens.update_one(
                        {"token": token}, {"$set": {"is_active": False}}
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
            
            # Get project info
            project = await db.async_client[settings.DB_NAME].projects.find_one(
                {"project_id": token_doc["project_id"]}
            )
            
            if not project:
                raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Project not found")
                
            return TokenPayload(
                token_id=token,
                project_id=project["project_id"],
                expires_at=datetime.fromisoformat(token_doc["expires_at"]) if token_doc.get("expires_at") else None
            )
            
        except HTTPException:
            raise
        except Exception as e:
            if settings.ALLOW_DEFAULT_TOKEN:
                return TokenPayload(token_id=DEFAULT_TOKEN, project_id=DEFAULT_PROJECT)
            else:
                raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail=f"Auth error: {str(e)}")
    
    @staticmethod
    async def create_token(project_id: str, created_by: str, description: str = None) -> str:
        """Create a new API token."""
        token = f"tk_{project_id}_{int(time.time())}_{uuid.uuid4().hex[:16]}"
        expires_at = (datetime.now() + timedelta(days=settings.TOKEN_EXPIRY_DAYS)).isoformat()
        
        if db.is_connected:
            await db.async_client[settings.DB_NAME].api_tokens.insert_one({
                "token": token,
                "project_id": project_id,
                "description": description,
                "created_by": created_by,
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