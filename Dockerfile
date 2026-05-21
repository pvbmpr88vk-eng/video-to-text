FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/output \
    && chown -R appuser:appuser /app

USER appuser

VOLUME ["/app/output"]

CMD ["python", "-m", "app", "bot"]
