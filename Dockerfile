FROM python:3.11-slim

WORKDIR /app

# Install dependencies 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directory for CSV fallback
RUN mkdir -p telemetry_logs && chmod 777 telemetry_logs

# Set environment variables
ENV DEBUG=false \
    HOST=0.0.0.0 \
    PORT=8001 \
    ALLOW_DEFAULT_TOKEN=true

# Expose port
EXPOSE 8001

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]