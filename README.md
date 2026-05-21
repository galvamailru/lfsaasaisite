# CIP Backend (lfsaasaisite)

Форк [saasaisite](../saasaisite) с **LangFuse**: трассировка вызовов DeepSeek и MCP-серверов. Подробная инструкция по observability — [LANGFUSE.md](LANGFUSE.md).

Backend многопользовательской SaaS-платформы диалогового веб-сайта с AI-агентом (CIP): чат (REST + SSE), кабинет (диалоги, промпт чанками, вставка чата на сайт, админ-чат, профиль). Регистрация с подтверждением по e-mail. Архитектура допускает расширение (галерея, RAG, MCP) без переделки ядра — см. [ARCHITECTURE.md](ARCHITECTURE.md).

## Стек

- Python 3.11+
- FastAPI, PostgreSQL (asyncpg), Alembic
- LLM: DeepSeek (HTTP API, стриминг)
- Docker, docker-compose

## Быстрый старт

1. Скопировать `.env.example` в `.env` и задать переменные: пароли БД (`POSTGRES_*`), SMTP (в Docker — Mailpit), `DEEPSEEK_API_KEY`.
2. Запуск через Docker Compose (приложение + LangFuse на порту 3000):

```bash
docker compose up -d
# Дождаться готовности БД и LangFuse (2–5 мин), затем при первом запуске:
docker compose run --rm app alembic upgrade head
```

Приложение: `http://localhost:8000`. LangFuse UI: `http://localhost:3000` — см. [LANGFUSE.md](LANGFUSE.md).  

**Письма подтверждения регистрации в Docker не уходят на реальную почту** — они попадают в контейнер Mailpit. Откройте **http://localhost:8025** в браузере, чтобы увидеть все отправленные письма и ссылки для подтверждения.

3. Локально (без Docker):

```bash
pip install -r requirements.txt
# PostgreSQL должен быть запущен, DATABASE_URL в .env
alembic upgrade head
python run.py
```

## Запуск под Windows (локально)

1. **Установить:**
   - [Python 3.11+](https://www.python.org/downloads/) (при установке включите «Add Python to PATH»).
   - [PostgreSQL](https://www.postgresql.org/download/windows/) или использовать только БД из Docker (см. ниже).

2. **Открыть терминал** (PowerShell или cmd) в папке проекта:
   ```powershell
   cd C:\путь\к\saasaisite
   ```

3. **Создать виртуальное окружение** (рекомендуется):
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```

4. **Установить зависимости:**
   ```powershell
   pip install -r requirements.txt
   ```

5. **Настроить окружение:**
   - Скопировать `.env.example` в `.env`:  
     `copy .env.example .env`
   - В `.env` задать:
     - `DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/cip` — учётные данные вашей PostgreSQL (пользователь, пароль, база `cip`).
     - `DEEPSEEK_API_KEY=sk-...` — ключ API DeepSeek.
     - При необходимости: `MINIO_ENDPOINT=localhost:9000`, `MINIO_ACCESS_KEY=minioadmin`, `MINIO_SECRET_KEY=minioadmin` (если MinIO запущен отдельно для загрузки файлов).

6. **Поднять БД и миграции:**
   - Вариант А — PostgreSQL установлен локально: создать базу `cip`, затем:
     ```powershell
     alembic upgrade head
     ```
   - Вариант Б — только БД в Docker:
     ```powershell
     docker-compose up -d db
     # Подождать 5–10 сек, затем:
     set DATABASE_URL=postgresql+asyncpg://cip:cip@localhost:5432/cip
     alembic upgrade head
     ```
     В `.env` указать `DATABASE_URL=postgresql+asyncpg://cip:cip@localhost:5432/cip`.

7. **Запустить приложение:**
   ```powershell
   python run.py
   ```
   Или с автоперезагрузкой при изменении кода:
   ```powershell
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

8. **Открыть в браузере:** [http://localhost:8000](http://localhost:8000).  
   Демо-тенант с slug `demo` создаётся миграцией 002: чат — [http://localhost:8000/demo/chat](http://localhost:8000/demo/chat), кабинет — [http://localhost:8000/demo/my](http://localhost:8000/demo/my).

**MinIO (файлы в кабинете):** если нужна загрузка файлов, запустите MinIO отдельно, например:
```powershell
docker run -d -p 9000:9000 -p 9001:9001 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin minio/minio server /data
```
В `.env` задать `MINIO_ENDPOINT=localhost:9000`, `MINIO_ACCESS_KEY=minioadmin`, `MINIO_SECRET_KEY=minioadmin`, `MINIO_BUCKET=cip-files`, `MINIO_SECURE=false`.

## Маршруты

- **Чат:** `POST /api/v1/tenants/{tenant_id}/chat` — тело: `{ "user_id", "message", "dialog_id?" }` → SSE.  
  `POST .../chat/message` — то же, ответ одним JSON: `{ "reply": "..." }`.  
  **Telegram:** только через webhook — `POST .../telegram/webhook` (см. [TELEGRAM.md](TELEGRAM.md)).
- **Кабинет (JWT):**  
  - `GET /api/v1/tenants/by-slug/{slug}` — тенант по slug.  
  - `GET /api/v1/tenants/{tenant_id}/me/dialogs`, `GET .../me/dialogs/{dialog_id}` — диалоги.  
  - `GET/POST/PATCH/DELETE /api/v1/tenants/{tenant_id}/me/prompt/chunks` — чанки промпта (до 500 символов).  
  - `GET /api/v1/tenants/{tenant_id}/me/embed` — URL и код iframe для вставки чата на сайт.  
  - `GET/POST/DELETE .../me/saved`, `GET/PATCH .../me/profile` — сохранённое, профиль.  
  - `POST .../admin/chat` — админ-чат.
- **Регистрация и вход:**  
  - `POST /api/v1/tenants/{tenant_id}/register` — регистрация (email, пароль); отправляется письмо с ссылкой подтверждения.  
  - `GET /api/v1/tenants/by-slug/{slug}/confirm?token=...` — подтверждение email по ссылке из письма.  
  - `POST /api/v1/tenants/{tenant_id}/login` — вход (email, пароль) → JWT.
- **Статика:**  
  - `/{slug}/chat`, `/{slug}/chat/embed` — чат и чат для iframe.  
  - `/{slug}/my`, `/{slug}/my/...` — кабинет.  
  - `/{slug}/register`, `/{slug}/login`, `/{slug}/confirm?token=...` — регистрация, вход, подтверждение email.

## EXECUTE: управление командами через промпт

И админ-бот, и пользовательский чат-бот работают по одному принципу: **модель в ответе может вставлять блоки `[EXECUTE]...[/EXECUTE]`**. Сервер парсит эти блоки, выполняет команды (локально или вызовом микросервисов) и подставляет результат в ответ пользователю. Управление поведением — через **промпт**: в нём описывается, когда и какие команды выводить.

### Формат блока

```
[EXECUTE]
КОМАНДА
аргумент_1
ключ=значение
[/EXECUTE]
```

- Первая строка внутри блока — имя команды (например `ADD_CHUNK`, `LIST_GALLERIES`).
- Далее — аргументы: по одной строке, либо в виде `ключ=значение`. Пробелы в начале/конце обрезаются.

### Админ-бот (кабинет)

Промпт админ-бота задаётся в `prompts/admin_chat_prompt.txt` (и при необходимости чанками из БД). Бот помогает заполнять **промпт пользовательского чата** чанками: задаёт уточняющие вопросы, по ответам формулирует инструкции и **сам добавляет в конец ответа блок [EXECUTE]** с командой. Пользователь команды не вводит.

**Команды админ-бота** (выполняются в основном приложении, меняют чанки промпта в БД):

| Команда      | Описание |
|-------------|----------|
| `ADD_CHUNK` | Добавить чанк. Первая строка — вопрос (до 1000 символов), со второй — текст чанка (инструкция для чат-бота, до 2000 символов). |
| `EDIT_CHUNK` | Изменить чанк. Первая строка — UUID чанка, со второй — новый текст ответа. |
| `DELETE_CHUNK` | Удалить чанк. Со следующей строки — UUID чанка. |

Текущее состояние чанков (id, position, вопрос, превью ответа) передаётся в каждом запросе админ-чата, чтобы модель могла выбирать чанк по вопросу при правке и удалении.

### Пользовательский чат-бот

Системный промпт пользовательского бота собирается из **чанков** (раздел «Промпт» в кабинете). В этих чанках владелец может описать **триггеры**: при каких запросах клиента бот должен вывести блок `[EXECUTE]` с той или иной командой. Сервер выполняет команду (сам или через микросервисы Gallery/RAG), подставляет результат в ответ и отдаёт его клиенту.

**Команды пользовательского бота** (часть выполняется на сервере, часть — вызов микросервисов):

| Команда | Описание |
|---------|----------|
| `LIST_GALLERIES` | Список групп галерей тенанта (микросервис Gallery). `tenant_id` подставляется автоматически. |
| `SHOW_GALLERY` | Одна группа с изображениями. Аргумент: `group_id=<uuid>`. |
| `RAG_LIST_DOCUMENTS` | Список документов тенанта (микросервис RAG). |
| `RAG_GET_DOCUMENT` | Получить документ по id. Аргумент: `document_id=<uuid>`. |
| `RAG_SEARCH` | Поиск по документам. Аргумент: `query=<текст>` или `q=<текст>`. |

Пример формулировки в промпте (чанке), которую помогает составить админ-бот: *«Если пользователь просит показать галерею и непонятно какую — выведи список галерей командой [EXECUTE] LIST_GALLERIES [/EXECUTE], затем спроси какую показать. Когда пользователь выбрал — выведи [EXECUTE] SHOW_GALLERY с новой строки group_id=<id> [/EXECUTE].»*

Сохранение лидов (email, телефон из сообщений) выполняется на сервере автоматически при каждом сообщении пользователя, отдельной команды EXECUTE для этого нет.

## Тесты

```bash
pytest tests/ -v
```

Тесты используют in-memory SQLite (aiosqlite). Для полной совместимости с продакшеном (PostgreSQL UUID и т.д.) можно запускать тесты с реальной БД, задав `DATABASE_URL` в окружении.

## Конфигурация (.env)

Пароли и пользователи БД и MinIO задаются в `.env` (см. `.env.example`).

- **БД:** `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL`.
- **LLM:** `DEEPSEEK_API_URL`, `DEEPSEEK_API_KEY`
- **Приложение:** `PROMPT_FILE`, `APP_HOST`, `APP_PORT`
- **Регистрация и email:**  
  - `JWT_SECRET`, `JWT_EXPIRE_MINUTES`, `FRONTEND_BASE_URL`  
  - **SMTP:** в Docker поднимается контейнер **Mailpit** (SMTP 1025, Web UI 8025). Приложение шлёт письма с ссылками подтверждения в Mailpit; письма можно смотреть в браузере: **http://localhost:8025**. В `.env` для Docker: `SMTP_HOST=mailpit`, `SMTP_PORT=1025`. Для продакшена укажите свой SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`). Если SMTP не задан, письмо выводится в консоль.

## Устранение неполадок

### `InvalidPasswordError: password authentication failed for user "cip"`

Ошибка возникает, когда **пароль в `.env` не совпадает** с паролем, под которым PostgreSQL был впервые инициализирован в томе `pgdata`. При первом запуске контейнера `db` Postgres создаёт пользователя и пароль из переменных окружения и сохраняет данные в томе; при последующих запусках том уже содержит инициализированную БД, и смена `POSTGRES_PASSWORD` в `.env` **не меняет** пароль в БД.

**Вариант 1 — вернуть старый пароль:**  
Если помните пароль, под которым БД была создана изначально, задайте в `.env` те же значения: `POSTGRES_USER=cip`, `POSTGRES_PASSWORD=<тот_же_пароль>`, `POSTGRES_DB=cip`. В `docker-compose` приложение получает `DATABASE_URL` из этих переменных, поэтому они должны совпадать с учётными данными в томе.

**Вариант 2 — пересоздать том (данные БД будут удалены):**

```bash
docker-compose down
docker volume rm saasaisite_pgdata
docker-compose up -d db mailpit
# Дождаться готовности БД (healthcheck), затем:
docker-compose run --rm app alembic upgrade head
docker-compose up app
```

Имя тома может быть с префиксом папки (например `saasaisite_pgdata`). Проверить: `docker volume ls | grep pgdata`.
