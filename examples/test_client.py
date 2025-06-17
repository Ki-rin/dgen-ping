#!/usr/bin/env python
"""Test client for dgen-ping service."""
import requests
import sys

URL = "http://127.0.0.1:8001"
SECRET = "dgen_secret_key_change_in_production"

def check_service():
    """Check if service is running."""
    try:
        resp = requests.get(f"{URL}/health")
        print(f"Service: {resp.json()['status']}")
        return True
    except Exception as e:
        print(f"❌ Service not running: {e}")
        return False

def generate_token(soeid):
    """Generate JWT token for user."""
    headers = {"X-Token-Secret": SECRET, "Content-Type": "application/json"}
    payload = {"soeid": soeid}
    
    try:
        resp = requests.post(f"{URL}/generate-token", headers=headers, json=payload)
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ Token: {result['token'][:50]}...")
            return result['token']
        else:
            print(f"❌ Token generation failed: {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def verify_token(token):
    """Verify JWT token."""
    headers = {"X-Token-Secret": SECRET, "Content-Type": "application/json"}
    payload = {"token": token}
    
    try:
        resp = requests.post(f"{URL}/verify-token", headers=headers, json=payload)
        result = resp.json()
        if result['valid']:
            print(f"✅ Valid token for {result['data']['soeid']}")
            return True
        else:
            print(f"❌ Invalid: {result['error']}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_llm(prompt, token=None, soeid="test_user"):
    """Test LLM completion."""
    headers = {"X-API-Token": token or "1", "Content-Type": "application/json"}
    payload = {
        "soeid": soeid,
        "project_name": soeid,
        "prompt": prompt,
        "model": "gpt-4"
    }
    
    try:
        resp = requests.post(f"{URL}/api/llm/completion", headers=headers, json=payload)
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ Response: {result['completion'][:100]}...")
            return result
        else:
            print(f"❌ LLM error: {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_client.py <soeid> [prompt]")
        sys.exit(1)
    
    soeid = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else "Hello, how are you?"
    
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
