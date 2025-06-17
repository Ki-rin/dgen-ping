"""JWT authentication for dgen-ping."""
import os
import jwt
import uuid
import re
from datetime import datetime, timezone
from fastapi import HTTPException, Depends
from fastapi.security import APIKeyHeader
from models import TokenPayload

TOKEN_SECRET = os.getenv("TOKEN_SECRET", "dgen_secret_key")
ALLOW_DEFAULT_TOKEN = os.getenv("ALLOW_DEFAULT_TOKEN", "true").lower() == "true"
DGEN_KEY = TOKEN_SECRET  # Used for token generation endpoint security

api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)

class AuthManager:
    @staticmethod
    def generate_token(soeid: str, project_id: str = None) -> str:
        """Generate JWT token for SOEID with default template."""
        if not soeid or not soeid.strip():
            raise HTTPException(status_code=400, detail="SOEID is required")
        
        soeid = soeid.strip()
        if not re.match(r'^[a-zA-Z0-9._-]+$', soeid):
            raise HTTPException(status_code=400, detail="Invalid SOEID format")
        
        # Default template: use soeid for both token_id and project_id
        actual_project_id = project_id if project_id else soeid
        
        payload = {
            "soeid": soeid,
            "project_id": actual_project_id,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "jti": str(uuid.uuid4())
        }
        
        token = jwt.encode(payload, TOKEN_SECRET, algorithm="HS256")
        return token if isinstance(token, str) else token.decode('utf-8')

    @staticmethod
    def verify_token(token: str) -> TokenPayload:
        """Verify JWT token and return payload with default template."""
        if not token:
            if ALLOW_DEFAULT_TOKEN:
                # Default template for missing token
                return TokenPayload(token_id="default_user", project_id="default_user")
            raise HTTPException(status_code=401, detail="Missing API token")
        
        token = token.strip()
        
        if token == "1" and ALLOW_DEFAULT_TOKEN:
            # Default template for token "1"
            return TokenPayload(token_id="default_user", project_id="default_user")
        
        try:
            payload = jwt.decode(token, TOKEN_SECRET, algorithms=["HS256"])
            soeid = payload.get("soeid")
            project_id = payload.get("project_id", soeid)  # Default template: fallback to soeid
            
            if not soeid:
                raise HTTPException(status_code=401, detail="Invalid token: missing soeid")
            
            return TokenPayload(token_id=soeid, project_id=project_id)
        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

# Legacy functions for compatibility
def generate_token(soeid: str) -> str:
    """Generate JWT token for SOEID."""
    return AuthManager.generate_token(soeid)

def verify_token(token: str) -> dict:
    """Verify JWT token and return payload as dict."""
    payload = AuthManager.verify_token(token)
    return {"token_id": payload.token_id, "project_id": payload.project_id}

async def get_token_payload(token: str = Depends(api_key_header)) -> TokenPayload:
    """FastAPI dependency for token verification."""
    return AuthManager.verify_token(token)
