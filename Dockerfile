FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DB_PATH=/data/rss_notify.db \
    CONFIG_PATH=/data/config.json \
    FEED_TIMEOUT=30

VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "run.py"]
