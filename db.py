"""Database operations for dgen-ping."""
import logging
import csv
import os
from datetime import datetime
from pymongo import MongoClient
from config import settings

logger = logging.getLogger("dgen-ping.db")

class Database:
    def __init__(self):
        self.client = None
        self.db = None
        self.connected = False
        self.csv_dir = "telemetry_logs"
        
        # Try multiple MongoDB URIs
        mongo_uris = [
            settings.MONGO_URI,
            os.getenv("MONGO_URI_BACKUP", ""),
            os.getenv("MONGO_URI_FALLBACK", "")
        ]
        
        for uri in mongo_uris:
            if uri and self._try_connect(uri):
                break
        
        # Create CSV directory if not connected
        if not self.connected:
            os.makedirs(self.csv_dir, exist_ok=True)
            logger.info("Using CSV fallback for telemetry")
    
    def _try_connect(self, uri: str) -> bool:
        """Try connecting to MongoDB URI."""
        try:
            self.client = MongoClient(
                uri,
                serverSelectionTimeoutMS=3000,
                connectTimeoutMS=3000
            )
            self.db = self.client[settings.DB_NAME]
            # Test connection
            self.client.admin.command('ping')
            self.connected = True
            logger.info(f"MongoDB connected: {uri[:20]}...")
            return True
        except Exception as e:
            logger.warning(f"MongoDB connection failed: {e}")
            return False
    
    def log_telemetry(self, event_data: dict) -> bool:
        """Log telemetry to MongoDB or CSV fallback."""
        if self.connected:
            try:
                self.db.telemetry.insert_one(event_data)
                return True
            except Exception as e:
                logger.error(f"MongoDB logging failed: {e}")
                self.connected = False  # Mark as disconnected
        
        # CSV fallback
        return self._log_to_csv(event_data)
    
    def _log_to_csv(self, data: dict) -> bool:
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
                else:
                    flat_data[key] = value
            
            # Add timestamp if missing
            if 'timestamp' not in flat_data:
                flat_data['timestamp'] = datetime.utcnow().isoformat()
            
            with open(csv_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=flat_data.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(flat_data)
            
            return True
        except Exception as e:
            logger.error(f"CSV logging failed: {e}")
            return False
    
    def health_check(self) -> dict:
        """Database health check."""
        return {
            "connected": self.connected,
            "status": "healthy" if self.connected else "csv_fallback",
            "csv_dir": self.csv_dir if not self.connected else None
        }

# Global database instance
db = Database()
