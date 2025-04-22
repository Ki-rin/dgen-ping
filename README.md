# dgen-ping

API proxy service with integrated telemetry tracking for DGEN.

## Overview

dgen-ping is a lightweight proxy service that:

- Routes API requests to downstream services
- Collects detailed telemetry data on each request
- Supports MongoDB storage with CSV fallback
- Provides simple authentication via API tokens

## Key Features

- **Proxy Service**: Routes requests to classifier and enhancer services
- **Telemetry Collection**: Records detailed metrics about each request
- **Fallback Mechanism**: Uses CSV logging when MongoDB is unavailable
- **Simple Authentication**: Supports API tokens with default token option
- **Rate Limiting**: Optional rate limiting for production deployments

## Requirements

- Python 3.9+
- MongoDB (optional - falls back to CSV storage if unavailable)
- Access to downstream services

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

| Variable              | Description                           | Default                       |
| --------------------- | ------------------------------------- | ----------------------------- |
| `MONGO_URI`           | MongoDB connection string             | `mongodb://admin_mongodb:...` |
| `DB_NAME`             | MongoDB database name                 | `dgen_db`                     |
| `DEBUG`               | Enable debug mode                     | `false`                       |
| `HOST`                | Host to bind service to               | `0.0.0.0`                     |
| `PORT`                | Port to run service on                | `8001`                        |
| `DOWNSTREAM_SERVICES` | JSON mapping of service names to URLs | See .env.example              |
| `ALLOW_DEFAULT_TOKEN` | Enable default token authentication   | `true`                        |
| `CSV_FALLBACK_DIR`    | Directory for CSV fallback logs       | `telemetry_logs`              |

See `.env.example` for a complete example configuration.

## API Endpoints

### Proxy Endpoints

- **POST** `/api/classifier/{path}` - Route request to classifier service
- **POST** `/api/enhancer/{path}` - Route request to enhancer service

### System Endpoints

- **GET** `/health` - Health check endpoint
- **GET** `/info` - Service information
- **POST** `/telemetry` - Direct telemetry logging

## Authentication

Use the `X-API-Token` header to authenticate requests:

```
X-API-Token: your-token-here
```

If `ALLOW_DEFAULT_TOKEN` is enabled, you can use the token value `1` for testing.

## Telemetry Data

Each request captures:

- Timestamp
- Client ID and IP
- Target service and endpoint
- HTTP method and status
- Latency metrics
- LLM model and latency (when available)
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
├── proxy.py         # Proxy service implementation
├── requirements.txt # Dependencies
└── run_local.py     # Local development script
```

### Running Tests

```bash
pytest
```

## License

Internal use only - Citi Proprietary
