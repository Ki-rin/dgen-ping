#!/usr/bin/env python
"""Test client for dgen-ping LLM proxy with JWT token support.

This script demonstrates how to make requests to the dgen-ping proxy service,
which uses JWT tokens for authentication and dgen_llm for content generation.
"""
import requests
import json
import time
import sys
import argparse
import os

DGEN_PING_URL = "http://127.0.0.1:8001"
DEFAULT_TOKEN = "1"  # Default token allowed by configuration
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "dgen_secret_key_change_in_production")

def check_service():
    """Check if the service is running."""
    try:
        # Check dgen-ping health
        ping_response = requests.get(f"{DGEN_PING_URL}/health")
        ping_status = ping_response.json()
        print(f"dgen-ping: {ping_status['status']}")
        
        # Show database status
        db_status = ping_status.get('database', {}).get('status', 'unknown')
        print(f"Database: {db_status}")
        
        if ping_status.get('database', {}).get('csv_fallback_active', False):
            print("📝 CSV fallback mode active")
        
        return True
    except Exception as e:
        print(f"Error connecting to service: {e}")
        print("\nMake sure the dgen-ping service is running first!")
        return False

def generate_jwt_token(soeid: str, project_id: str = "default"):
    """Generate a JWT token for the given user."""
    headers = {
        "X-Token-Secret": TOKEN_SECRET,
        "Content-Type": "application/json"
    }
    
    payload = {
        "soeid": soeid,
        "project_id": project_id
    }
    
    try:
        response = requests.post(
            f"{DGEN_PING_URL}/generate-token",
            headers=headers,
            json=payload
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n✅ JWT Token generated for {soeid}:")
            print(f"Token: {result['token'][:50]}...")
            print(f"Project: {result['project_id']}")
            print(f"Type: {result['type']}")
            return result['token']
        else:
            print(f"❌ Token generation failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Token generation error: {e}")
        return None

def verify_token(token: str):
    """Verify a JWT token."""
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
                print(f"✅ Token is valid")
                print(f"User: {result['data']['soeid']}")
                print(f"Project: {result['data']['project_id']}")
                return True
            else:
                print(f"❌ Token is invalid: {result['error']}")
                return False
        else:
            print(f"❌ Token verification failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Token verification error: {e}")
        return False

def make_llm_request(prompt, token=None, model="gpt-4", max_tokens=2000, temperature=0.7, soeid="test_user", project="test_project"):
    """Make an LLM request through the dgen-ping proxy."""
    # Use default token if none provided
    auth_token = token or DEFAULT_TOKEN
    
    headers = {
        "X-API-Token": auth_token,
        "Content-Type": "application/json"
    }
    
    payload = {
        "soeid": soeid,
        "project_name": project,
        "prompt": prompt,
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    
    print(f"\nSending request: \"{prompt}\"")
    if auth_token != DEFAULT_TOKEN:
        print(f"Using JWT token: {auth_token[:20]}...")
    else:
        print("Using default token")
    
    try:
        start_time = time.time()
        response = requests.post(
            f"{DGEN_PING_URL}/api/llm/completion",
            headers=headers,
            json=payload
        )
        
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            print("\n=== LLM Response ===")
            print(f"Completion: {result['completion']}")
            print("\n=== Metadata ===")
            print(f"Model: {result['model']}")
            print(f"Latency: {elapsed:.2f} seconds")
            
            if 'metadata' in result and 'tokens' in result['metadata']:
                tokens = result['metadata']['tokens']
                print(f"Tokens: {tokens.get('prompt', 0)} prompt, "
                      f"{tokens.get('completion', 0)} completion, "
                      f"{tokens.get('total', 0)} total")
            
            return result
        else:
            print(f"❌ Error: {response.status_code} - {response.text}")
            return None
    
    except Exception as e:
        print(f"❌ Request error: {e}")
        return None

def get_metrics(token=None):
    """Get metrics from dgen-ping."""
    auth_token = token or DEFAULT_TOKEN
    headers = {"X-API-Token": auth_token}
    
    try:
        response = requests.get(f"{DGEN_PING_URL}/metrics", headers=headers)
        
        if response.status_code == 200:
            metrics = response.json()
            print("\n=== dgen-ping Metrics ===")
            print(f"Total requests: {metrics.get('requests_total', 0)}")
            print(f"Requests last hour: {metrics.get('requests_last_hour', 0)}")
            print(f"Average latency (ms): {metrics.get('avg_latency_ms', 0):.2f}")
            print(f"Error rate: {metrics.get('error_rate', 0):.2%}")
            print(f"Total token usage: {metrics.get('token_usage_total', 0)}")
            print(f"Database status: {metrics.get('database_status', 'unknown')}")
            return metrics
        else:
            print(f"❌ Error getting metrics: {response.status_code} - {response.text}")
            return None
    
    except Exception as e:
        print(f"❌ Metrics error: {e}")
        return None

def get_service_info(token=None):
    """Get detailed service information."""
    auth_token = token or DEFAULT_TOKEN
    headers = {"X-API-Token": auth_token}
    
    try:
        response = requests.get(f"{DGEN_PING_URL}/info", headers=headers)
        
        if response.status_code == 200:
            info = response.json()
            print("\n=== Service Information ===")
            print(f"Service: {info.get('service', 'unknown')}")
            print(f"Version: {info.get('version', 'unknown')}")
            
            auth_info = info.get('authentication', {})
            print(f"Auth type: {auth_info.get('token_type', 'unknown')}")
            print(f"Project ID: {auth_info.get('project_id', 'unknown')}")
            print(f"User ID: {auth_info.get('user_id', 'unknown')}")
            
            db_info = info.get('database', {})
            print(f"Database: {db_info.get('status', 'unknown')}")
            
            perf_info = info.get('performance', {})
            print(f"Active requests: {perf_info.get('active_requests', 'unknown')}")
            print(f"Max concurrency: {perf_info.get('max_concurrency', 'unknown')}")
            
            return info
        else:
            print(f"❌ Error getting service info: {response.status_code} - {response.text}")
            return None
    
    except Exception as e:
        print(f"❌ Service info error: {e}")
        return None

def main():
    """Main function to run test requests."""
    parser = argparse.ArgumentParser(description="Test client for dgen-ping LLM proxy with JWT support")
    parser.add_argument("--prompt", "-p", help="Prompt to send to the LLM service")
    parser.add_argument("--metrics", "-m", action="store_true", help="Get metrics from the service")
    parser.add_argument("--info", "-i", action="store_true", help="Get service information")
    parser.add_argument("--generate-token", "-g", help="Generate JWT token for the given SOEID")
    parser.add_argument("--verify-token", "-v", help="Verify the given JWT token")
    parser.add_argument("--use-token", "-t", help="Use specific token for requests")
    parser.add_argument("--project", help="Project ID for token generation", default="test_project")
    parser.add_argument("--soeid", help="SOEID for requests", default="test_user")
    parser.add_argument("--url", help=f"Service URL (default: {DGEN_PING_URL})")
    args = parser.parse_args()
    
    global DGEN_PING_URL
    if args.url:
        DGEN_PING_URL = args.url
    
    print("=== dgen-ping Test Client (JWT Support) ===")
    print(f"Service URL: {DGEN_PING_URL}")
    
    if not check_service():
        return
    
    # Handle token generation
    if args.generate_token:
        token = generate_jwt_token(args.generate_token, args.project)
        if token:
            print(f"\n💡 You can now use this token with: --use-token {token}")
        return
    
    # Handle token verification
    if args.verify_token:
        verify_token(args.verify_token)
        return
    
    # Handle metrics request
    if args.metrics:
        get_metrics(args.use_token)
        return
    
    # Handle service info request
    if args.info:
        get_service_info(args.use_token)
        return
    
    # Handle specific prompt
    if args.prompt:
        make_llm_request(
            args.prompt, 
            token=args.use_token,
            soeid=args.soeid,
            project=args.project
        )
        return
    
    # Otherwise run example workflow
    print("\n=== JWT Token Demo ===")
    
    # Generate a token for testing
    test_token = generate_jwt_token(args.soeid, args.project)
    if test_token:
        # Verify the token
        print(f"\nVerifying generated token...")
        verify_token(test_token)
    
    # Run example prompts
    prompts = [
        "Explain how JWT tokens work.",
        "Write a haiku about secure authentication.",
        "What are the benefits of stateless authentication?"
    ]
    
    print("\n=== Testing with Default Token ===")
    for prompt in prompts[:1]:  # Just one with default token
        result = make_llm_request(prompt, soeid=args.soeid, project=args.project)
        if result:
            time.sleep(1)
    
    if test_token:
        print("\n=== Testing with JWT Token ===")
        for prompt in prompts[1:]:  # Rest with JWT token
            result = make_llm_request(
                prompt, 
                token=test_token,
                soeid=args.soeid,
                project=args.project
            )
            if result:
                time.sleep(1)
    
    # Get final metrics and info
    print("\n=== Final Status ===")
    get_metrics(args.use_token)
    get_service_info(args.use_token)

if __name__ == "__main__":
    main()
