# dgen-ping

Minimal LLM proxy with JWT authentication and resilient telemetry logging.

## Core Features

- **JWT Authentication**: Generate/verify tokens with SOEID + secret
- **LLM Completion**: Text generation with automatic telemetry
- **Resilient Logging**: MongoDB with CSV fallback when DB unavailable
- **Simple API**: 4 endpoints covering essential functionality

## Quick Start

```bash
# Run service
python examples/run.py

# Test all functions
python examples/test_client.py
```

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /generate-token` | Create JWT token |
| `POST /verify-token` | Validate JWT token |
| `POST /api/llm/completion` | LLM text completion |
| `POST /telemetry` | Log custom events |

## Usage Examples

### 1. Generate Token
```bash
curl -X POST http://localhost:8001/generate-token \
  -H "X-Token-Secret: dgen_secret_key" \
  -H "Content-Type: application/json" \
  -d '{"soeid": "user123"}'
```

### 2. LLM Completion
```bash
curl -X POST http://localhost:8001/api/llm/completion \
  -H "X-API-Token: YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "soeid": "user123",
    "project_name": "test",
    "prompt": "Hello, how are you?"
  }'
```

## Configuration

Set in `.env`:
```bash
TOKEN_SECRET=your_secret_key
MONGO_URI=mongodb://your-server:27017/db
DEBUG=true
```

## Database Resilience

- Tries MongoDB first
- Automatically falls back to CSV if MongoDB fails
- Logs saved to `telemetry_logs/telemetry.csv`
- Service continues working regardless of DB status

## Files

- `main.py` - Core service (4 endpoints)
- `auth.py` - JWT token management
- `db.py` - MongoDB + CSV fallback
- `proxy.py` - LLM integration
- `examples/test_client.py` - Complete test suite

## Dependencies

```
fastapi
uvicorn[standard]
pydantic
PyJWT
pymongo
dgen_llm
```

## Docker

```bash
docker build -t dgen-ping .
docker run -p 8001:8001 dgen-ping
```
