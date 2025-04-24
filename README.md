# dgen-ping: LLM Proxy with Telemetry

High-performance LLM proxy service with integrated telemetry tracking for Citi's Generative AI systems.

## Overview

dgen-ping is a high-throughput, resilient proxy service that:

- Integrates directly with the dgen_llm package for LLM content generation
- Collects detailed telemetry data for each request
- Tracks token usage, request/response sizes, and latencies
- Handles high-concurrency with async processing
- Supports MongoDB storage with CSV fallback
- Provides simple authentication via API tokens

## Key Features

- **Direct LLM Integration**: Uses dgen_llm.llm_connection for content generation
- **High Performance**: Optimized for concurrent requests with async processing
- **Telemetry Collection**: Records detailed metrics about each request
- **Resilient**: Automatic retries and fallback mechanisms
- **Token Tracking**: Records prompt and completion token usage
- **Simple Authentication**: API tokens with default token option

## Requirements

- Python 3.9+
- dgen_llm package
- MongoDB (optional - falls back to CSV storage if unavailable)

## Installation

### Local Development

1. Clone the repository:

   ```bash
   git clone https://github.com/your-org/dgen-ping.git
   cd dgen-ping
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   pip install dgen_llm
   ```

3. Run the local development server:

   ```bash
   python run.py
   ```

4. Access the API at http://127.0.0.1:8001 and documentation at http://127.0.0.1:8001/docs

## Configuration

dgen-ping is configured via environment variables:

| Variable              | Description                         | Default          |
| --------------------- | ----------------------------------- | ---------------- |
| `MONGO_URI`           | MongoDB connection string           | `mongodb://...`  |
| `DB_NAME`             | MongoDB database name               | `dgen_db`        |
| `DEBUG`               | Enable debug mode                   | `false`          |
| `HOST`                | Host to bind service to             | `0.0.0.0`        |
| `PORT`                | Port to run service on              | `8001`           |
| `MAX_CONCURRENCY`     | Maximum concurrent requests         | `500`            |
| `RATE_LIMIT`          | Rate limit per minute               | `120`            |
| `WORKERS`             | Number of worker processes          | `4`              |
| `LLM_TIMEOUT`         | LLM request timeout in seconds      | `60`             |
| `RETRY_ATTEMPTS`      | Number of retry attempts            | `3`              |
| `ALLOW_DEFAULT_TOKEN` | Enable default token authentication | `true`           |
| `DEFAULT_MODEL`       | Default LLM model                   | `gpt-4`          |
| `DEFAULT_MAX_TOKENS`  | Default max response tokens         | `2000`           |
| `DEFAULT_TEMPERATURE` | Default LLM temperature             | `0.7`            |
| `CSV_FALLBACK_DIR`    | Directory for CSV fallback logs     | `telemetry_logs` |

See `.env.example` for a complete example configuration.

## API Endpoints

### LLM Endpoints

- **POST** `/api/llm/completion` - Submit an LLM completion request
- **POST** `/api/llm/chat` - Submit an LLM chat request

### System Endpoints

- **GET** `/health` - Health check endpoint
- **GET** `/info` - Service information and status
- **GET** `/metrics` - Performance metrics
- **POST** `/telemetry` - Direct telemetry logging

## Authentication

Use the `X-API-Token` header to authenticate requests:

```
X-API-Token: your-token-here
```

If `ALLOW_DEFAULT_TOKEN` is enabled, you can use the token value `1` for testing.

## Request Format

Send LLM requests with the following JSON structure:

```json
{
  "soeid": "ab1234",
  "project_name": "risk-analysis",
  "prompt": "Explain the concept of market volatility",
  "model": "gpt-4",
  "temperature": 0.7,
  "max_tokens": 2000
}
```

## Telemetry Data

Each request captures:

- Request ID and timestamp
- SOEID and project name
- Target service and endpoint
- HTTP method and status
- Request latency metrics
- LLM model and latency
- Token usage (prompt, completion, total)
- Request and response sizes

## Testing

To test the service, you can use the included test client:

```bash
# Run a quick test with example prompts
python test_client.py

# Test with a specific prompt
python test_client.py --prompt "Write a summary of recent market trends"

# Get current metrics
python test_client.py --metrics
```

## Implementation Details

The proxy service directly integrates with the `dgen_llm` package:

1. When a request is received, it calls `dgen_llm.llm_connection.generate_content(prompt)`
2. It captures telemetry data about the request and response
3. Telemetry is stored in MongoDB or falls back to CSV files
4. Detailed metrics are available via the API

## Project Structure

```
dgen-ping/
├── auth.py          # Authentication logic
├── config.py        # Configuration management
├── db.py            # Database operations with CSV fallback
├── main.py          # FastAPI application and routes
├── middleware.py    # Telemetry and rate limiting middleware
├── models.py        # Data models
├── proxy.py         # Direct dgen_llm integration
├── requirements.txt # Dependencies
├── run.py           # Local development script
└── test_client.py   # Testing utility
```

## License

Internal use only - Citi Proprietary
