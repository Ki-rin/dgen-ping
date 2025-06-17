#!/usr/bin/env python
"""Test client for dgen-ping service."""
import requests
import sys
import time

URL = "http://127.0.0.1:8001"
SECRET = "dgen_secret_key_change_in_production"

def check_service():
    """Check if service is running."""
    try:
        resp = requests.get(f"{URL}/health", timeout=5)
        result = resp.json()
        print(f"Service: {result.get('status')} | DB: {result.get('database', {}).get('status', 'unknown')}")
        return True
    except Exception as e:
        print(f"❌ Service not running: {e}")
        return False

def generate_token(soeid):
    """Generate JWT token."""
    headers = {"X-Token-Secret": SECRET, "Content-Type": "application/json"}
    payload = {"soeid": soeid}
    
    try:
        resp = requests.post(f"{URL}/generate-token", headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ Token generated for {soeid}")
            return result['token']
        else:
            print(f"❌ Token failed: {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Token error: {e}")
        return None

def verify_token(token):
    """Verify JWT token."""
    headers = {"X-Token-Secret": SECRET, "Content-Type": "application/json"}
    payload = {"token": token}
    
    try:
        resp = requests.post(f"{URL}/verify-token", headers=headers, json=payload, timeout=10)
        result = resp.json()
        if result.get('valid'):
            print(f"✅ Token valid for {result['data']['soeid']}")
            return True
        else:
            print(f"❌ Token invalid: {result.get('error')}")
            return False
    except Exception as e:
        print(f"❌ Verify error: {e}")
        return False

def test_llm(prompt, token, soeid):
    """Test LLM completion."""
    headers = {"X-API-Token": token, "Content-Type": "application/json"}
    payload = {
        "soeid": soeid,
        "project_name": soeid,
        "prompt": prompt,
        "model": "gemini"
    }
    
    start_time = time.time()
    try:
        resp = requests.post(f"{URL}/api/llm/completion", headers=headers, json=payload, timeout=30)
        elapsed = time.time() - start_time
        
        if resp.status_code == 200:
            result = resp.json()
            completion = result['completion']
            print(f"✅ LLM Response ({elapsed:.2f}s): {completion[:150]}...")
            return result
        else:
            print(f"❌ LLM error: {resp.text}")
            return None
    except Exception as e:
        print(f"❌ LLM error: {e}")
        return None

def test_telemetry(token, soeid):
    """Test telemetry logging."""
    headers = {"X-API-Token": token, "Content-Type": "application/json"}
    payload = {
        "event_type": "test_event",
        "request_id": "test-123",
        "client_ip": "127.0.0.1",
        "metadata": {
            "client_id": soeid,
            "soeid": soeid,
            "project_name": "test",
            "target_service": "test",
            "endpoint": "/test",
            "method": "POST",
            "status_code": 200,
            "latency_ms": 100.0,
            "request_size": 50,
            "response_size": 200
        }
    }
    
    try:
        resp = requests.post(f"{URL}/telemetry", headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ Telemetry logged: {result.get('status')}")
            return True
        else:
            print(f"❌ Telemetry error: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Telemetry error: {e}")
        return False

def main():
    soeid = sys.argv[1] if len(sys.argv) > 1 else "test_user"
    prompt = sys.argv[2] if len(sys.argv) > 2 else "Hello, how are you?"
    
    print(f"Testing dgen-ping with SOEID: {soeid}")
    print("=" * 40)
    
    # 1. Check service
    if not check_service():
        return
    
    # 2. Generate and verify token
    token = generate_token(soeid)
    if not token:
        print("Using default token")
        token = "1"
    else:
        verify_token(token)
    
    # 3. Test LLM completion
    test_llm(prompt, token, soeid)
    
    # 4. Test telemetry
    test_telemetry(token, soeid)
    
    print("✅ All tests completed")

if __name__ == "__main__":
    main()
