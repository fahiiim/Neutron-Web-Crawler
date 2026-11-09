FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/
COPY services/crawler/ /app/services/crawler/

ENV PYTHONPATH=/app
EXPOSE 8001

CMD ["uvicorn", "services.crawler.main:app", "--host", "0.0.0.0", "--port", "8001"]

