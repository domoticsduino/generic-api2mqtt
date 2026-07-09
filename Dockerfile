# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY main.py .
COPY http_utils.py .
COPY config.json .
COPY logging.json .
COPY providers/ ./providers/

# Default command
CMD ["python", "main.py"]
