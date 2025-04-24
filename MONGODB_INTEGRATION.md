# MongoDB Integration for dgen-ping

This document describes how dgen-ping integrates with MongoDB to record telemetry data, connection logs, and LLM run history.

## Overview

dgen-ping uses MongoDB as its primary storage backend for all telemetry and logging data. The service is designed to automatically create the necessary database, collections, and indexes if they don't already exist.

If MongoDB is unavailable, the service will automatically fall back to CSV-based storage to ensure no telemetry data is lost.

## Database Schema

The MongoDB database contains the following collections:

### `telemetry`

Stores detailed telemetry about all API requests and responses.

**Key fields:**

- `event_type`: Type of event (e.g., "llm_request", "direct_request")
- `timestamp`: When the event occurred
- `request_id`: Unique identifier for the request
- `client_ip`: Client IP address
- `metadata`: Detailed information about the request and response
  - `client_id`: Client identifier
  - `soeid`: User SOEID
  - `project_name`: Project name
  - `target_service`: Target service
  - `endpoint`: API endpoint
  - `method`: HTTP method
  - `status_code`: HTTP status code
  - `latency_ms`: Request latency in milliseconds
  - `request_size`: Request size in bytes
  - `response_size`: Response size in bytes
  - `prompt_tokens`: Number of prompt tokens
  - `completion_tokens`: Number of completion tokens
  - `total_tokens`: Total number of tokens
  - `llm_model`: LLM model name
  - `llm_latency`: LLM processing latency

### `llm_runs`

Stores full details of LLM generation requests and responses, including prompts and completions.

**Key fields:**

- `request_id`: Unique identifier for the request
- `timestamp`: When the run occurred
- `soeid`: User SOEID
- `project_name`: Project name
- `prompt`: The actual prompt text sent to the LLM
- `completion`: The generated completion text
- `model`: LLM model used
- `temperature`: Temperature setting
- `max_tokens`: Max tokens setting
- `prompt_tokens`: Number of prompt tokens
- `completion_tokens`: Number of completion tokens
- `total_tokens`: Total number of tokens
- `latency_ms`: Processing latency

### `connection_logs`

Tracks database connections, application startup/shutdown events, and other system events.

**Key fields:**

- `timestamp`: When the event occurred
- `event_type`: Type of event (e.g., "database_connected", "application_startup")
- `status`: Success or error
- `message`: Descriptive message
- `metadata`: Additional contextual information

### `metrics`

Stores aggregated metrics calculated periodically for dashboard display.

**Key fields:**

- `timestamp`: When the metrics were calculated
- `metric_type`: Type of metric (e.g., "hourly")
- `metrics`: Object containing calculated metric values

### `api_tokens`

Stores API authentication tokens.

### `projects`

Stores project configuration information.

## Automatic Collection Creation

When dgen-ping starts up, it:

1. Attempts to connect to MongoDB using the connection string from settings
2. Checks if the required collections exist
3. Creates any missing collections with appropriate schema validation
4. Creates indexes on all collections for optimal query performance

## CSV Fallback

If MongoDB is unavailable, dgen-ping will:

1. Log a warning about the connection failure
2. Switch to CSV-based storage in the directory specified by `CSV_FALLBACK_DIR`
3. Create CSV files with telemetry data using the naming pattern `telemetry_YYYY-MM-DD.csv`
4. Continue attempting to reconnect to MongoDB periodically

## API Endpoints for MongoDB Data

dgen-ping provides several endpoints for accessing the data stored in MongoDB:

- **GET** `/metrics` - Get aggregated service metrics
- **GET** `/llm-history` - Get historical LLM runs with filtering options
- **GET** `/db-status` - Get database connection status and information

## Schema Validation

MongoDB schema validation is used to ensure data integrity. The validation schemas are defined in `db.py` in the `_get_telemetry_schema_validator()` and `_get_llm_runs_schema_validator()` methods.

## Telemetry Collection Process

1. When an LLM request is processed:

   - A telemetry event is recorded in the `telemetry` collection
   - The complete request and response are recorded in the `llm_runs` collection
   - Token usage and latency metrics are captured

2. When the application starts or shuts down:

   - A connection event is recorded in the `connection_logs` collection
   - System information and environment details are captured

3. Metrics are calculated periodically and stored in the `metrics` collection

## Indexes

Indexes are created on all collections to optimize common query patterns:

- Timestamp-based queries for time-series analysis
- SOEID and project-based queries for user activity tracking
- Status code queries for error analysis
- Token usage queries for billing and quota management

## Configuration

MongoDB connection settings are configured via environment variables:

```
MONGO_URI=mongodb://username:password@hostname:port/
DB_NAME=dgen_db
```

These can be set in the `.env` file or passed as environment variables.
