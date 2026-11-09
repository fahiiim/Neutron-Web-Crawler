FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared library and service code
COPY shared/ /app/shared/
COPY services/gateway/ /app/services/gateway/

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "services.gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]

