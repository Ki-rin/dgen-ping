#!/usr/bin/env python
"""Simplified script to run dgen-ping with essential checks."""
import os
import subprocess
import sys

def check_dependencies():
    """Check and install required dependencies."""
    print("📦 Checking dependencies...")
    
    dependencies = [
        "fastapi", "uvicorn[standard]", "pydantic", "pymongo", 
        "motor", "PyJWT", "httpx", "python-multipart", 
        "python-dotenv", "pydantic-settings", "dnspython", "aiofiles"
    ]
    
    missing = []
    for dep in dependencies:
        try:
            __import__(dep.replace("-", "_").split("[")[0])
            print(f"✅ {dep}")
        except ImportError:
            print(f"❌ {dep}")
            missing.append(dep)
    
    # Check dgen_llm separately
    try:
        import dgen_llm
        print("✅ dgen_llm")
    except ImportError:
        print("⚠️  dgen_llm missing (will use mock)")
    
    if missing:
        print(f"Installing: {', '.join(missing)}")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install"] + missing, check=True)
            print("✅ Dependencies installed")
        except subprocess.CalledProcessError as e:
            print(f"❌ Install failed: {e}")
            return False
    
    return True

def setup_environment():
    """Setup basic environment."""
    print("⚙️ Setting up environment...")
    
    # Create directories
    os.makedirs("telemetry_logs", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    # Set default environment variables
    defaults = {
        "DEBUG": "true",
        "HOST": "127.0.0.1",
        "PORT": "8001",
        "ALLOW_DEFAULT_TOKEN": "true",
        "CSV_FALLBACK_DIR": "telemetry_logs",
        "MAX_CONCURRENCY": "20",
        "TOKEN_SECRET": "dgen_secret_key_change_in_production"
    }
    
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
    
    print("✅ Environment ready")
    return True

def test_imports():
    """Test critical imports."""
    print("🔍 Testing imports...")
    
    modules = ["fastapi", "uvicorn", "config", "db", "auth", "proxy", "models", "middleware"]
    
    for module in modules:
        try:
            __import__(module)
            print(f"✅ {module}")
        except ImportError as e:
            print(f"❌ {module}: {e}")
            return False
        except Exception as e:
            print(f"⚠️  {module}: {e}")
    
    return True

def run_service():
    """Run the service."""
    print("\n🚀 Starting dgen-ping service")
    print(f"API: http://127.0.0.1:8001")
    print(f"Docs: http://127.0.0.1:8001/docs")
    print("=" * 40)
    
    try:
        cmd = [
            "uvicorn", "main:app",
            "--host", "127.0.0.1",
            "--port", "8001",
            "--reload",
            "--log-level", "info"
        ]
        
        subprocess.run(cmd, check=True)
        
    except KeyboardInterrupt:
        print("\n⏹️  Service stopped")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Service failed: {e}")
    except FileNotFoundError:
        print("\n❌ uvicorn not found. Install with: pip install uvicorn[standard]")

def main():
    """Main function."""
    print("🚀 dgen-ping Service Runner")
    print("=" * 30)
    
    # Run checks
    if not check_dependencies():
        print("❌ Dependency check failed")
        sys.exit(1)
    
    if not setup_environment():
        print("❌ Environment setup failed")
        sys.exit(1)
    
    if not test_imports():
        print("❌ Import test failed")
        sys.exit(1)
    
    print("\n✅ All checks passed!")
    input("Press Enter to start the service...")
    
    run_service()

if __name__ == "__main__":
    main()
