"""Configuration for dgen-ping LLM proxy service with JWT support."""
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
    
    # Concurrency and performance settings
    MAX_CONCURRENCY: int = int(os.getenv("MAX_CONCURRENCY", "500"))
    RATE_LIMIT: int = int(os.getenv("RATE_LIMIT", "120"))
    WORKERS: int = int(os.getenv("WORKERS", "4"))
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "60"))
    RETRY_ATTEMPTS: int = int(os.getenv("RETRY_ATTEMPTS", "3"))
    
    # Proxy and service targets
    DOWNSTREAM_SERVICES: Dict[str, str] = json.loads(
        os.getenv("DOWNSTREAM_SERVICES", 
                 '{"llm":"http://llm-service:8000","classifier":"http://classifier-service:8000","enhancer":"http://enhancer-service:8000"}')
    )
    
    # JWT Authentication settings
    TOKEN_SECRET: str = os.getenv("TOKEN_SECRET", "dgen_secret_key_change_in_production")
    ALLOW_DEFAULT_TOKEN: bool = os.getenv("ALLOW_DEFAULT_TOKEN", "true").lower() == "true"
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    
    # Legacy settings (for backward compatibility)
    TOKEN_EXPIRY_DAYS: int = int(os.getenv("TOKEN_EXPIRY_DAYS", "90"))  # Not used with JWT
    
    # CSV fallback settings
    CSV_FALLBACK_DIR: str = os.getenv("CSV_FALLBACK_DIR", "telemetry_logs")
    
    # Default LLM settings
    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gpt-4")
    DEFAULT_MAX_TOKENS: int = int(os.getenv("DEFAULT_MAX_TOKENS", "2000"))
    DEFAULT_TEMPERATURE: float = float(os.getenv("DEFAULT_TEMPERATURE", "0.7"))
    
    # Database connection settings
    DB_CONNECTION_TIMEOUT: int = int(os.getenv("DB_CONNECTION_TIMEOUT", "5"))
    DB_MAX_RETRIES: int = int(os.getenv("DB_MAX_RETRIES", "3"))
    
    # Metrics and monitoring
    METRICS_CACHE_TTL: int = int(os.getenv("METRICS_CACHE_TTL", "300"))  # 5 minutes
    
    class Config:
        env_file = ".env"
        case_sensitive = True

    def validate_settings(self):
        """Validate critical settings."""
        if self.TOKEN_SECRET == "dgen_secret_key_change_in_production":
            if not self.DEBUG:
                raise ValueError("TOKEN_SECRET must be changed in production!")
        
        if self.MAX_CONCURRENCY < 1:
            raise ValueError("MAX_CONCURRENCY must be at least 1")
            
        if self.RATE_LIMIT < 1:
            raise ValueError("RATE_LIMIT must be at least 1")

settings = Settings()

# Validate settings on import
try:
    settings.validate_settings()
except ValueError as e:
    if not settings.DEBUG:
        raise e
    else:
        print(f"⚠️  Configuration warning: {e}")

# Helper function to get environment info
def get_environment_info() -> Dict[str, str]:
    """Get environment information for debugging."""
    return {
        "kubernetes": bool(os.environ.get("KUBERNETES_SERVICE_HOST")),
        "debug": settings.DEBUG,
        "allow_default_token": settings.ALLOW_DEFAULT_TOKEN,
        "csv_fallback_dir": settings.CSV_FALLBACK_DIR,
        "max_concurrency": settings.MAX_CONCURRENCY,
        "database_configured": bool(settings.MONGO_URI),
        "jwt_algorithm": settings.JWT_ALGORITHM
    }
