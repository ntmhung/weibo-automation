FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget unzip \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpangocairo-1.0-0 libpango-1.0-0 libcairo2 libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app /app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir fastapi uvicorn playwright \
    && python -m playwright install chromium \
    && mkdir -p /data

ENV PYTHONUNBUFFERED=1
EXPOSE 3001

CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "3001"]