# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
RUN pip install --no-cache-dir --prefix=/install uvicorn

FROM python:3.12-slim

RUN groupadd --gid 1000 appuser && useradd --uid 1000 --gid 1000 --create-home appuser
COPY --from=builder /install /usr/local
WORKDIR /app

COPY --chown=appuser:appuser . .

USER appuser

ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/healthz').status==200 else 1)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
