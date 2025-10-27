FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for surnames.db download
RUN mkdir -p data

# Expose port
EXPOSE 8000

# Run the application with Hypercorn for WebSocket support
CMD ["hypercorn", "server:app", "--bind", "0.0.0.0:8000", "--websocket-ping-interval", "20"]
