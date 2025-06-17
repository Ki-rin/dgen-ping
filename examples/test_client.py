#!/usr/bin/env python
"""Test client for dgen-ping service."""
import requests
import sys
import json
import time

URL = "http://127.0.0.1:8001"
SECRET = "dgen_secret_key_change_in_production"

def check_service():
    """Check if service is running."""
    try:
        resp = requests.get(f"{URL}/health", timeout=5)
        result = resp.json()
        print(f"✅ Service: {result.get('status', 'unknown')}")
        if result.get('database'):
            db_status = result['database'].get('status', 'unknown')
            print(f"   Database: {db_status}")
        return True
    except Exception as e:
        print(f"❌ Service not running: {e}")
        return False

def check_public_health():
    """Check public health endpoint."""
    try:
        resp = requests.get(f"{URL}/public/health", timeout=5)
        result = resp.json()
        print(f"✅ Public health: {result.get('status', 'unknown')}")
        return True
    except Exception as e:
        print(f"❌ Public health check failed: {e}")
        return False

def generate_token(soeid, project_id=None):
    """Generate JWT token for user."""
    headers = {"X-Token-Secret": SECRET, "Content-Type": "application/json"}
    payload = {"soeid": soeid}
    if project_id:
        payload["project_id"] = project_id
    
    try:
        resp = requests.post(f"{URL}/generate-token", headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ Token generated for {soeid}")
            print(f"   Token: {result['token'][:50]}...")
            print(f"   Project ID: {result['project_id']}")
            return result['token']
        else:
            print(f"❌ Token generation failed ({resp.status_code}): {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Token generation error: {e}")
        return None

def verify_token(token):
    """Verify JWT token."""
    headers = {"X-Token-Secret": SECRET, "Content-Type": "application/json"}
    payload = {"token": token}
    
    try:
        resp = requests.post(f"{URL}/verify-token", headers=headers, json=payload, timeout=10)
        result = resp.json()
        if result.get('valid'):
            data = result.get('data', {})
            print(f"✅ Token valid for {data.get('soeid', 'unknown')}")
            print(f"   Project: {data.get('project_id', 'unknown')}")
            return True
        else:
            print(f"❌ Token invalid: {result.get('error', 'unknown')}")
            return False
    except Exception as e:
        print(f"❌ Token verification error: {e}")
        return False

def test_llm(prompt, token=None, soeid="test_user", model="gemini"):
    """Test LLM completion."""
    headers = {"X-API-Token": token or "1", "Content-Type": "application/json"}
    payload = {
        "soeid": soeid,
        "project_name": soeid,
        "prompt": prompt,
        "model": model,
        "temperature": 0.3,
        "max_tokens": 1000
    }
    
    print(f"🤖 Testing LLM with model: {model}")
    start_time = time.time()
    
    try:
        resp = requests.post(f"{URL}/api/llm/completion", headers=headers, json=payload, timeout=30)
        elapsed = time.time() - start_time
        
        if resp.status_code == 200:
            result = resp.json()
            completion = result['completion']
            metadata = result.get('metadata', {})
            
            print(f"✅ LLM Response ({elapsed:.2f}s):")
            print(f"   Model: {result.get('model', 'unknown')}")
            print(f"   Latency: {metadata.get('latency', 'unknown')}s")
            print(f"   Tokens: {metadata.get('tokens', {})}")
            print(f"   Response: {completion[:200]}{'...' if len(completion) > 200 else ''}")
            return result
        else:
            print(f"❌ LLM error ({resp.status_code}): {resp.text}")
            return None
    except Exception as e:
        print(f"❌ LLM request error: {e}")
        return None

def test_metrics(token):
    """Test metrics endpoint."""
    headers = {"X-API-Token": token}
    
    try:
        resp = requests.get(f"{URL}/metrics", headers=headers, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ Metrics:")
            print(f"   Total requests: {result.get('requests_total', 0)}")
            print(f"   Database status: {result.get('database_status', 'unknown')}")
            return result
        else:
            print(f"❌ Metrics error ({resp.status_code}): {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Metrics request error: {e}")
        return None

def test_info(token):
    """Test info endpoint."""
    headers = {"X-API-Token": token}
    
    try:
        resp = requests.get(f"{URL}/info", headers=headers, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            auth = result.get('authentication', {})
            print(f"✅ Service info:")
            print(f"   Version: {result.get('version', 'unknown')}")
            print(f"   Token type: {auth.get('token_type', 'unknown')}")
            print(f"   User ID: {auth.get('user_id', 'unknown')}")
            return result
        else:
            print(f"❌ Info error ({resp.status_code}): {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Info request error: {e}")
        return None

def comprehensive_test(soeid, prompt="Hello, how are you?"):
    """Run comprehensive test suite."""
    print(f"🧪 Comprehensive test for SOEID: {soeid}")
    print("=" * 50)
    
    # 1. Check service health
    if not check_service():
        return False
    
    check_public_health()
    print()
    
    # 2. Test token generation and verification
    print("🔑 Testing authentication...")
    token = generate_token(soeid)
    if token:
        verify_token(token)
    else:
        print("⚠️ Continuing with default token")
        token = "1"
    print()
    
    # 3. Test service info
    print("ℹ️ Getting service info...")
    test_info(token)
    print()
    
    # 4. Test LLM completion
    print("🤖 Testing LLM completion...")
    test_llm(prompt, token, soeid)
    print()
    
    # 5. Test metrics
    print("📊 Getting metrics...")
    test_metrics(token)
    print()
    
    # 6. Test with different models
    print("🔄 Testing different models...")
    for model in ["gemini", "gpt-4", "claude"]:
        test_llm(f"Quick test for {model}", token, soeid, model)
    print()
    
    print("✅ Test suite completed!")
    return True

def main():
    # Default values
    soeid = "test_user"
    prompt = "Hello, how are you?"
    comprehensive = False
    
    # Parse arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--comprehensive":
            comprehensive = True
            soeid = sys.argv[2] if len(sys.argv) > 2 else soeid
            prompt = sys.argv[3] if len(sys.argv) > 3 else prompt
        else:
            soeid = sys.argv[1]
            prompt = sys.argv[2] if len(sys.argv) > 2 else prompt
    
    if comprehensive:
        comprehensive_test(soeid, prompt)
    else:
        print(f"🧪 Testing dgen-ping with SOEID: {soeid}")
        
        if not check_service():
            return
        
        # Generate and verify token
        token = generate_token(soeid)
        if token and verify_token(token):
            # Test LLM with token
            test_llm(prompt, token, soeid)
        
        # Test with default token
        print("\n🔄 Testing with default token...")
        test_llm(prompt, None, soeid)

if __name__ == "__main__":
    main()
