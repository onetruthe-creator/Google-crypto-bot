FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Data directory (mounted as a volume)
RUN mkdir -p /data/sovereign

ENV SOVEREIGN_DIR=/data/sovereign
ENV PYTHONUNBUFFERED=1
