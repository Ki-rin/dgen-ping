# dgen-ping: LLM Proxy with Telemetry

High-performance LLM proxy service with integrated telemetry tracking for Citi's Generative AI systems.

## Overview

dgen-ping is a high-throughput, resilient proxy service that:

- Routes LLM requests to downstream AI services
- Collects detailed telemetry data for each request
- Tracks token usage, request/response sizes, and latencies
- Handles high-concurrency with connection pooling
- Supports MongoDB storage with CSV fallback
- Provides simple authentication via API tokens

## Key Features

- **LLM Proxy**: Routes completion/chat requests to LLM services
- **High Performance**: Optimized for concurrent requests with connection pooling
- **Telemetry Collection**: Records detailed metrics about each request
- **Resilient**: Automatic retries and fallback mechanisms
- **Token Tracking**: Records prompt and completion token usage
- **Simple Authentication**: API tokens with default token option

## Requirements

- Python 3.9+
- MongoDB (optional - falls back to CSV storage if unavailable)
- Access to downstream LLM services

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
   ```

3. Run the local development server:

   ```bash
   python run_local.py
   ```

4. Access the API at http://127.0.0.1:8001 and documentation at http://127.0.0.1:8001/docs

### Docker Deployment

1. Build the Docker image:

   ```bash
   docker build -t dgen-ping .
   ```

2. Run the container:
   ```bash
   docker run -p 8001:8001 dgen-ping
   ```

## Configuration

dgen-ping is configured via environment variables:

| Variable              | Description                           | Default          |
| --------------------- | ------------------------------------- | ---------------- |
| `MONGO_URI`           | MongoDB connection string             | `mongodb://...`  |
| `DB_NAME`             | MongoDB database name                 | `dgen_db`        |
| `DEBUG`               | Enable debug mode                     | `false`          |
| `HOST`                | Host to bind service to               | `0.0.0.0`        |
| `PORT`                | Port to run service on                | `8001`           |
| `MAX_CONCURRENCY`     | Maximum concurrent requests           | `500`            |
| `RATE_LIMIT`          | Rate limit per minute                 | `120`            |
| `WORKERS`             | Number of worker processes            | `4`              |
| `LLM_TIMEOUT`         | LLM request timeout in seconds        | `60`             |
| `RETRY_ATTEMPTS`      | Number of retry attempts              | `3`              |
| `DOWNSTREAM_SERVICES` | JSON mapping of service names to URLs | See .env.example |
| `ALLOW_DEFAULT_TOKEN` | Enable default token authentication   | `true`           |
| `DEFAULT_MODEL`       | Default LLM model                     | `gpt-4`          |
| `DEFAULT_MAX_TOKENS`  | Default max response tokens           | `2000`           |
| `DEFAULT_TEMPERATURE` | Default LLM temperature               | `0.7`            |
| `CSV_FALLBACK_DIR`    | Directory for CSV fallback logs       | `telemetry_logs` |

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

## Development

### Project Structure

```
dgen-ping/
├── auth.py          # Authentication logic
├── config.py        # Configuration management
├── db.py            # Database operations with CSV fallback
├── main.py          # FastAPI application and routes
├── middleware.py    # Telemetry and rate limiting middleware
├── models.py        # Data models
├── proxy.py         # LLM proxy service implementation
├── requirements.txt # Dependencies
└── run_local.py     # Local development script
```

## License

Internal use only - Citi Proprietary
