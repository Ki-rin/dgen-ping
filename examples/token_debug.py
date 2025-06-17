#!/usr/bin/env python
"""Debug JWT token issues and test token generation/verification."""
import jwt
import json
import base64
import os
import sys
from datetime import datetime, timezone

# Use the same secret as the application
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "dgen_secret_key_change_in_production")

def analyze_token(token_str):
    """Analyze a JWT token for encoding and format issues."""
    print(f"🔍 Analyzing token: {token_str[:50]}...")
    
    # Check basic format
    parts = token_str.split('.')
    if len(parts) != 3:
        print(f"❌ Invalid JWT format: expected 3 parts, got {len(parts)}")
        return False
    
    print(f"✅ JWT format: {len(parts)} parts")
    
    # Check encoding of each part
    for i, part in enumerate(parts):
        part_name = ["Header", "Payload", "Signature"][i]
        print(f"\n📋 {part_name}: {part[:30]}...")
        
        # Check for invalid characters
        import re
        if not re.match(r'^[A-Za-z0-9_-]*$', part):
            print(f"❌ {part_name} contains invalid characters")
            invalid_chars = [c for c in part if not re.match(r'[A-Za-z0-9_-]', c)]
            print(f"   Invalid characters: {set(invalid_chars)}")
            return False
        
        # Try to decode (header and payload only)
        if i < 2:
            try:
                # Add padding if needed
                padded = part + '=' * (4 - len(part) % 4)
                decoded = base64.urlsafe_b64decode(padded)
                data = json.loads(decoded)
                print(f"✅ {part_name} decoded successfully:")
                print(f"   {json.dumps(data, indent=2)}")
            except Exception as e:
                print(f"❌ {part_name} decode error: {e}")
                return False
    
    return True

def test_token_generation(soeid="test_user", project_id=None):
    """Test token generation with SOEID only."""
    print(f"\n🔧 Generating token for SOEID: {soeid}")
    if project_id:
        print(f"   Project ID: {project_id}")
    else:
        print(f"   Project ID: {soeid} (defaults to SOEID)")
    
    try:
        # Use soeid as project_id if not provided
        actual_project_id = project_id if project_id else soeid
        
        payload = {
            "soeid": soeid,
            "project_id": actual_project_id,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "jti": "test-token-id"
        }
        
        print(f"📝 Payload: {json.dumps(payload, indent=2)}")
        
        # Generate token
        token = jwt.encode(payload, TOKEN_SECRET, algorithm="HS256")
        
        # Ensure it's a string
        if isinstance(token, bytes):
            token = token.decode('utf-8')
        
        print(f"✅ Token generated: {token}")
        
        # Analyze the generated token
        analyze_token(token)
        
        return token
        
    except Exception as e:
        print(f"❌ Token generation failed: {e}")
        return None

def test_token_verification(token_str):
    """Test token verification."""
    print(f"\n🔐 Verifying token...")
    
    try:
        # Decode token
        payload = jwt.decode(token_str, TOKEN_SECRET, algorithms=["HS256"])
        print(f"✅ Token verified successfully:")
        print(f"   {json.dumps(payload, indent=2, default=str)}")
        return True
        
    except jwt.ExpiredSignatureError:
        print(f"❌ Token expired")
        return False
    except jwt.InvalidTokenError as e:
        print(f"❌ Invalid token: {e}")
        return False
    except Exception as e:
        print(f"❌ Verification error: {e}")
        return False

def clean_token(token_str):
    """Clean a token string of common issues."""
    print(f"\n🧹 Cleaning token...")
    
    original = token_str
    
    # Strip whitespace
    token_str = token_str.strip()
    
    # Remove common prefixes
    if token_str.startswith('Bearer '):
        token_str = token_str[7:]
    
    # URL decode if needed
    try:
        import urllib.parse
        decoded = urllib.parse.unquote(token_str)
        if decoded != token_str:
            print(f"📝 URL decoded: {decoded[:50]}...")
            token_str = decoded
    except:
        pass
    
    # Check for encoding issues
    try:
        # Try to encode/decode to catch encoding issues
        token_str.encode('utf-8').decode('utf-8')
    except UnicodeError as e:
        print(f"❌ Encoding issue: {e}")
        return None
    
    if token_str != original:
        print(f"🔄 Cleaned token: {token_str[:50]}...")
    else:
        print(f"✅ Token already clean")
    
    return token_str

def main():
    """Main debugging function."""
    print("🔍 JWT Token Debugging Tool")
    print("=" * 40)
    
    if len(sys.argv) > 1:
        # Token provided as argument
        input_token = sys.argv[1]
        print(f"📥 Input token: {input_token[:50]}...")
        
        # Clean the token
        cleaned_token = clean_token(input_token)
        if not cleaned_token:
            print("❌ Could not clean token")
            return
        
        # Analyze token structure
        if analyze_token(cleaned_token):
            # Test verification
            test_token_verification(cleaned_token)
    else:
        # Generate and test a new token
        print("📝 No token provided, generating test token...")
        test_token = test_token_generation()
        
        if test_token:
            print(f"\n🧪 Testing verification of generated token...")
            test_token_verification(test_token)
    
    print(f"\n🔧 Configuration:")
    print(f"   TOKEN_SECRET: {TOKEN_SECRET[:10]}...")
    print(f"   Algorithm: HS256")

if __name__ == "__main__":
    main()
