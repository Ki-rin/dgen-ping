#!/usr/bin/env python
"""Debug script to identify startup issues with dgen-ping."""
import sys
import traceback
import os

def check_imports():
    """Check if all required modules can be imported."""
    print("🔍 Checking imports...")
    
    modules_to_check = [
        'fastapi',
        'uvicorn', 
        'pydantic',
        'pymongo',
        'motor',
        'jwt',
        'config',
        'db',
        'auth',
        'proxy',
        'models',
        'middleware'
    ]
    
    failed_imports = []
    
    for module in modules_to_check:
        try:
            __import__(module)
            print(f"✅ {module}")
        except ImportError as e:
            print(f"❌ {module}: {e}")
            failed_imports.append((module, str(e)))
        except Exception as e:
            print(f"⚠️  {module}: {e}")
            failed_imports.append((module, str(e)))
    
    return failed_imports

def check_environment():
    """Check environment variables and configuration."""
    print("\n🔧 Checking environment...")
    
    # Check critical environment variables
    env_vars = [
        'MONGO_URI',
        'DB_NAME', 
        'TOKEN_SECRET',
        'DEBUG',
        'HOST',
        'PORT'
    ]
    
    for var in env_vars:
        value = os.getenv(var, 'NOT_SET')
        if value == 'NOT_SET':
            print(f"⚠️  {var}: Not set (will use default)")
        else:
            # Mask sensitive values
            if 'SECRET' in var or 'URI' in var:
                masked_value = value[:10] + "..." if len(value) > 10 else "***"
                print(f"✅ {var}: {masked_value}")
            else:
                print(f"✅ {var}: {value}")

def test_config():
    """Test configuration loading."""
    print("\n⚙️ Testing configuration...")
    
    try:
        from config import settings
        print(f"✅ Configuration loaded")
        print(f"   Debug: {settings.DEBUG}")
        print(f"   Host: {settings.HOST}")
        print(f"   Port: {settings.PORT}")
        print(f"   Max concurrency: {settings.MAX_CONCURRENCY}")
        print(f"   Allow default token: {settings.ALLOW_DEFAULT_TOKEN}")
        return True
    except Exception as e:
        print(f"❌ Configuration failed: {e}")
        traceback.print_exc()
        return False

def test_database():
    """Test database connection."""
    print("\n💾 Testing database...")
    
    try:
        from db import db
        print("✅ Database module imported")
        
        # Test if we can create the database instance
        if hasattr(db, 'is_connected'):
            print(f"   Connection status available: {db.is_connected}")
        
        return True
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        traceback.print_exc()
        return False

def test_auth():
    """Test authentication module."""
    print("\n🔐 Testing authentication...")
    
    try:
        from auth import AuthManager, get_token_payload
        print("✅ Auth module imported")
        
        # Test token generation (basic test)
        try:
            token = AuthManager.generate_token("test_user")
            print("✅ Token generation works")
            
            # Test token verification
            payload = AuthManager.verify_token(token)
            print("✅ Token verification works")
            
        except Exception as e:
            print(f"⚠️  Token operations failed: {e}")
            
        return True
    except Exception as e:
        print(f"❌ Auth test failed: {e}")
        traceback.print_exc()
        return False

def test_proxy():
    """Test proxy service."""
    print("\n🔄 Testing proxy service...")
    
    try:
        from proxy import ProxyService
        print("✅ Proxy module imported")
        
        # Check if dgen_llm is available
        try:
            from dgen_llm import llm_connection
            print("✅ dgen_llm available")
        except ImportError:
            print("⚠️  dgen_llm not available (will use mock)")
            
        return True
    except Exception as e:
        print(f"❌ Proxy test failed: {e}")
        traceback.print_exc()
        return False

def test_models():
    """Test data models."""
    print("\n📋 Testing models...")
    
    try:
        from models import LlmRequest, LlmResponse, TelemetryEvent, RequestMetadata, TokenPayload
        print("✅ Models imported")
        
        # Test model creation
        try:
            request = LlmRequest(
                soeid="test_user",
                project_name="test_project", 
                prompt="Hello world",
                model="gpt-4"
            )
            print("✅ LlmRequest creation works")
        except Exception as e:
            print(f"⚠️  Model creation failed: {e}")
            
        return True
    except Exception as e:
        print(f"❌ Models test failed: {e}")
        traceback.print_exc()
        return False

def test_app_creation():
    """Test FastAPI app creation."""
    print("\n🚀 Testing app creation...")
    
    try:
        # Import the main module to test app creation
        from main import app
        print("✅ FastAPI app created successfully")
        
        # Check if app has expected attributes
        if hasattr(app, 'routes'):
            route_count = len(app.routes)
            print(f"   Routes: {route_count}")
            
        return True
    except Exception as e:
        print(f"❌ App creation failed: {e}")
        traceback.print_exc()
        return False

def main():
    """Run all diagnostic tests."""
    print("🔍 dgen-ping Startup Diagnostics")
    print("=" * 40)
    
    # Set environment for testing
    os.environ.setdefault('DEBUG', 'true')
    os.environ.setdefault('ALLOW_DEFAULT_TOKEN', 'true')
    
    tests = [
        ("Import Check", check_imports),
        ("Environment Check", check_environment), 
        ("Configuration Test", test_config),
        ("Database Test", test_database),
        ("Authentication Test", test_auth),
        ("Proxy Test", test_proxy),
        ("Models Test", test_models),
        ("App Creation Test", test_app_creation)
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results[test_name] = result
        except Exception as e:
            print(f"\n❌ {test_name} crashed: {e}")
            traceback.print_exc()
            results[test_name] = False
    
    # Summary
    print("\n" + "=" * 40)
    print("📊 Test Summary:")
    
    passed = 0
    total = len(tests)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! The application should start correctly.")
        print("\n💡 Try running: python examples/run.py")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Fix these issues before starting the application.")
        
        # Provide specific guidance
        if not results.get("Import Check", True):
            print("\n🔧 Import issues detected:")
            print
