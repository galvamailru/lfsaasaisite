# Микросервисы (Gallery, RAG)

Сервисы лежат в `saasaisite/services/` и поднимаются одним `docker-compose` из корня **saasaisite**:

```bash
cd saasaisite
docker compose up --build
```

- **app** — основное приложение (порт 8000)
- **gallery** — галерея изображений (порт 8010), схема БД `gallery`
- **rag** — документы PDF → markdown (порт 8020), схема БД `rag`. Первая сборка образа может занять 5–10 минут из‑за зависимостей docling/PyTorch; повторные сборки быстрее за счёт кэша.
- **db** — PostgreSQL (одна БД для всех, разные схемы)
- **mailpit** — SMTP для писем

Переменные для app: `GALLERY_SERVICE_URL=http://gallery:8010`, `RAG_SERVICE_URL=http://rag:8020` заданы в `docker-compose.yml`.
