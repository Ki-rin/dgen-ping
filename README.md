# dgen-ping

LLM proxy service with authentication and telemetry tracking.

## Features

- **LLM Completion**: Process text completion requests via `/api/llm/completion`
- **JWT Authentication**: Secure token-based access control
- **Telemetry Logging**: Track usage with MongoDB or CSV fallback
- **Resilient Database**: Multiple MongoDB URIs with automatic CSV fallback

## Quick Start

1. **Install and run**:
   ```bash
   python examples/run.py
   ```

2. **Generate token**:
   ```bash
   curl -X POST http://localhost:8001/generate-token \
     -H "X-Token-Secret: secret_key_for_usage_tracking_token_generation" \
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

# MongoDB (with fallbacks)
MONGO_URI=mongodb://primary-server:27017/db
MONGO_URI_BACKUP=mongodb://backup-server:27017/db
MONGO_URI_FALLBACK=mongodb://fallback-server:27017/db
DB_NAME=dgen_db
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/llm/completion` | POST | Process LLM requests |
| `/generate-token` | POST | Create JWT token (requires secret) |
| `/verify-token` | POST | Validate JWT token (requires secret) |
| `/telemetry` | POST | Log custom telemetry events |
| `/health` | GET | Service health check |

## Authentication

### Generate Token
```bash
POST /generate-token
Headers: X-Token-Secret: <SECRET>
Body: {"soeid": "user123"}
```

### Use Token
```bash
Headers: X-API-Token: <JWT_TOKEN>
```

### Default Token (Development)
Set `ALLOW_DEFAULT_TOKEN=true` to use token `"1"` for testing.

## Database Resilience

The service automatically:
1. Tries multiple MongoDB URIs in order
2. Falls back to CSV logging if all MongoDB connections fail
3. Switches to CSV if MongoDB drops during operation
4. Saves telemetry to `telemetry_logs/telemetry.csv`

## Testing

```bash
# Test with specific user
python examples/test_client.py user123 "Hello world"

# Check service status
curl http://localhost:8001/health
```

## Dependencies

- FastAPI + Uvicorn
- PyJWT for authentication  
- PyMongo for database (optional)
- dgen_llm for LLM integration

## Files

- `main.py` - Core service
- `auth.py` - JWT authentication
- `db.py` - Database with CSV fallback
- `models.py` - Data models
- `proxy.py` - LLM integration
- `config.py` - Settings
- `examples/` - Setup and test scripts
