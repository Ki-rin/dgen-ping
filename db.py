"""Database operations for dgen-ping with CSV fallback."""
import logging
import csv
import os
import json
import asyncio
from pymongo import MongoClient, ASCENDING
from pymongo.errors import ConnectionFailure, OperationFailure
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from config import settings
from models import TelemetryEvent

logger = logging.getLogger("dgen-ping.db")

class Database:
    """MongoDB database connection with CSV fallback."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._client = None
            cls._instance._async_client = None
            cls._instance._use_csv_fallback = False
            cls._instance._csv_dir = settings.CSV_FALLBACK_DIR
            cls._instance._csv_lock = asyncio.Lock()
        return cls._instance
    
    async def initialize(self):
        """Initialize database connection with CSV fallback."""
        try:
            # Connections for blocking and non-blocking operations
            self._client = MongoClient(
                settings.MONGO_URI,
                maxPoolSize=50,
                minPoolSize=5,
                serverSelectionTimeoutMS=5000,
                retryWrites=True
            )
            self._async_client = AsyncIOMotorClient(settings.MONGO_URI)
            
            # Test connection
            self._client.admin.command('ping')
            logger.info("Connected to MongoDB")
            
            # Create indexes
            await self._create_indexes()
            self._use_csv_fallback = False
            
        except Exception as e:
            logger.warning(f"MongoDB connection failed: {e}. Using CSV fallback.")
            self._use_csv_fallback = True
            self._setup_csv_fallback()
    
    def _setup_csv_fallback(self):
        """Set up CSV fallback directory."""
        if not os.path.exists(self._csv_dir):
            os.makedirs(self._csv_dir)
        logger.info(f"CSV fallback enabled: logs stored in {self._csv_dir}")
    
    async def _create_indexes(self):
        """Create necessary database indexes."""
        try:
            db = self._client[settings.DB_NAME]
            indexes = [
                ("metadata.client_id", ASCENDING),
                ("metadata.target_service", ASCENDING),
                ("timestamp", ASCENDING),
                ("event_type", ASCENDING)
            ]
            for field, direction in indexes:
                db.telemetry.create_index([(field, direction)], background=True)
        except Exception as e:
            logger.warning(f"Failed to create indexes: {e}")
    
    async def log_telemetry(self, event: TelemetryEvent):
        """Log telemetry to database or CSV fallback."""
        if self._use_csv_fallback:
            await self._log_to_csv(event)
        else:
            try:
                await self._async_client[settings.DB_NAME].telemetry.insert_one(event.model_dump())
            except Exception as e:
                logger.warning(f"MongoDB logging failed: {e}. Using CSV fallback.")
                self._use_csv_fallback = True
                self._setup_csv_fallback()
                await self._log_to_csv(event)
    
    async def _log_to_csv(self, event: TelemetryEvent):
        """Log telemetry event to CSV file."""
        today = datetime.now().strftime("%Y-%m-%d")
        filename = f"{self._csv_dir}/telemetry_{today}.csv"
        
        # Flatten the event data
        flat_data = {
            "timestamp": event.timestamp.isoformat(),
            "event_type": event.event_type,
            "client_ip": event.client_ip,
            "client_id": event.metadata.client_id,
            "target_service": event.metadata.target_service,
            "endpoint": event.metadata.endpoint,
            "method": event.metadata.method,
            "status_code": event.metadata.status_code,
            "latency_ms": event.metadata.latency_ms,
            "llm_model": event.metadata.llm_model,
            "llm_latency": event.metadata.llm_latency,
            "additional_data": json.dumps(event.metadata.additional_data) if event.metadata.additional_data else None
        }
        
        # Use lock to prevent concurrent writes
        async with self._csv_lock:
            file_exists = os.path.isfile(filename)
            with open(filename, 'a', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=flat_data.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(flat_data)
    
    @property
    def client(self):
        """Get MongoDB client."""
        return self._client
    
    @property
    def async_client(self):
        """Get async MongoDB client."""
        return self._async_client
    
    @property
    def is_connected(self):
        """Check if connected to MongoDB."""
        return not self._use_csv_fallback and self._client is not None

# Singleton instance
db = Database()