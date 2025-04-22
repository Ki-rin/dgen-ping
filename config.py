"""Configuration for dgen-ping service."""
import os
import json
from pydantic_settings import BaseSettings
from typing import Dict, List

class Settings(BaseSettings):
    # MongoDB connection
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://admin_mongodb:cD4uwQCF@maas-gt-d284-u2045.nam.nsroot.net:37017/?authSource=admin&readPreference=primary&ssl=true&tlsAllowInvalidCertificates=true&tlsAllowInvalidHostnames=true")
    DB_NAME: str = os.getenv("DB_NAME", "dgen_db")
    
    # Application settings
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8001"))
    ALLOWED_ORIGINS: List[str] = ["*"]
    
    # Proxy and service targets
    DOWNSTREAM_SERVICES: Dict[str, str] = json.loads(
        os.getenv("DOWNSTREAM_SERVICES", 
                 '{"classifier":"http://classifier-service:8000","enhancer":"http://enhancer-service:8000"}')
    )
    
    # Security settings
    TOKEN_EXPIRY_DAYS: int = int(os.getenv("TOKEN_EXPIRY_DAYS", "90"))
    ALLOW_DEFAULT_TOKEN: bool = os.getenv("ALLOW_DEFAULT_TOKEN", "true").lower() == "true"
    
    # CSV fallback settings
    CSV_FALLBACK_DIR: str = os.getenv("CSV_FALLBACK_DIR", "telemetry_logs")
    
    class Config:
        env_file = ".env"

settings = Settings()