# syntax=docker/dockerfile:1
# RAG: тяжёлый образ из-за docling (PyTorch). Используем CPU-only PyTorch и многостадийную сборку.

# --- Stage 1: установка зависимостей ---
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc poppler-utils tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Docling тянет PyTorch; CPU-версия сильно меньше по размеру
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# --- Stage 2: минимальный образ для запуска ---
FROM python:3.11-slim AS runtime

WORKDIR /app

# docling/OpenCV: libGL для рендера PDF, libglib2.0-0 для libgthread; tesseract для OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 poppler-utils libgl1 libglib2.0-0 tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Только установленные пакеты (без gcc и build-зависимостей)
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
# Код приложения из контекста сборки
COPY . .

ENV PYTHONPATH=/app
EXPOSE 8020
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
