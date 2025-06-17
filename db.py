"""Database operations for dgen-ping with comprehensive error handling and CSV fallback."""
import logging
import csv
import os
import asyncio
import time
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from pymongo import MongoClient, ASCENDING, IndexModel
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError, NetworkTimeout
from motor.motor_asyncio import AsyncIOMotorClient

from config import settings

logger = logging.getLogger("dgen-ping.db")

class Database:
    """MongoDB database connection with comprehensive error handling and CSV fallback."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._client = None
            cls._instance._async_client = None
            cls._instance._use_csv_fallback = False
            cls._instance._csv_dir = settings.CSV_FALLBACK_DIR
            cls._instance._csv_lock = asyncio.Lock()
            cls._instance._metrics_cache = {}
            cls._instance._metrics_last_update = datetime.now() - timedelta(hours=1)
            cls._instance._connection_attempts = 0
            cls._instance._max_connection_attempts = 3
            cls._instance._is_connected = False
        return cls._instance

    @property
    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._is_connected and not self._use_csv_fallback

    @property
    def client(self):
        """Get synchronous MongoDB client."""
        return self._client

    @property
    def async_client(self):
        """Get asynchronous MongoDB client."""
        return self._async_client

    async def initialize(self):
        """Initialize database connection with comprehensive error handling."""
        self._connection_attempts += 1
        
        try:
            # Create connections with shorter timeouts for faster fallback
            self._client = MongoClient(
                settings.MONGO_URI,
                maxPoolSize=50,
                minPoolSize=5,
                serverSelectionTimeoutMS=3000,  # Reduced timeout
                connectTimeoutMS=3000,
                socketTimeoutMS=3000,
                retryWrites=True
            )
            self._async_client = AsyncIOMotorClient(
                settings.MONGO_URI,
                maxPoolSize=50,
                minPoolSize=5,
                serverSelectionTimeoutMS=3000,
                connectTimeoutMS=3000,
                socketTimeoutMS=3000
            )

            # Test connection with timeout
            await asyncio.wait_for(
                self._test_connection(), 
                timeout=5.0
            )
            
            self._is_connected = True
            self._use_csv_fallback = False
            logger.info("Successfully connected to MongoDB")

            # Initialize database schema
            await self._initialize_db_schema()

            # Log successful connection to database
            await self._log_connection_event_safe(
                "database_connected", 
                "success", 
                "MongoDB connection established"
            )

        except (ServerSelectionTimeoutError, NetworkTimeout, asyncio.TimeoutError) as e:
            await self._handle_connection_failure(f"Database connection timeout: {e}")
        except Exception as e:
            await self._handle_connection_failure(f"Database connection failed: {e}")

    async def _test_connection(self):
        """Test database connection."""
        await self._async_client.admin.command('ping')

    async def _handle_connection_failure(self, error_msg: str):
        """Handle database connection failures with retry logic."""
        logger.warning(error_msg)

        # Try to reconnect if we haven't exceeded max attempts
        if self._connection_attempts < self._max_connection_attempts:
            logger.info(f"Retrying connection (attempt {self._connection_attempts}/{self._max_connection_attempts})...")
            await asyncio.sleep(2)
            await self.initialize()
            return

        # All retries failed - switch to CSV fallback
        logger.error(f"All database connection attempts failed. Switching to CSV fallback mode.")
        self._is_connected = False
        self._use_csv_fallback = True
        self._setup_csv_fallback()

        # Log connection failure to CSV
        await self._log_to_csv("connection_logs", {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": "database_connection_failed",
            "status": "error",
            "message": error_msg,
            "attempt": self._connection_attempts
        })

    def _setup_csv_fallback(self):
        """Set up CSV fallback directory and files."""
        try:
            if not os.path.exists(self._csv_dir):
                os.makedirs(self._csv_dir)
            logger.info(f"CSV fallback enabled: logs stored in {self._csv_dir}")
        except Exception as e:
            logger.error(f"Failed to create CSV fallback directory: {e}")

    async def _initialize_db_schema(self):
        """Initialize database schema and collections safely."""
        if not self.is_connected:
            return

        try:
            db = self._async_client[settings.DB_NAME]
            collection_names = await db.list_collection_names()

            # Define required collections
            required_collections = [
                "telemetry",
                "connection_logs", 
                "llm_runs",
                "metrics"
            ]

            # Create missing collections
            for collection_name in required_collections:
                if collection_name not in collection_names:
                    await db.create_collection(collection_name)
                    logger.info(f"Created collection: {collection_name}")

            # Create indexes for better performance
            await self._create_indexes()

        except Exception as e:
            logger.error(f"Error initializing database schema: {e}")

    async def _create_indexes(self):
        """Create database indexes for better performance."""
        if not self.is_connected:
            return

        try:
            db = self._async_client[settings.DB_NAME]
            
            # Telemetry indexes
            await db.telemetry.create_index([("timestamp", -1)])
            await db.telemetry.create_index([("metadata.client_id", 1)])
            await db.telemetry.create_index([("event_type", 1)])
            
            # Connection logs indexes
            await db.connection_logs.create_index([("timestamp", -1)])
            
            # LLM runs indexes
            await db.llm_runs.create_index([("timestamp", -1)])
            await db.llm_runs.create_index([("metadata.soeid", 1)])
            
            logger.info("Database indexes created successfully")
        except Exception as e:
            logger.error(f"Error creating database indexes: {e}")

    async def log_telemetry(self, event) -> bool:
        """Log telemetry event with fallback handling."""
        try:
            if self.is_connected:
                return await self._log_to_mongodb("telemetry", event.dict())
            else:
                return await self._log_to_csv("telemetry", event.dict())
        except Exception as e:
            logger.error(f"Failed to log telemetry: {e}")
            return False

    async def log_connection_event(self, event_type: str, status: str, message: str, metadata: Dict = None) -> bool:
        """Log connection event with fallback handling."""
        return await self._log_connection_event_safe(event_type, status, message, metadata)

    async def _log_connection_event_safe(self, event_type: str, status: str, message: str, metadata: Dict = None) -> bool:
        """Safely log connection event with comprehensive error handling."""
        event_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "status": status,
            "message": message,
            "metadata": metadata or {}
        }

        try:
            if self.is_connected:
                return await self._log_to_mongodb("connection_logs", event_data)
            else:
                return await self._log_to_csv("connection_logs", event_data)
        except Exception as e:
            logger.error(f"Failed to log connection event: {e}")
            # Last resort - try to write to local file
            try:
                with open("emergency_log.txt", "a") as f:
                    f.write(f"{datetime.utcnow().isoformat()} - {event_type}: {message}\n")
                return True
            except:
                return False

    async def _log_to_mongodb(self, collection_name: str, data: Dict) -> bool:
        """Log data to MongoDB collection."""
        try:
            collection = self._async_client[settings.DB_NAME][collection_name]
            await collection.insert_one(data)
            return True
        except Exception as e:
            logger.error(f"MongoDB logging failed for {collection_name}: {e}")
            # Fallback to CSV on MongoDB error
            return await self._log_to_csv(collection_name, data)

    async def _log_to_csv(self, collection_name: str, data: Dict) -> bool:
        """Log data to CSV file with proper error handling."""
        if not self._csv_dir:
            return False

        async with self._csv_lock:
            try:
                csv_file = os.path.join(self._csv_dir, f"{collection_name}.csv")
                file_exists = os.path.exists(csv_file)
                
                # Flatten nested data for CSV
                flattened_data = self._flatten_dict(data)
                
                with open(csv_file, 'a', newline='', encoding='utf-8') as f:
                    if flattened_data:
                        writer = csv.DictWriter(f, fieldnames=flattened_data.keys())
                        if not file_exists:
                            writer.writeheader()
                        writer.writerow(flattened_data)
                
                return True
            except Exception as e:
                logger.error(f"CSV logging failed for {collection_name}: {e}")
                return False

    def _flatten_dict(self, data: Dict, parent_key: str = '', sep: str = '.') -> Dict:
        """Flatten nested dictionary for CSV storage."""
        items = []
        for k, v in data.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list):
                # Convert lists to JSON strings
                items.append((new_key, json.dumps(v)))
            else:
                items.append((new_key, v))
        return dict(items)

    async def get_metrics(self) -> Dict[str, Any]:
        """Get system metrics with caching and error handling."""
        # Check cache freshness
        now = datetime.now()
        if (now - self._metrics_last_update).total_seconds() < 300:  # 5 minutes cache
            return self._metrics_cache

        try:
            if self.is_connected:
                metrics = await self._get_metrics_from_mongodb()
            else:
                metrics = await self._get_metrics_from_csv()
            
            self._metrics_cache = metrics
            self._metrics_last_update = now
            return metrics
        except Exception as e:
            logger.error(f"Error getting metrics: {e}")
            return self._get_default_metrics()

    async def _get_metrics_from_mongodb(self) -> Dict[str, Any]:
        """Get metrics from MongoDB."""
        try:
            db = self._async_client[settings.DB_NAME]
            
            # Get basic counts
            telemetry_count = await db.telemetry.count_documents({})
            llm_runs_count = await db.telemetry.count_documents({"event_type": "llm_run"})
            
            # Get recent activity (last hour)
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            recent_count = await db.telemetry.count_documents({
                "timestamp": {"$gte": one_hour_ago.isoformat()}
            })
            
            return {
                "requests_total": telemetry_count,
                "requests_last_hour": recent_count,
                "llm_runs_total": llm_runs_count,
                "avg_latency_ms": 0,  # Would need aggregation pipeline
                "error_rate": 0,      # Would need aggregation pipeline
                "token_usage_total": 0, # Would need aggregation pipeline
                "database_status": "connected"
            }
        except Exception as e:
            logger.error(f"Error getting MongoDB metrics: {e}")
            return self._get_default_metrics()

    async def _get_metrics_from_csv(self) -> Dict[str, Any]:
        """Get basic metrics from CSV files."""
        try:
            telemetry_file = os.path.join(self._csv_dir, "telemetry.csv")
            line_count = 0
            
            if os.path.exists(telemetry_file):
                with open(telemetry_file, 'r') as f:
                    line_count = sum(1 for line in f) - 1  # Subtract header
            
            return {
                "requests_total": max(0, line_count),
                "requests_last_hour": 0,  # Would need timestamp parsing
                "llm_runs_total": 0,      # Would need event type filtering
                "avg_latency_ms": 0,
                "error_rate": 0,
                "token_usage_total": 0,
                "database_status": "csv_fallback"
            }
        except Exception as e:
            logger.error(f"Error getting CSV metrics: {e}")
            return self._get_default_metrics()

    def _get_default_metrics(self) -> Dict[str, Any]:
        """Get default metrics when all else fails."""
        return {
            "requests_total": 0,
            "requests_last_hour": 0,
            "llm_runs_total": 0,
            "avg_latency_ms": 0,
            "error_rate": 0,
            "token_usage_total": 0,
            "database_status": "error"
        }

    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check."""
        health = {
            "database_connected": self.is_connected,
            "csv_fallback_active": self._use_csv_fallback,
            "connection_attempts": self._connection_attempts
        }

        if self.is_connected:
            try:
                # Test database responsiveness
                start_time = time.time()
                await self._async_client.admin.command('ping')
                health["db_response_time_ms"] = (time.time() - start_time) * 1000
                health["status"] = "healthy"
            except Exception as e:
                health["status"] = "degraded"
                health["error"] = str(e)
        else:
            health["status"] = "fallback_mode"
            if os.path.exists(self._csv_dir):
                health["csv_directory_writable"] = os.access(self._csv_dir, os.W_OK)

        return health

# Global database instance
db = Database()
