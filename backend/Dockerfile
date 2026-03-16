FROM python:3.11.3-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y gcc libpq-dev libgomp1 curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p models/ml/artifacts && \
    chmod +x /app/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
  CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["/app/entrypoint.sh"]
