FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt playwright
RUN playwright install --with-deps chromium

COPY shared/ /app/shared/
COPY services/renderer/ /app/services/renderer/

ENV PYTHONPATH=/app
EXPOSE 8002

CMD ["uvicorn", "services.renderer.main:app", "--host", "0.0.0.0", "--port", "8002"]

