#!/usr/bin/env python
"""Test client for dgen-ping LLM proxy.

This script demonstrates how to make requests to the dgen-ping proxy service,
which uses dgen_llm.llm_connection directly for content generation.
"""
import requests
import json
import time
import sys
import argparse

DGEN_PING_URL = "http://127.0.0.1:8001"
DEFAULT_TOKEN = "1"  # Default token allowed by configuration

def check_service():
    """Check if the service is running."""
    try:
        # Check dgen-ping
        ping_response = requests.get(f"{DGEN_PING_URL}/health")
        ping_status = ping_response.json()
        print(f"dgen-ping: {ping_status['status']}")
        
        if 'services' in ping_status:
            print(f"Service mode: {ping_status['services']}")
        
        return True
    except Exception as e:
        print(f"Error connecting to service: {e}")
        print("\nMake sure the dgen-ping service is running first!")
        return False

def make_llm_request(prompt, model="gpt-4", max_tokens=2000, temperature=0.7):
    """Make an LLM request through the dgen-ping proxy."""
    headers = {
        "X-API-Token": DEFAULT_TOKEN,
        "Content-Type": "application/json"
    }
    
    payload = {
        "soeid": "test_user",
        "project_name": "test_project",
        "prompt": prompt,
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    
    print(f"\nSending request: \"{prompt}\"")
    
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
            print(f"Error: {response.status_code} - {response.text}")
            return None
    
    except Exception as e:
        print(f"Request error: {e}")
        return None

def get_metrics():
    """Get metrics from dgen-ping."""
    headers = {"X-API-Token": DEFAULT_TOKEN}
    
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
            return metrics
        else:
            print(f"Error getting metrics: {response.status_code} - {response.text}")
            return None
    
    except Exception as e:
        print(f"Metrics error: {e}")
        return None

def main():
    """Main function to run test requests."""
    parser = argparse.ArgumentParser(description="Test client for dgen-ping LLM proxy")
    parser.add_argument("--prompt", "-p", help="Prompt to send to the LLM service")
    parser.add_argument("--metrics", "-m", action="store_true", help="Get metrics from the service")
    parser.add_argument("--url", help=f"Service URL (default: {DGEN_PING_URL})")
    args = parser.parse_args()
    
    global DGEN_PING_URL
    if args.url:
        DGEN_PING_URL = args.url
    
    print("=== dgen-ping Test Client ===")
    print(f"Service URL: {DGEN_PING_URL}")
    
    if not check_service():
        return
    
    if args.metrics:
        get_metrics()
        return
    
    # If prompt is provided, use it
    if args.prompt:
        make_llm_request(args.prompt)
        return
    
    # Otherwise run a few example prompts
    prompts = [
        "Explain how a proxy service works.",
        "Write a haiku about data telemetry.",
        "What are the benefits of capturing API metrics?"
    ]
    
    for prompt in prompts:
        result = make_llm_request(prompt)
        if result:
            # Small pause between requests
            time.sleep(1)
    
    # Get metrics after running some requests
    get_metrics()

if __name__ == "__main__":
    main()