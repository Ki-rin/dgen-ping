# dgen-ping

LLM proxy service with authentication and telemetry tracking.

## Features

- **JWT Authentication**: Token generation and validation using SOEID
- **LLM Completion**: Text generation with automatic telemetry logging
- **Resilient Database**: MongoDB with automatic CSV fallback
- **Auto-Telemetry**: Every LLM request automatically logged
- **Default Values**: Ready-to-test with sensible defaults

## Quick Start

```bash
# Start service
python examples/run.py

# Test all endpoints
python examples/test_client.py
```

Service runs at: http://127.0.0.1:8001
API docs at: http://127.0.0.1:8001/docs

## API Endpoints

### 1. Generate Token
**POST** `/generate-token`

Generate JWT token for user authentication.

```bash
curl -X POST http://localhost:8001/generate-token \
  -H "X-Token-Secret: dgen_secret_key" \
  -H "Content-Type: application/json" \
  -d '{"soeid": "default_user"}'
```

**Response:**
```json
{
  "token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "soeid": "default_user",
  "timestamp": "2025-01-01T12:00:00.000Z"
}
```

### 2. Verify Token
**POST** `/verify-token`

Validate JWT token and get user info.

```bash
curl -X POST http://localhost:8001/verify-token \
  -H "X-Token-Secret: dgen_secret_key" \
  -H "Content-Type: application/json" \
  -d '{"token": "1"}'
```

**Response:**
```json
{
  "valid": true,
  "data": {
    "soeid": "default_user"
  },
  "timestamp": "2025-01-01T12:00:00.000Z"
}
```

### 3. LLM Completion
**POST** `/api/llm/completion`

Generate text completion with automatic telemetry.

```bash
curl -X POST http://localhost:8001/api/llm/completion \
  -H "X-API-Token: 1" \
  -H "Content-Type: application/json" \
  -d '{
    "soeid": "default_user",
    "project_name": "default_project",
    "prompt": "Hello, how are you?",
    "model": "gemini",
    "temperature": 0.3,
    "max_tokens": 10000
  }'
```

**Response:**
```json
{
  "completion": "Hello! I'm doing well, thank you for asking...",
  "model": "gemini",
  "metadata": {
    "request_id": "uuid-here",
    "latency": 1.234,
    "tokens": {
      "prompt": 25,
      "completion": 45,
      "total": 70
    },
    "timestamp": "2025-01-01T12:00:00.000Z"
  }
}
```

### 4. Manual Telemetry
**POST** `/telemetry`

Log custom telemetry events.

```bash
curl -X POST http://localhost:8001/telemetry \
  -H "X-API-Token: 1" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "custom_event",
    "request_id": "test-123",
    "client_ip": "127.0.0.1",
    "metadata": {
      "client_id": "default_user",
      "soeid": "default_user",
      "project_name": "default_project",
      "target_service": "custom",
      "endpoint": "/custom",
      "method": "POST",
      "status_code": 200,
      "latency_ms": 100.0,
      "request_size": 50,
      "response_size": 200
    }
  }'
```

## Default Token Support

For easy testing, the service supports default authentication:

- **Token "1"**: Works as default token when `ALLOW_DEFAULT_TOKEN=true`
- **Missing token**: Falls back to default user
- **Default SOEID**: Uses "default_user" when not specified

## Configuration

Create `.env` file or set environment variables:

```bash
# Core Settings
DEBUG=true
TOKEN_SECRET=your_secret_key_here
ALLOW_DEFAULT_TOKEN=true

# Database
MONGO_URI=mongodb://your-server:27017/dgen_db
CSV_FALLBACK_DIR=telemetry_logs

# LLM Authentication
CLIENT_ID=your_client_id
CLIENT_SECRET=your_client_secret
SCOPE=your_scope

# LLM Service URLs
COIN_URL=https://your-coin-url
API_ENDPOINT=https://your-api-endpoint
SURL=https://your-service-url

# LLM Models
DEFAULT_MODEL=gemini
MODEL=your_model
SMODEL=your_secondary_model
SKEY=your_service_key
```

## Automatic Telemetry

Every LLM completion automatically logs:

- **Performance**: Request/response times, sizes
- **Usage**: Model, tokens, temperature settings
- **User Context**: SOEID, project name, request ID
- **System Info**: Client IP, endpoint, HTTP method

Telemetry is resilient:
- Tries MongoDB first
- Falls back to CSV if database unavailable
- Logs in background (non-blocking)
- Service continues working regardless of logging status

## Database Resilience

The service handles database issues gracefully:

1. **MongoDB Primary**: Tries main connection
2. **MongoDB Backup**: Falls back to backup URI
3. **CSV Fallback**: Saves to `telemetry_logs/telemetry.csv`
4. **Service Continuity**: LLM requests work regardless of DB status

## Testing

Run comprehensive tests:

```bash
# Test with defaults
python examples/test_client.py

# Test with custom user
python examples/test_client.py your_user "Custom prompt here"
```

Tests cover:
- Service health check
- Token generation and validation
- LLM completion with telemetry
- Manual telemetry logging

## Docker Deployment

```bash
# Build and run
docker build -t dgen-ping .
docker run -p 8001:8001 \
  -e TOKEN_SECRET=your_secret \
  -e MONGO_URI=your_mongodb_uri \
  dgen-ping
```

## Dependencies

```txt
fastapi
uvicorn[standard]
pydantic
PyJWT
pymongo
python-dotenv
dgen_llm
```

## Project Structure

```
dgen-ping/
├── main.py           # FastAPI app with 4 endpoints
├── auth.py           # JWT token management
├── db.py             # MongoDB + CSV fallback
├── proxy.py          # LLM service integration
├── config.py         # Environment configuration
├── models.py         # Pydantic data models
├── middleware.py     # Request tracking middleware
├── examples/
│   ├── run.py        # Service runner
│   ├── test_client.py # Test suite
│   └── .env          # Configuration template
├── requirements.txt  # Python dependencies
├── Dockerfile        # Container setup
└── README.md         # This file
```

## Development

1. **Install dependencies**: `pip install -r requirements.txt`
2. **Configure environment**: Copy `examples/.env` to project root
3. **Start service**: `python examples/run.py`
4. **Run tests**: `python examples/test_client.py`
5. **Check docs**: Visit http://127.0.0.1:8001/docs

The service is designed for simplicity and reliability, with sensible defaults that work out of the box.
