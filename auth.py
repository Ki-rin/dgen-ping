"""JWT authentication for dgen-ping."""
import os
import jwt
import uuid
import re
from datetime import datetime, timezone
from fastapi import HTTPException
from fastapi.security import APIKeyHeader

TOKEN_SECRET = os.getenv("TOKEN_SECRET", "dgen_secret_key_change_in_production")
ALLOW_DEFAULT_TOKEN = os.getenv("ALLOW_DEFAULT_TOKEN", "true").lower() == "true"

api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)

def generate_token(soeid: str) -> str:
    """Generate JWT token for SOEID."""
    if not soeid or not soeid.strip():
        raise HTTPException(status_code=400, detail="SOEID is required")
    
    soeid = soeid.strip()
    if not re.match(r'^[a-zA-Z0-9._-]+$', soeid):
        raise HTTPException(status_code=400, detail="Invalid SOEID format")
    
    payload = {
        "soeid": soeid,
        "project_id": soeid,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "jti": str(uuid.uuid4())
    }
    
    token = jwt.encode(payload, TOKEN_SECRET, algorithm="HS256")
    return token if isinstance(token, str) else token.decode('utf-8')

def verify_token(token: str) -> dict:
    """Verify JWT token and return payload."""
    if not token:
        if ALLOW_DEFAULT_TOKEN:
            return {"token_id": "default_user", "project_id": "default"}
        raise HTTPException(status_code=401, detail="Missing API token")
    
    token = token.strip()
    
    if token == "1" and ALLOW_DEFAULT_TOKEN:
        return {"token_id": "default_user", "project_id": "default"}
    
    try:
        payload = jwt.decode(token, TOKEN_SECRET, algorithms=["HS256"])
        soeid = payload.get("soeid")
        project_id = payload.get("project_id", soeid)
        
        if not soeid:
            raise HTTPException(status_code=401, detail="Invalid token: missing soeid")
        
        return {"token_id": soeid, "project_id": project_id}
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

async def get_token_payload(token: str = None) -> dict:
    """FastAPI dependency for token verification."""
    return verify_token(token)
