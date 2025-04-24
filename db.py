# Singleton instance
"""Database operations for dgen-ping with CSV fallback, metrics, and schema creation."""
import logging
import csv
import os
import json
import asyncio
import time
from pymongo import MongoClient, ASCENDING, IndexModel
from pymongo.errors import ConnectionFailure, OperationFailure
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from config import settings
from models import TelemetryEvent

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
            cls._instance._metrics_cache = {}
            cls._instance._metrics_last_update = datetime.now() - timedelta(hours=1)
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
            await self.log_connection_event("database_connected", "success", "MongoDB connection established")
            
        except Exception as e:
            error_msg = f"MongoDB connection failed: {e}"
            logger.warning(error_msg)
            
            # Try to reconnect if we haven't exceeded max attempts
            if self._connection_attempts < self._max_connection_attempts:
                logger.info(f"Retrying connection (attempt {self._connection_attempts}/{self._max_connection_attempts})...")
                await asyncio.sleep(2)  # Wait before retry
                await self.initialize()
                return
            
            # If all retries failed, use CSV fallback
            self._use_csv_fallback = True
            self._setup_csv_fallback()
            
            # Log connection failure to CSV since we can't use MongoDB
            await self._log_to_csv(self._create_connection_event("database_connection_failed", "error", error_msg))
    
    def _setup_csv_fallback(self):
        """Set up CSV fallback directory."""
        if not os.path.exists(self._csv_dir):
            os.makedirs(self._csv_dir)
        logger.info(f"CSV fallback enabled: logs stored in {self._csv_dir}")
    
    async def _initialize_db_schema(self):
        """Initialize database schema and collections if they don't exist."""
        try:
            db = self._async_client[settings.DB_NAME]
            
            # Check if collections exist, create them if not
            collection_names = await db.list_collection_names()
            
            # Define collections to ensure exist
            required_collections = {
                "telemetry": self._get_telemetry_schema_validator(),
                "metrics": {},  # No validator needed
                "connection_logs": {},  # No validator needed
                "llm_runs": self._get_llm_runs_schema_validator(),
                "api_tokens": {},  # No validator needed
                "projects": {}  # No validator needed
            }
            
            # Create collections that don't exist
            for collection_name, validator in required_collections.items():
                if collection_name not in collection_names:
                    logger.info(f"Creating {collection_name} collection")
                    if validator:
                        await db.create_collection(collection_name, validator=validator)
                    else:
                        await db.create_collection(collection_name)
            
            # Create indexes for all collections
            await self._create_indexes()
            
            logger.info("Database schema initialized successfully")
            
        except OperationFailure as e:
            if "already exists" in str(e):
                logger.info("Collections already exist, skipping creation")
                # Just create indexes
                await self._create_indexes()
            else:
                logger.error(f"Error creating database schema: {e}")
                raise
    
    def _get_telemetry_schema_validator(self):
        """Return JSON Schema validator for telemetry collection."""
        return {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["event_type", "timestamp", "metadata"],
                "properties": {
                    "event_type": {
                        "bsonType": "string",
                        "description": "Type of event (e.g., llm_request)"
                    },
                    "timestamp": {
                        "bsonType": "date",
                        "description": "Timestamp of the event"
                    },
                    "request_id": {
                        "bsonType": "string",
                        "description": "Unique request identifier"
                    },
                    "client_ip": {
                        "bsonType": "string",
                        "description": "Client IP address"
                    },
                    "metadata": {
                        "bsonType": "object",
                        "required": ["client_id", "target_service", "endpoint", "method", "status_code", "latency_ms"],
                        "properties": {
                            "client_id": {
                                "bsonType": "string",
                                "description": "Client identifier"
                            },
                            "soeid": {
                                "bsonType": ["string", "null"],
                                "description": "User SOEID"
                            },
                            "project_name": {
                                "bsonType": ["string", "null"],
                                "description": "Project name"
                            },
                            "target_service": {
                                "bsonType": "string",
                                "description": "Target service"
                            },
                            "endpoint": {
                                "bsonType": "string",
                                "description": "API endpoint"
                            },
                            "method": {
                                "bsonType": "string",
                                "description": "HTTP method"
                            },
                            "status_code": {
                                "bsonType": "int",
                                "description": "HTTP status code"
                            },
                            "latency_ms": {
                                "bsonType": "double",
                                "description": "Request latency in milliseconds"
                            },
                            "request_size": {
                                "bsonType": ["int", "null"],
                                "description": "Request size in bytes"
                            },
                            "response_size": {
                                "bsonType": ["int", "null"],
                                "description": "Response size in bytes"
                            },
                            "prompt_tokens": {
                                "bsonType": ["int", "null"],
                                "description": "Number of prompt tokens"
                            },
                            "completion_tokens": {
                                "bsonType": ["int", "null"],
                                "description": "Number of completion tokens"
                            },
                            "total_tokens": {
                                "bsonType": ["int", "null"],
                                "description": "Total number of tokens"
                            },
                            "llm_model": {
                                "bsonType": ["string", "null"],
                                "description": "LLM model name"
                            },
                            "llm_latency": {
                                "bsonType": ["double", "null"],
                                "description": "LLM processing latency"
                            }
                        }
                    }
                }
            }
        }
    
    def _get_llm_runs_schema_validator(self):
        """Return JSON Schema validator for llm_runs collection."""
        return {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["request_id", "timestamp", "prompt", "completion"],
                "properties": {
                    "request_id": {
                        "bsonType": "string",
                        "description": "Unique request identifier"
                    },
                    "timestamp": {
                        "bsonType": "date",
                        "description": "Timestamp of the run"
                    },
                    "soeid": {
                        "bsonType": ["string", "null"],
                        "description": "User SOEID"
                    },
                    "project_name": {
                        "bsonType": ["string", "null"],
                        "description": "Project name"
                    },
                    "prompt": {
                        "bsonType": "string",
                        "description": "LLM prompt"
                    },
                    "completion": {
                        "bsonType": "string",
                        "description": "LLM completion"
                    },
                    "model": {
                        "bsonType": "string",
                        "description": "LLM model used"
                    },
                    "temperature": {
                        "bsonType": "double",
                        "description": "Temperature setting"
                    },
                    "max_tokens": {
                        "bsonType": "int",
                        "description": "Max tokens setting"
                    },
                    "prompt_tokens": {
                        "bsonType": "int",
                        "description": "Number of prompt tokens"
                    },
                    "completion_tokens": {
                        "bsonType": "int",
                        "description": "Number of completion tokens"
                    },
                    "total_tokens": {
                        "bsonType": "int",
                        "description": "Total number of tokens"
                    },
                    "latency_ms": {
                        "bsonType": "double",
                        "description": "Processing latency"
                    }
                }
            }
        }
    
    async def _create_indexes(self):
        """Create necessary database indexes."""
        try:
            db = self._async_client[settings.DB_NAME]
            
            # Define indexes for telemetry collection
            telemetry_indexes = [
                IndexModel([("metadata.client_id", ASCENDING)], background=True),
                IndexModel([("metadata.soeid", ASCENDING)], background=True),
                IndexModel([("metadata.target_service", ASCENDING)], background=True),
                IndexModel([("timestamp", ASCENDING)], background=True),
                IndexModel([("event_type", ASCENDING)], background=True),
                IndexModel([("request_id", ASCENDING)], background=True),
                
                # Compound indexes for common queries
                IndexModel([
                    ("event_type", ASCENDING),
                    ("timestamp", ASCENDING),
                    ("metadata.status_code", ASCENDING)
                ], background=True),
                
                # Indexes for token counting
                IndexModel([
                    ("metadata.soeid", ASCENDING),
                    ("metadata.total_tokens", ASCENDING)
                ], background=True),
                
                # Index for latency analysis
                IndexModel([
                    ("metadata.latency_ms", ASCENDING),
                    ("timestamp", ASCENDING)
                ], background=True),
                
                # Index for error tracking
                IndexModel([
                    ("metadata.status_code", ASCENDING),
                    ("timestamp", ASCENDING)
                ], background=True)
            ]
            
            # Create telemetry indexes
            await db.telemetry.create_indexes(telemetry_indexes)
            
            # Create indexes for metrics collection
            metrics_indexes = [
                IndexModel([("timestamp", ASCENDING)], background=True),
                IndexModel([("metric_type", ASCENDING)], background=True),
                IndexModel([
                    ("metric_type", ASCENDING),
                    ("timestamp", ASCENDING)
                ], background=True)
            ]
            await db.metrics.create_indexes(metrics_indexes)
            
            # Create indexes for llm_runs collection
            llm_runs_indexes = [
                IndexModel([("request_id", ASCENDING)], background=True, unique=True),
                IndexModel([("timestamp", ASCENDING)], background=True),
                IndexModel([("soeid", ASCENDING)], background=True),
                IndexModel([("project_name", ASCENDING)], background=True),
                IndexModel([("model", ASCENDING)], background=True),
                IndexModel([
                    ("soeid", ASCENDING),
                    ("timestamp", ASCENDING)
                ], background=True)
            ]
            await db.llm_runs.create_indexes(llm_runs_indexes)
            
            # Create indexes for connection_logs collection
            connection_logs_indexes = [
                IndexModel([("timestamp", ASCENDING)], background=True),
                IndexModel([("event_type", ASCENDING)], background=True),
                IndexModel([("status", ASCENDING)], background=True)
            ]
            await db.connection_logs.create_indexes(connection_logs_indexes)
            
            logger.info("Database indexes created successfully")
            
        except Exception as e:
            logger.warning(f"Failed to create indexes: {e}")
    
    async def log_telemetry(self, event: TelemetryEvent):
        """Log telemetry to database or CSV fallback."""
        if self._use_csv_fallback:
            await self._log_to_csv(event)
        else:
            try:
                # Convert timestamp to datetime object if it's a string
                event_dict = event.model_dump()
                if isinstance(event_dict['timestamp'], str):
                    event_dict['timestamp'] = datetime.fromisoformat(event_dict['timestamp'])
                
                # Use a lightweight insertion to minimize latency impact
                await self._async_client[settings.DB_NAME].telemetry.insert_one(event_dict)
                
                # If this is an LLM run event, also store it in the llm_runs collection
                if event.event_type == "llm_run" and event.metadata and event.metadata.additional_data:
                    try:
                        # Extract the necessary fields from the telemetry event
                        add_data = event.metadata.additional_data
                        llm_run_data = {
                            "request_id": event.request_id,
                            "timestamp": event.timestamp,
                            "soeid": event.metadata.soeid,
                            "project_name": event.metadata.project_name,
                            "prompt": add_data.get("prompt", ""),
                            "completion": add_data.get("completion", ""),
                            "model": add_data.get("model", event.metadata.llm_model or "unknown"),
                            "temperature": add_data.get("temperature", 0.7),
                            "max_tokens": add_data.get("max_tokens", 2000),
                            "prompt_tokens": event.metadata.prompt_tokens or 0,
                            "completion_tokens": event.metadata.completion_tokens or 0,
                            "total_tokens": event.metadata.total_tokens or 0,
                            "latency_ms": event.metadata.latency_ms or 0
                        }
                        
                        # Insert into llm_runs collection
                        await self._async_client[settings.DB_NAME].llm_runs.insert_one(llm_run_data)
                    except Exception as e:
                        logger.warning(f"Failed to store LLM run in dedicated collection: {e}")
                
            except Exception as e:
                logger.warning(f"MongoDB logging failed: {e}. Using CSV fallback.")
                self._use_csv_fallback = True
                self._setup_csv_fallback()
                await self._log_to_csv(event)
    
    async def log_connection_event(self, event_type, status, message, metadata=None):
        """Log a connection event to the database or CSV fallback."""
        timestamp = datetime.utcnow()
        
        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "status": status,
            "message": message,
            "metadata": metadata or {}
        }
        
        if self._use_csv_fallback:
            # Create a telemetry-like event for CSV logging
            event = self._create_connection_event(event_type, status, message, metadata)
            await self._log_to_csv(event)
        else:
            try:
                # Insert the connection log
                await self._async_client[settings.DB_NAME].connection_logs.insert_one(log_entry)
            except Exception as e:
                logger.warning(f"MongoDB connection logging failed: {e}. Using CSV fallback.")
                self._use_csv_fallback = True
                self._setup_csv_fallback()
                
                # Create a telemetry-like event for CSV logging
                event = self._create_connection_event(event_type, status, message, metadata)
                await self._log_to_csv(event)
    
    def _create_connection_event(self, event_type, status, message, metadata=None):
        """Create a telemetry event from connection log data for CSV fallback."""
        from models import RequestMetadata  # Import here to avoid circular import
        
        return TelemetryEvent(
            event_type=f"connection_{event_type}",
            timestamp=datetime.utcnow(),
            request_id=f"conn_{int(time.time() * 1000)}",
            client_ip="",
            metadata=RequestMetadata(
                client_id="system",
                target_service="database",
                endpoint="connection",
                method="SYSTEM",
                status_code=200 if status == "success" else 500,
                latency_ms=0,
                additional_data={
                    "message": message,
                    "status": status,
                    "metadata": metadata or {}
                }
            )
        )
    
    async def _log_to_csv(self, event: TelemetryEvent):
        """Log telemetry event to CSV file."""
        today = datetime.now().strftime("%Y-%m-%d")
        filename = f"{self._csv_dir}/telemetry_{today}.csv"
        
        # Flatten the event data for CSV storage
        flat_data = {
            "timestamp": event.timestamp.isoformat() if isinstance(event.timestamp, datetime) else event.timestamp,
            "event_type": event.event_type,
            "client_ip": event.client_ip,
            "request_id": event.request_id,
            "client_id": event.metadata.client_id,
            "soeid": event.metadata.soeid,
            "project_name": event.metadata.project_name,
            "target_service": event.metadata.target_service,
            "endpoint": event.metadata.endpoint,
            "method": event.metadata.method,
            "status_code": event.metadata.status_code,
            "latency_ms": event.metadata.latency_ms,
            "request_size": event.metadata.request_size,
            "response_size": event.metadata.response_size,
            "prompt_tokens": event.metadata.prompt_tokens,
            "completion_tokens": event.metadata.completion_tokens,
            "total_tokens": event.metadata.total_tokens,
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
    
    async def get_metrics(self):
        """Get service metrics."""
        # Check cache first
        if (datetime.now() - self._metrics_last_update).total_seconds() < 60:
            return self._metrics_cache
        
        metrics = {
            "requests_total": 0,
            "requests_last_hour": 0,
            "avg_latency_ms": 0,
            "error_rate": 0,
            "token_usage_total": 0,
            "llm_runs_total": 0,
            "database_status": "fallback" if self._use_csv_fallback else "connected"
        }
        
        if self._use_csv_fallback:
            # In CSV fallback mode, provide minimal metrics
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                filename = f"{self._csv_dir}/telemetry_{today}.csv"
                
                if os.path.isfile(filename):
                    with open(filename, 'r', newline='') as csvfile:
                        reader = csv.DictReader(csvfile)
                        rows = list(reader)
                        
                        # Count all events
                        metrics["requests_total"] = len([r for r in rows if r["event_type"] == "llm_request" or r["event_type"] == "direct_request"])
                        
                        # Count LLM runs
                        metrics["llm_runs_total"] = len([r for r in rows if r["event_type"] == "llm_run"])
                        
                        # Calculate recent requests
                        one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
                        recent_rows = [r for r in rows if r["timestamp"] >= one_hour_ago]
                        metrics["requests_last_hour"] = len([r for r in recent_rows if r["event_type"] == "llm_request" or r["event_type"] == "direct_request"])
                        
                        # Calculate error rate
                        if rows:
                            error_rows = [r for r in rows if r["event_type"] in ["llm_request", "direct_request"] and int(r["status_code"]) >= 400]
                            if metrics["requests_total"] > 0:
                                metrics["error_rate"] = len(error_rows) / metrics["requests_total"]
                        
                        # Calculate average latency
                        if rows:
                            latency_rows = [r for r in rows if r["event_type"] in ["llm_request", "direct_request"]]
                            latencies = [float(r["latency_ms"]) for r in latency_rows if r["latency_ms"]]
                            if latencies:
                                metrics["avg_latency_ms"] = sum(latencies) / len(latencies)
                        
                        # Calculate token usage
                        token_rows = [r for r in rows if r["event_type"] in ["llm_request", "llm_run"]]
                        total_tokens = [int(r["total_tokens"]) for r in token_rows if r["total_tokens"] and r["total_tokens"].isdigit()]
                        if total_tokens:
                            metrics["token_usage_total"] = sum(total_tokens)
            except Exception as e:
                logger.error(f"Error calculating CSV metrics: {e}")
        else:
            try:
                db = self._async_client[settings.DB_NAME]
                
                # Total requests
                metrics["requests_total"] = await db.telemetry.count_documents({
                    "event_type": {"$in": ["llm_request", "direct_request"]}
                })
                
                # Total LLM runs
                metrics["llm_runs_total"] = await db.telemetry.count_documents({
                    "event_type": "llm_run"
                })
                
                # Recent requests
                one_hour_ago = datetime.now() - timedelta(hours=1)
                metrics["requests_last_hour"] = await db.telemetry.count_documents({
                    "timestamp": {"$gte": one_hour_ago},
                    "event_type": {"$in": ["llm_request", "direct_request"]}
                })
                
                # Average latency
                latency_pipeline = [
                    {"$match": {
                        "event_type": {"$in": ["llm_request", "direct_request"]},
                        "metadata.latency_ms": {"$ne": None}
                    }},
                    {"$group": {"_id": None, "avg_latency": {"$avg": "$metadata.latency_ms"}}}
                ]
                latency_result = await db.telemetry.aggregate(latency_pipeline).to_list(1)
                if latency_result:
                    metrics["avg_latency_ms"] = latency_result[0]["avg_latency"]
                
                # Error rate
                total_count = await db.telemetry.count_documents({
                    "event_type": {"$in": ["llm_request", "direct_request"]}
                })
                error_count = await db.telemetry.count_documents({
                    "event_type": {"$in": ["llm_request", "direct_request"]},
                    "metadata.status_code": {"$gte": 400}
                })
                if total_count > 0:
                    metrics["error_rate"] = error_count / total_count
                
                # Token usage from telemetry
                token_pipeline = [
                    {"$match": {
                        "event_type": {"$in": ["llm_request", "llm_run"]},
                        "metadata.total_tokens": {"$ne": None}
                    }},
                    {"$group": {"_id": None, "total_tokens": {"$sum": "$metadata.total_tokens"}}}
                ]
                token_result = await db.telemetry.aggregate(token_pipeline).to_list(1)
                if token_result:
                    metrics["token_usage_total"] = token_result[0]["total_tokens"]
                
                # Store calculated metrics for future reference
                await db.metrics.insert_one({
                    "timestamp": datetime.now(),
                    "metric_type": "hourly",
                    "metrics": metrics
                })
                
            except Exception as e:
                logger.error(f"Error calculating MongoDB metrics: {e}")
                # If MongoDB metrics fail, try to get from CSV fallback
                if os.path.exists(self._csv_dir):
                    self._use_csv_fallback = True
                    return await self.get_metrics()
        
        # Update cache
        self._metrics_cache = metrics
        self._metrics_last_update = datetime.now()
        
        return metrics
    
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