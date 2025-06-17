#!/usr/bin/env python
"""Script to run dgen-ping with direct dgen_llm integration and enhanced error handling."""
import os
import subprocess
import sys
import traceback

def check_python_version():
    """Check if Python version is compatible."""
    print("🐍 Checking Python version...")
    
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print(f"❌ Python {version.major}.{version.minor} is not supported. Please use Python 3.8 or later.")
        return False
    
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} is compatible")
    return True

def check_dependencies():
    """Check and install required dependencies."""
    print("📦 Checking dependencies...")
    
    # Core dependencies with versions
    dependencies = [
        ("fastapi", "fastapi>=0.68.0"),
        ("uvicorn", "uvicorn[standard]>=0.15.0"),
        ("pydantic", "pydantic>=1.8.0"),
        ("pymongo", "pymongo>=4.0.0"),
        ("motor", "motor>=3.0.0"),
        ("PyJWT", "PyJWT>=2.8.0"),
        ("httpx", "httpx>=0.24.0"),
        ("python-multipart", "python-multipart"),
        ("python-dotenv", "python-dotenv"),
        ("pydantic-settings", "pydantic-settings"),
        ("dnspython", "dnspython"),
        ("aiofiles", "aiofiles")
    ]
    
    missing_deps = []
    
    for dep_name, dep_spec in dependencies:
        try:
            __import__(dep_name.replace("-", "_"))
            print(f"✅ {dep_name} is installed")
        except ImportError:
            print(f"❌ {dep_name} is missing")
            missing_deps.append(dep_spec)
    
    # Check for dgen_llm separately (optional)
    try:
        import dgen_llm
        print("✅ dgen_llm is installed")
    except ImportError:
        print("⚠️  dgen_llm is not installed. Installing...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "dgen_llm"], 
                         check=True, capture_output=True, text=True)
            print("✅ dgen_llm installed successfully")
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Failed to install dgen_llm: {e}")
            print("   The service will run in mock mode")
    
    # Install missing dependencies
    if missing_deps:
        print(f"🔧 Installing missing dependencies: {', '.join(missing_deps)}")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install"] + missing_deps, 
                         check=True, capture_output=True, text=True)
            print("✅ All dependencies installed successfully")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install dependencies: {e}")
            print("   Please install manually:")
            for dep in missing_deps:
                print(f"     pip install {dep}")
            return False
    
    return True

def setup_environment():
    """Set up the environment for the service."""
    print("⚙️ Setting up environment...")
    
    # Create necessary directories
    directories = ["telemetry_logs", "logs"]
    for directory in directories:
        try:
            os.makedirs(directory, exist_ok=True)
            print(f"✅ Created {directory} directory")
        except Exception as e:
            print(f"⚠️  Failed to create {directory}: {e}")
    
    # Set environment variables for local development
    env_vars = {
        "DEBUG": "true",
        "HOST": "127.0.0.1", 
        "PORT": "8001",
        "ALLOW_DEFAULT_TOKEN": "true",
        "CSV_FALLBACK_DIR": "telemetry_logs",
        "MAX_CONCURRENCY": "20",
        "TOKEN_SECRET": "dgen_secret_key_change_in_production"
    }
    
    for key, value in env_vars.items():
        os.environ.setdefault(key, value)
        print(f"✅ {key}: {value}")
    
    return True

def test_imports():
    """Test critical imports before starting the server."""
    print("🔍 Testing imports...")
    
    critical_modules = [
        "fastapi",
        "uvicorn", 
        "config",
        "db",
        "auth",
        "proxy", 
        "models",
        "middleware"
    ]
    
    for module in critical_modules:
        try:
            __import__(module)
            print(f"✅ {module}")
        except ImportError as e:
            print(f"❌ {module}: {e}")
            return False
        except Exception as e:
            print(f"⚠️  {module}: {e}")
            # Continue with warnings
    
    return True

def test_app_creation():
    """Test if the FastAPI app can be created without errors."""
    print("🚀 Testing app creation...")
    
    try:
        # Set environment for testing
        os.environ["DEBUG"] = "true"
        os.environ["ALLOW_DEFAULT_TOKEN"] = "true"
        
        # Try to import the main app
        from main import app
        
        print("✅ FastAPI app created successfully")
        
        # Check basic app properties
        if hasattr(app, 'routes'):
            route_count = len([r for r in app.routes if hasattr(r, 'path')])
            print(f"   Routes registered: {route_count}")
        
        return True
        
    except Exception as e:
        print(f"❌ App creation failed: {e}")
        print("\nFull error traceback:")
        traceback.print_exc()
        return False

def run_diagnostics():
    """Run comprehensive diagnostics."""
    print("🔍 Running diagnostics...")
    
    try:
        # Run the debug script if it exists
        result = subprocess.run([sys.executable, "debug_startup.py"], 
                               capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print("✅ Diagnostics completed successfully")
            print(result.stdout)
        else:
            print("⚠️  Diagnostics found issues:")
            print(result.stdout)
            if result.stderr:
                print("Errors:")
                print(result.stderr)
    except subprocess.TimeoutExpired:
        print("⚠️  Diagnostics timed out")
    except FileNotFoundError:
        print("⚠️  Debug script not found, skipping diagnostics")
    except Exception as e:
        print(f"⚠️  Diagnostics failed: {e}")

def run_service():
    """Run the dgen-ping service with enhanced error handling."""
    print("\n" + "=" * 50)
    print("🚀 Starting dgen-ping service")
    print("=" * 50)
    print(f"API: http://127.0.0.1:8001")
    print(f"Docs: http://127.0.0.1:8001/docs")
    print(f"Health: http://127.0.0.1:8001/health")
    print(f"Default token: '1' (enabled)")
    print(f"Mode: Direct dgen_llm integration")
    print("=" * 50 + "\n")
    
    try:
        # Run the service with auto-reload and better error handling
        cmd = [
            "uvicorn", 
            "main:app",
            "--host", "127.0.0.1",
            "--port", "8001", 
            "--reload",
            "--log-level", "info",
            "--access-log"
        ]
        
        print(f"🔧 Running command: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        
    except KeyboardInterrupt:
        print("\n⏹️  Service stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Service failed with exit code {e.returncode}")
        print("   Check the error messages above for details")
    except FileNotFoundError:
        print("\n❌ uvicorn not found. Please install it:")
        print("   pip install uvicorn[standard]")
    except Exception as e:
        print(f"\n❌ Unexpected error running service: {e}")
        traceback.print_exc()

def main():
    """Main function with comprehensive startup checks."""
    print("=" * 60)
    print("🚀 dgen-ping Service Runner (Enhanced)")
    print("=" * 60)
    
    # Step 1: Check Python version
    if not check_python_version():
        sys.exit(1)
    
    # Step 2: Check and install dependencies
    print()
    if not check_dependencies():
        print("\n❌ Dependency check failed. Please install the required packages manually.")
        sys.exit(1)
    
    # Step 3: Setup environment
    print()
    if not setup_environment():
        print("\n❌ Environment setup failed.")
        sys.exit(1)
    
    # Step 4: Test imports
    print()
    if not test_imports():
        print("\n❌ Import test failed. Please check your installation.")
        sys.exit(1)
    
    # Step 5: Test app creation
    print()
    if not test_app_creation():
        print("\n❌ App creation test failed.")
        print("   This suggests there's an issue with the application code.")
        print("   Please check the error details above.")
        
        # Offer to run diagnostics
        response = input("\n🔍 Would you like to run detailed diagnostics? (y/n): ")
        if response.lower().startswith('y'):
            run_diagnostics()
        
        sys.exit(1)
    
    # Step 6: All checks passed, run the service
    print("\n✅ All startup checks passed!")
    input("Press Enter to start the service...")
    
    run_service()

if __name__ == "__main__":
    main()
