"""Database operations for dgen-ping."""
import logging
import csv
import os
import asyncio
from datetime import datetime
from pymongo import MongoClient
from config import settings
from models import TelemetryEvent

logger = logging.getLogger("dgen-ping.db")

class Database:
    def __init__(self):
        self.client = None
        self.db = None
        self.is_connected = False
        self.csv_dir = settings.CSV_FALLBACK_DIR
        
    async def initialize(self):
        """Initialize database connection."""
        # Try multiple MongoDB URIs
        mongo_uris = [
            settings.MONGO_URI,
            settings.MONGO_URI_BACKUP,
            settings.MONGO_URI_FALLBACK
        ]
        
        for uri in mongo_uris:
            if uri and await self._try_connect(uri):
                break
        
        # Create CSV directory if not connected
        if not self.is_connected:
            os.makedirs(self.csv_dir, exist_ok=True)
            logger.info("Using CSV fallback for telemetry")
    
    async def _try_connect(self, uri: str) -> bool:
        """Try connecting to MongoDB URI."""
        try:
            self.client = MongoClient(
                uri,
                serverSelectionTimeoutMS=3000,
                connectTimeoutMS=3000
            )
            self.db = self.client[settings.DB_NAME]
            
            # Test connection in executor to avoid blocking
            await asyncio.get_event_loop().run_in_executor(
                None, self.client.admin.command, 'ping'
            )
            
            self.is_connected = True
            logger.info(f"MongoDB connected: {uri[:20]}...")
            return True
        except Exception as e:
            logger.warning(f"MongoDB connection failed: {e}")
            return False
    
    async def log_telemetry(self, event: TelemetryEvent) -> bool:
        """Log telemetry to MongoDB or CSV fallback."""
        event_data = event.dict()
        
        # Add timestamp if missing
        if not event_data.get('timestamp'):
            event_data['timestamp'] = datetime.utcnow()
        
        if self.is_connected:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self.db.telemetry.insert_one, event_data
                )
                return True
            except Exception as e:
                logger.error(f"MongoDB logging failed: {e}")
                self.is_connected = False  # Mark as disconnected
        
        # CSV fallback
        return await self._log_to_csv(event_data)
    
    async def _log_to_csv(self, data: dict) -> bool:
        """Log to CSV file."""
        try:
            csv_file = os.path.join(self.csv_dir, "telemetry.csv")
            file_exists = os.path.exists(csv_file)
            
            # Flatten nested data
            flat_data = {}
            for key, value in data.items():
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        flat_data[f"{key}_{sub_key}"] = sub_value
                elif isinstance(value, datetime):
                    flat_data[key] = value.isoformat()
                else:
                    flat_data[key] = value
            
            # Add timestamp if missing
            if 'timestamp' not in flat_data:
                flat_data['timestamp'] = datetime.utcnow().isoformat()
            
            # Write to CSV in executor to avoid blocking
            await asyncio.get_event_loop().run_in_executor(
                None, self._write_csv, csv_file, flat_data, file_exists
            )
            
            return True
        except Exception as e:
            logger.error(f"CSV logging failed: {e}")
            return False
    
    def _write_csv(self, csv_file: str, flat_data: dict, file_exists: bool):
        """Write data to CSV file (blocking operation for executor)."""
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=flat_data.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(flat_data)
    
    async def log_connection_event(self, event_type: str, status: str, message: str, data: dict = None):
        """Log connection/system events."""
        event_data = {
            "event_type": event_type,
            "status": status,
            "message": message,
            "timestamp": datetime.utcnow(),
            "data": data or {}
        }
        
        if self.is_connected:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self.db.system_events.insert_one, event_data
                )
                return
            except Exception:
                self.is_connected = False
        
        # CSV fallback for system events
        await self._log_to_csv(event_data)
    
    async def health_check(self) -> dict:
        """Database health check."""
        return {
            "connected": self.is_connected,
            "status": "healthy" if self.is_connected else "csv_fallback",
            "csv_dir": self.csv_dir if not self.is_connected else None
        }
    
    async def get_metrics(self) -> dict:
        """Get system metrics."""
        try:
            if self.is_connected:
                count = await asyncio.get_event_loop().run_in_executor(
                    None, self.db.telemetry.count_documents, {}
                )
                return {
                    "requests_total": count,
                    "database_status": "connected"
                }
            else:
                # Count CSV rows if available
                csv_file = os.path.join(self.csv_dir, "telemetry.csv")
                if os.path.exists(csv_file):
                    with open(csv_file, 'r') as f:
                        count = sum(1 for line in f) - 1  # Subtract header
                    return {
                        "requests_total": max(0, count),
                        "database_status": "csv_fallback"
                    }
                else:
                    return {
                        "requests_total": 0,
                        "database_status": "csv_fallback"
                    }
        except Exception as e:
            logger.error(f"Error getting metrics: {e}")
            return {
                "requests_total": 0,
                "database_status": "error"
            }

# Global database instance
db = Database()
