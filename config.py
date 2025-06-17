"""Configuration for dgen-ping."""
import os

class Settings:
    # Core settings
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    TOKEN_SECRET = os.getenv("TOKEN_SECRET", "dgen_secret_key")
    ALLOW_DEFAULT_TOKEN = os.getenv("ALLOW_DEFAULT_TOKEN", "true").lower() == "true"
    
    # Server settings
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8001"))
    
    # CORS settings
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
    
    # Rate limiting
    RATE_LIMIT = int(os.getenv("RATE_LIMIT", "100"))
    MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "50"))
    
    # Database - multiple URIs for resilience
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://admin_mongodb:cD4uwQCF@maas-gt-d284-u2045.nam.nsroot.net:37017/?authSource=admin&readPreference=primary&ssl=true&tlsAllowInvalidCertificates=true&tlsAllowInvalidHostnames=true")
    MONGO_URI_BACKUP = os.getenv("MONGO_URI_BACKUP", "")
    MONGO_URI_FALLBACK = os.getenv("MONGO_URI_FALLBACK", "")
    DB_NAME = os.getenv("DB_NAME", "dgen_db")
    
    # CSV fallback
    CSV_FALLBACK_DIR = os.getenv("CSV_FALLBACK_DIR", "telemetry_logs")
    
    # LLM settings
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini")
    DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", "10000"))
    DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.3"))
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

settings = Settings()
