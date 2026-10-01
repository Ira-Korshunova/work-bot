# План: долгосрочная память на PostgreSQL + Docker Compose

**Дата:** 2026-07-05  
**Статус:** утверждён пользователем  
**Выбранный стек:** Docker Compose (локально) + PostgreSQL + гибридное извлечение фактов  

---

## 1. Цель

Заменить файловое хранилище `user_data.json` на полноценную PostgreSQL-базу для долгосрочной памяти, способную работать с множеством пользователей и автоматически извлекать/сохранять разнообразные факты (не только имя).

---

## 2. Архитектура долгосрочной памяти

### 2.1 Схема PostgreSQL

```sql
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_active TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE user_facts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    fact_type TEXT DEFAULT 'general',
    confidence REAL DEFAULT 0.9,
    source_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, fact_key)
);

CREATE TABLE conversation_summaries (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    topics TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 2.2 Гибридное извлечение фактов

**A. Правила для очевидных паттернов (fast path):**

| Паттерн в сообщении | Факт (key) | Пример значения |
|---|---|---|
| «Меня зовут Имя» | `name` | Ирина |
| «Я из Москвы» / «компания в Новосибирске» | `city` | Москва |
| «Я экспортёр/импортёр» | `role` | импортёр |
| «У нас электроника» / «торгуем одеждой» | `product_category` | электроника |
| «Мы работаем по FOB» / «предпочитаем DDP» | `preferred_incoterm` | FOB |
| «Доставляем в Китай» / «из Европы» | `trade_direction` | экспорт в Китай |

**B. LLM-структурирование (slow path):**

- Запускается каждые N сообщений (например, каждое 3-е) или при высокой «информационной плотности» сообщения.
- Получает последние сообщения диалога + уже известные факты.
- Возвращает JSON:
  ```json
  {
    "facts": [
      {"key": "name", "value": "Ирина", "confidence": 0.95, "type": "profile"},
      {"key": "company_city", "value": "Москва", "confidence": 0.8, "type": "profile"},
      {"key": "product_category", "value": "электроника", "confidence": 0.85, "type": "business"}
    ]
  }
  ```
- Только факты с `confidence >= 0.7` сохраняются.

**C. Использование в ответах:**

- Перед ответом извлекаем все факты пользователя из PostgreSQL.
- Формируем блок «Известные факты о пользователе» и подаём в LLM вместе с историей.
- При необходимости фильтруем факты по релевантности к текущему вопросу.

---

## 3. Docker Compose для локального запуска

### 3.1 `docker-compose.yml`

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16
    container_name: work_bot_postgres
    environment:
      POSTGRES_USER: workbot
      POSTGRES_PASSWORD: workbot_pass
      POSTGRES_DB: workbot_db
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U workbot -d workbot_db"]
      interval: 5s
      timeout: 5s
      retries: 5

  bot:
    build: .
    container_name: work_bot
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./rag_data:/app/rag_data
      - ./screens:/app/screens
      - ./user_data.json:/app/user_data.json:ro
    restart: unless-stopped

volumes:
  postgres_data:
```

### 3.2 `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "work_bot.py"]
```

### 3.3 Запуск

```bash
docker compose up --build
```

Данные PostgreSQL сохраняются в named volume `postgres_data` между перезапусками.

---

## 4. Изменения в коде

### 4.1 Новые/изменённые файлы

1. **`storage/postgres_db.py`** — новый класс `PostgresUserDatabase` с интерфейсом, совместимым с текущим `UserDatabase`:
   - `create_or_update_user(user_id, name=None, metadata=None)`
   - `set_fact(user_id, key, value, fact_type='general', confidence=0.9, source_message=None)`
   - `get_facts(user_id)`
   - `get_name(user_id)`
   - `get_user_count()`

2. **`storage/migrations/001_initial.sql`** — первая миграция (создание таблиц).

3. **`storage/migrations.py`** — автоприменение миграций при старте.

4. **`work_bot.py`**:
   - Импорт `PostgresUserDatabase` вместо `UserDatabase`.
   - Добавление `DATABASE_URL` из `.env`.
   - Эвристика извлечения фактов: расширить с `name` до набора правил (city, role, product_category и т.д.).
   - Добавить `extract_facts_with_llm(history, existing_facts)` — LLM-структурирование.
   - Вызвать извлечение фактов после ответа бота.
   - Сохранять профиль пользователя в PostgreSQL.

5. **`.env`**:
   - Добавить `DATABASE_URL=postgresql://workbot:workbot_pass@postgres:5432/workbot_db`.
   - Добавить `LLM_FACT_EXTRACTION_EVERY=3` (каждые N сообщений запускать LLM-анализ).

6. **`requirements.txt`**:
   - Добавить `psycopg2-binary`.
   - Включить все текущие зависимости бота.

### 4.2 Индексы и оптимизация

```sql
CREATE INDEX idx_user_facts_user_id ON user_facts(user_id);
CREATE INDEX idx_users_telegram_id ON users(telegram_id);
```

---

## 5. Почему выбран гибридный подход

| Подход | Плюсы | Минусы | Годится для этого бота |
|---|---|---|---|
| **Правила + LLM** | Быстро, дёшево, контролируемо, не плодит мусор | Нужна схема фактов | ✅ Да — оптимум |
| **LLM на каждое сообщение** | Универсально | Дорого, много токенов, риск ложных фактов | ❌ Перебор для учебного бота |
| **RAG embeddings по истории** | Не нужна схема | Не хранит конкретные факты (имя, роль), сложнее использовать | ❌ Не подходит для имени/профиля |

---

## 6. Риски и смягчение

| Риск | Решение |
|---|---|
| LLM сохраняет ложный факт | Храним `confidence`, `source_message`, `updated_at` — можно аудировать и удалять |
| Перегруз промпта фактами | Берём top-N по confidence или фильтруем по теме вопроса |
| Потеря старых данных | `user_data.json` остаётся как резерв; при желании — скрипт миграции в PostgreSQL |
| Ошибка подключения к PostgreSQL | Graceful fallback на JSON-хранилище при старте |
| Дублирование фактов | `UNIQUE(user_id, fact_key)` + `ON CONFLICT UPDATE` |

---

## 7. Критерии успеха

- [ ] `docker compose up --build` поднимает PostgreSQL и бота без ошибок.
- [ ] Бот сохраняет имя, город, роль, сферу и другие факты в PostgreSQL.
- [ ] После перезапуска бота факты не теряются.
- [ ] При `/clear` очищается краткосрочная история, но долгосрочные факты остаются.
- [ ] При многопользовательской нагрузке факты не смешиваются между пользователями.
- [ ] Сделан скриншот долгосрочной памяти (например, «Меня зовут Ирина» → «Какие документы мне нужны?» с обращением по имени).
- [ ] `REPORT_PE_r04.md` обновлён с описанием новой архитектуры памяти.

---

## 8. Следующий шаг

Реализовать план: добавить PostgreSQL-хранилище, Docker Compose, гибридное извлечение фактов и обновить отчёт.
