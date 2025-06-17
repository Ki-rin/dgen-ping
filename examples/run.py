#!/usr/bin/env python
"""Script to run dgen-ping with direct dgen_llm integration.

This script starts the dgen-ping proxy service with the dgen_llm integration.
"""
import os
import subprocess
import sys

def check_dependencies():
    """Check and install required dependencies."""
    print("Checking dependencies...")
    
    # Check for dgen_llm
    try:
        import dgen_llm
        print("✅ dgen_llm is installed")
    except ImportError:
        print("❌ dgen_llm is not installed. Installing...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "dgen_llm"], check=True)
            print("✅ dgen_llm installed successfully")
        except subprocess.CalledProcessError:
            print("❌ Failed to install dgen_llm")
            return False
    
    # Check for FastAPI and other dependencies
    try:
        import fastapi
        import uvicorn
        print("✅ FastAPI and Uvicorn are installed")
    except ImportError:
        print("❌ FastAPI or Uvicorn is not installed. Installing...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "fastapi", "uvicorn"], check=True)
            print("✅ FastAPI and Uvicorn installed successfully")
        except subprocess.CalledProcessError:
            print("❌ Failed to install FastAPI and Uvicorn")
            return False
    
    return True

def setup_environment():
    """Set up the environment for the service."""
    print("Setting up environment...")
    
    # Create telemetry logs directory
    os.makedirs("telemetry_logs", exist_ok=True)
    print("✅ Created telemetry_logs directory")
    
    # Set environment variables for local development
    os.environ.update({
        "DEBUG": "true",
        "HOST": "127.0.0.1",
        "PORT": "8001",
        "ALLOW_DEFAULT_TOKEN": "true",
        "CSV_FALLBACK_DIR": "telemetry_logs",
        "MAX_CONCURRENCY": "20"
    })
    print("✅ Environment variables set")
    
    return True

def run_service():
    """Run the dgen-ping service."""
    print("\n=== Starting dgen-ping service ===")
    print("API: http://127.0.0.1:8001")
    print("Docs: http://127.0.0.1:8001/docs")
    print("Default token: '1' (enabled)")
    print("Mode: Direct dgen_llm integration")
    print("===================================\n")
    
    try:
        # Run the service with auto-reload
        subprocess.run(["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8001", "--reload"])
    except KeyboardInterrupt:
        print("\nService stopped by user")
    except Exception as e:
        print(f"\nError running service: {e}")

def main():
    """Main function."""
    print("=== dgen-ping Service Runner ===\n")
    
    if not check_dependencies():
        print("\n❌ Dependency check failed. Please install the required packages manually.")
        return
    
    if not setup_environment():
        print("\n❌ Environment setup failed.")
        return
    
    run_service()

if __name__ == "__main__":
    main()
