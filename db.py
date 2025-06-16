"""Database operations for dgen-ping with CSV fallback, metrics, and schema creation."""
import logging
import csv
import os
import asyncio
import time
from datetime import datetime, timedelta

from pymongo import MongoClient, ASCENDING, IndexModel
from pymongo.errors import OperationFailure
from motor.motor_asyncio import AsyncIOMotorClient

from config import settings
from metrics import TelemetryWriter

logger = logging.getLogger("dgen-ping.db")

class Database:
    """MongoDB database connection with CSV fallback and schema management."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._client = None
            cls._instance._async_client = None
            cls._instance._use_csv_fallback = False
            cls._instance._csv_dir = settings.CSV_FALLBACK_DIR
            cls._instance._csv_lock = asyncio.Lock()
            cls._instance._metrics_last_update = datetime.now() - timedelta(hours=1)
            cls._instance._metrics_cache = {}
            cls._instance._connection_attempts = 0
            cls._instance._max_connection_attempts = 3
        return cls._instance

    async def initialize(self):
        """Initialize database connection with CSV fallback."""
        self._connection_attempts += 1
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

            # Initialize database schema and create collections/indexes
            await self._initialize_db_schema()
            self._use_csv_fallback = False

            # Log successful connection
            await self._log.to_connection_event("database_connected", "success", "MongoDB connection established")

        except Exception as e:
            error_msg = f"MongoDB connection failed: {e}"
            logger.warning(error_msg)

            # Try to reconnect if we haven't exceeded max attempts
            if self._connection_attempts < self._max_connection_attempts:
                logger.info(f"Retrying connection attempt ({self._connection_attempts}/{self._max_connection_attempts})...")
                await asyncio.sleep(2)
                await self.initialize()
                return

            # If all retries failed, USE CSV fallback
            self._use_csv_fallback = True
            self._setup_csv_fallback()

            # Log connection failure to CSV since we can't use MongoDB
            await self._log.to_csv(self._create_connection_event("database_connection_failed", "error", error_msg))

    def _setup_csv_fallback(self):
        """Set up CSV fallback directory."""
        if not os.path.exists(self._csv_dir):
            os.makedirs(self._csv_dir)
        logger.info(f"CSV fallback enabled: logs stored in {self._csv_dir}")

    async def _initialize_db_schema(self):
        """Initialize database schema and collections if they don't exist."""
        try:
            db = self._async_client[settings.DB_NAME]
            collection_names = await db.list_collection_names()

            # Define collection schemas
            required_collections = {
                "telemetry": settings.get_telemetry_schema_validator(),
                "metrics": {},  # No validator needed
                "connection_logs": {},  # No validator needed
                "ping_runs": settings.get_main_runs_schema_validator(),
                "projects": {}  # No validator needed
            }

            # Create missing collections
            for name, validator in required_collections.items():
                if name not in collection_names:
                    if validator:
                        await db.create_collection(name, validator=validator)
                    else:
                        await db.create_collection(name)
        except Exception as e:
            logger.error(f"Error initializing DB schema: {e}")
