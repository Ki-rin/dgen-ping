#!/usr/bin/env python
"""Simple demonstration of SOEID-only JWT token generation and usage."""
import requests
import json
import os
import sys

# Configuration
DGEN_PING_URL = "http://127.0.0.1:8001"
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "dgen_secret_key_change_in_production")

def generate_simple_token(soeid):
    """Generate a token using only SOEID."""
    print(f"🔧 Generating token for SOEID: {soeid}")
    
    headers = {
        "X-Token-Secret": TOKEN_SECRET,
        "Content-Type": "application/json"
    }
    
    payload = {"soeid": soeid}
    
    try:
        response = requests.post(
            f"{DGEN_PING_URL}/generate-token-simple",
            headers=headers,
            json=payload
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Token generated successfully!")
            print(f"   SOEID: {result['soeid']}")
            print(f"   Project ID: {result['project_id']} (same as SOEID)")
            print(f"   Token: {result['token'][:50]}...")
            return result['token']
        else:
            print(f"❌ Error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return None

def verify_token(token):
    """Verify a token."""
    print(f"\n🔍 Verifying token...")
    
    headers = {
        "X-Token-Secret": TOKEN_SECRET,
        "Content-Type": "application/json"
    }
    
    payload = {"token": token}
    
    try:
        response = requests.post(
            f"{DGEN_PING_URL}/verify-token",
            headers=headers,
            json=payload
        )
        
        if response.status_code == 200:
            result = response.json()
            if result['valid']:
                print(f"✅ Token is valid!")
                print(f"   SOEID: {result['data']['soeid']}")
                print(f"   Project ID: {result['data']['project_id']}")
                return True
            else:
                print(f"❌ Token is invalid: {result['error']}")
                return False
        else:
            print(f"❌ Verification failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Verification error: {e}")
        return False

def make_llm_request(token, soeid):
    """Make an LLM request using the token."""
    print(f"\n🚀 Making LLM request with token...")
    
    headers = {
        "X-API-Token": token,
        "Content-Type": "application/json"
    }
    
    payload = {
        "soeid": soeid,
        "project_name": soeid,  # Use soeid as project name
        "prompt": f"Hello, this is a test request from user {soeid}",
        "model": "gpt-4",
        "max_tokens": 100,
        "temperature": 0.7
    }
    
    try:
        response = requests.post(
            f"{DGEN_PING_URL}/api/llm/completion",
            headers=headers,
            json=payload
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ LLM request successful!")
            print(f"   Response: {result['completion'][:100]}...")
            print(f"   Model: {result['model']}")
            return True
        else:
            print(f"❌ LLM request failed: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ LLM request error: {e}")
        return False

def check_service():
    """Check if the service is running."""
    try:
        response = requests.get(f"{DGEN_PING_URL}/health")
        if response.status_code == 200:
            health = response.json()
            print(f"✅ Service is running: {health['status']}")
            return True
        else:
            print(f"❌ Service health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Cannot connect to service: {e}")
        print(f"   Make sure the service is running at {DGEN_PING_URL}")
        return False

def main():
    """Main demonstration."""
    if len(sys.argv) > 1:
        soeid = sys.argv[1]
    else:
        soeid = input("Enter your SOEID: ").strip()
    
    if not soeid:
        print("❌ SOEID is required")
        return
    
    print("🎯 SOEID-only JWT Token Demo")
    print("=" * 40)
    print(f"Service: {DGEN_PING_URL}")
    print(f"SOEID: {soeid}")
    print()
    
    # Check service
    if not check_service():
        return
    
    # Generate token
    token = generate_simple_token(soeid)
    if not token:
        return
    
    # Verify token
    if not verify_token(token):
        return
    
    # Make LLM request
    make_llm_request(token, soeid)
    
    print(f"\n🎉 Demo completed successfully!")
    print(f"💡 Your token: {token}")
    print(f"💡 Use it in API calls with header: X-API-Token: {token}")

if __name__ == "__main__":
    main()
