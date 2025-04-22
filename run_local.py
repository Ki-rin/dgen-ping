#!/usr/bin/env python
"""Local development script for running dgen-ping."""
import os
import uvicorn

# Set environment variables for local development
os.environ.update({
    "DEBUG": "true",
    "HOST": "127.0.0.1",
    "PORT": "8001",
    "ALLOW_DEFAULT_TOKEN": "true",
    "CSV_FALLBACK_DIR": "telemetry_logs",
    "DOWNSTREAM_SERVICES": '{"classifier":"http://localhost:8002","enhancer":"http://localhost:8003"}'
})

if __name__ == "__main__":
    # Create telemetry logs directory
    os.makedirs("telemetry_logs", exist_ok=True)
    
    print("Starting dgen-ping in development mode")
    print("API: http://127.0.0.1:8001")
    print("Docs: http://127.0.0.1:8001/docs")
    print("Default token: '1' (enabled)")
    
    # Run with auto-reload
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)