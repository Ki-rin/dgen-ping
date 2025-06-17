# dgen-ping

LLM proxy service with JWT authentication and resilient telemetry logging.

## Features

- **LLM Completion**: Text completion via `/api/llm/completion`
- **JWT Authentication**: Deterministic token generation based on SOEID
- **Resilient Logging**: MongoDB with automatic CSV fallback
- **Rate Limiting**: Configurable request limits
- **Health Monitoring**: Comprehensive health checks and metrics

## Quick Start

1. **Install and run**:
   ```bash
   python examples/run.py
   ```

2. **Generate token**:
   ```bash
   curl -X POST http://localhost:8001/generate-token \
     -H "X-Token-Secret: dgen_secret_key" \
     -H "Content-Type: application/json" \
     -d '{"soeid": "your_user_id"}'
   ```

3. **Make LLM request**:
   ```bash
   curl -X POST http://localhost:8001/api/llm/completion \
     -H "X-API-Token: YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "soeid": "your_user_id",
       "project_name": "test",
       "prompt": "Hello, how are you?"
     }'
   ```

## Configuration

Set environment variables in `.env`:

```bash
# Core settings
DEBUG=true
TOKEN_SECRET=your_secret_key
ALLOW_DEFAULT_TOKEN=true
HOST=0.0.0.0
PORT=8001

# Rate limiting
RATE_LIMIT=100
MAX_CONCURRENCY=50

# MongoDB (with fallbacks)
MONGO_URI=mongodb://primary-server:27017/db
MONGO_URI_BACKUP=mongodb://backup-server:27017/db
MONGO_URI_FALLBACK=mongodb://fallback-server:27017/db
DB_NAME=dgen_db

# CSV fallback
CSV_FALLBACK_DIR=telemetry_logs

# LLM settings
DEFAULT_MODEL=gemini
DEFAULT_MAX_TOKENS=10000
DEFAULT_TEMPERATURE=0.3
LLM_TIMEOUT=120
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/llm/completion` | POST | Process LLM requests |
| `/api/llm/chat` | POST | Alias for completion |
| `/generate-token` | POST | Create JWT token (requires secret) |
| `/generate-token-simple` | POST | Simple token generation |
| `/verify-token` | POST | Validate JWT token (requires secret) |
| `/telemetry` | POST | Log custom telemetry events |
| `/health` | GET | Service health check |
| `/metrics` | GET | System metrics |
| `/info` | GET | Service information |

## Authentication

### Generate Token
```bash
POST /generate-token
Headers: X-Token-Secret: <SECRET>
Body: {"soeid": "user123", "project_id": "optional"}
```

### Use Token
```bash
Headers: X-API-Token: <JWT_TOKEN>
```

### Default Token (Development)
Set `ALLOW_DEFAULT_TOKEN=true` to use token `"1"` for testing.

**Token Consistency**: Same SOEID always generates
