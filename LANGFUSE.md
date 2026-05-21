# LangFuse в lfsaasaisite

Форк `saasaisite` с observability: каждый запрос чата — **trace** в LangFuse, внутри — **generations** (DeepSeek) и **spans** (MCP `tools/list`, `tools/call`).

- Клиент LLM остаётся на **httpx** (без OpenAI SDK).
- LangFuse поднимается в Docker вместе с приложением (`docker-compose.langfuse.yml` подключается через `include`).

## Что видно в UI

| Тип | Имя | Когда |
|-----|-----|--------|
| Trace | `user-chat` | Пользовательский / тестовый / Telegram чат |
| Trace | `admin-chat` | Админ-помощник |
| Generation | `llm-round-N` / `llm-round-N-tools` | Каждый вызов DeepSeek |
| Span | `mcp/tools/call/<имя>` | Вызов инструмента на MCP-сервере |

Метаданные: `tenant_id`, `chat_type` (`prodchat`, `testchat`, `telegramchat`, `adminchat`), `session_id` (id диалога или `test_<user>`).

## Первый запуск

### 1. Окружение

```powershell
cd C:\путь\к\lfsaasaisite
copy .env.example .env
```

В `.env` обязательно:

- `DEEPSEEK_API_KEY=sk-...`
- Ключи LangFuse (по умолчанию совпадают с auto-init в compose):

```env
LANGFUSE_ENABLED=true
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-lfsaas-dev
LANGFUSE_SECRET_KEY=sk-lf-lfsaas-dev
```

В Docker для контейнера `app` хост переопределяется на `http://langfuse-web:3000` (см. `docker-compose.yml`).

### 2. Запуск стека

```powershell
docker compose up -d
```

Первый старт LangFuse занимает **2–5 минут** (ClickHouse, миграции). Дождитесь в логах `langfuse-web`: сообщение **Ready**.

```powershell
docker compose logs -f langfuse-web
```

### 3. Вход в LangFuse UI

1. Откройте http://localhost:3000  
2. Логин (создаётся при первом старте через `LANGFUSE_INIT_*` в `docker-compose.langfuse.yml`):
   - Email: `admin@langfuse.local`
   - Пароль: `langfuse123`
3. Проект **lfsaasaisite** и API-ключи `pk-lf-lfsaas-dev` / `sk-lf-lfsaas-dev` должны появиться автоматически.  
   Если ключи другие — скопируйте их из **Project → Settings → API Keys** в `.env` и перезапустите `app`:

```powershell
docker compose up -d app
```

### 4. Миграции приложения (если БД пустая)

```powershell
docker compose run --rm app alembic upgrade head
```

### 5. Сгенерировать трассировку

1. Откройте приложение: http://localhost:8000  
2. Войдите в кабинет тенанта и отправьте сообщение в **чат** или **тестовый чат** (с вопросом, где модель вызовет MCP, например «какие галереи?»).  
3. Либо откройте **админ-чат** и отправьте сообщение.

### 6. Просмотр traces

1. LangFuse → **Tracing** (или **Traces**)  
2. Фильтр по времени — последние минуты  
3. Откройте trace `user-chat` или `admin-chat`  
4. Внутри: цепочка `llm-round-*` и `mcp/tools/call/...`

**Session:** в списке traces можно группировать по `session_id` (= id диалога в БД).

## Локально без Docker LangFuse

1. Поднимите только LangFuse: `docker compose up -d langfuse-web` (и зависимости).  
2. В `.env`: `LANGFUSE_HOST=http://localhost:3000`, ключи как выше.  
3. `pip install -r requirements.txt` и `python run.py`.

## Отключить трассировку

```env
LANGFUSE_ENABLED=false
```

или оставьте пустыми `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`.

## Устранение неполадок

- **Traces не появляются** — проверьте `docker compose logs app` на ошибки LangFuse; убедитесь, что `langfuse-web` в состоянии running.  
- **`app` не стартует из-за langfuse-web** — дождитесь готовности LangFuse или временно уберите `langfuse-web` из `depends_on` в `docker-compose.yml`.  
- **Неверные ключи** — сверьте `.env` с UI → Project Settings → API Keys.
