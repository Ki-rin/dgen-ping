#!/usr/bin/env python
"""Simple runner for dgen-ping service."""
import os
import subprocess
import sys

def install_deps():
    """Install missing dependencies."""
    deps = ["fastapi", "uvicorn[standard]", "pydantic", "PyJWT", "pymongo"]
    missing = []
    
    for dep in deps:
        try:
            __import__(dep.replace("-", "_").split("[")[0])
        except ImportError:
            missing.append(dep)
    
    if missing:
        print(f"Installing: {', '.join(missing)}")
        subprocess.run([sys.executable, "-m", "pip", "install"] + missing, check=True)

def setup_env():
    """Set environment defaults."""
    defaults = {
        "DEBUG": "true",
        "TOKEN_SECRET": "dgen_secret_key_change_in_production",
        "ALLOW_DEFAULT_TOKEN": "true"
    }
    
    for key, value in defaults.items():
        os.environ.setdefault(key, value)

def main():
    print("🚀 Starting dgen-ping...")
    
    try:
        install_deps()
        setup_env()
        
        print("Service: http://127.0.0.1:8001")
        print("Docs: http://127.0.0.1:8001/docs")
        
        subprocess.run([
            "uvicorn", "main:app",
            "--host", "127.0.0.1",
            "--port", "8001",
            "--reload"
        ])
        
    except KeyboardInterrupt:
        print("\n⏹️ Service stopped")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
