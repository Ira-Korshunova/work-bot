# Контекст выполнения: ДЗ PE-r04 — Telegram RAG-бот с памятью

**Дата:** 2026-07-05  
**Рабочая папка:** `/Users/irina/Desktop/Домашка/ДЗ_мод5_4/work_bot/`  
**Бот:** DiV_executive (work_bot)

---

## Что сделано

### 1. Архитектура
- Перенесён `work_bot.py` из монолитного ДЗ_мод5_1 в модульную структуру:
  - `dialog_controller/session_manager.py`
  - `dialog_controller/user_context.py`
  - `storage/user_db.py`

### 2. Краткосрочная память
- `UserContext` хранит `conversation_history`.
- `handle_rag_qa` формирует `expanded_q` с предыдущими вопросами пользователя.
- Добавлен query rewriting (`_rewrite_follow_up`) для раскрытия коротких follow-up вопросов.

### 3. Команды
- `/clear` — очищает `conversation_history` и сбрасывает `top_k` на 5.
- `/top N [вопрос]` — устанавливает персональный `top_k` и сразу отвечает на вопрос.

### 4. Долгосрочная память
- `UserDatabase` сохраняет факты о пользователе в `user_data.json`.
- Известные факты подаются в LLM через `expanded_q` в `handle_rag_qa`.
- Эвристика: «Меня зовут Имя» → сохраняется факт `name`.

### 5. Улучшения retrieval
- Включён реранкер `qwen3-rerank` с `RAG_RERANK_MIN_SCORE=0.0`.
- Увеличен `RAG_MAX_CONTEXT=8000`.
- Улучшен chunking: добавлены markdown-заголовки (`#`, `##`, `###`), сохраняется `article`.
- Добавлена MMR-подобная диверсификация `_diverse_select`: не более 2 чанков из одного файла.
- Добавлен answer self-check `RAG_ANSWER_VERIFY=1`.

### 6. Модель
- `RAG_CHAT_MODEL` и `MODEL` изменены на `qwen3-max` (оптимальный баланс скорости/качества).

### 7. Документы
- Добавлены в `rag_data/docs/`:
  - `incoterms_2020.txt`
  - `usloviya_postavki_filo_lilo_lifo_fifo.txt` (статья BestDeals)
- Итог: 9 файлов, 99 чанков после удаления старого индекса и полной переиндексации.
- Дополнительно: `_diverse_select` теперь гарантирует `k` источников — если разных файлов не хватает, добирает лучших оставшихся кандидатов.
- Фикс «загрязнения» контекста: `/top 3 что такое коносамент` после диалога про FILO давал ответ на обе темы. Исправлено:
  - `_rewrite_follow_up` не трогает самодостаточные вопросы (`что такое ...`) и команды `/top`;
  - в `rag_engine.query` для retrieval передаётся только текущий вопрос, история подаётся LLM отдельно.
- Фикс форматирования: в системный промпт добавлен запрет markdown (#, **, *, `, \>), ответы теперь в plain-text Telegram-формате.

### 8. Файлы, изменённые в ходе работы
- `work_bot.py`
- `rag_engine.py`
- `.env`
- `dialog_controller/user_context.py` (read)
- `storage/user_db.py` (read)

### 9. Отчёт
- Черновик: `REPORT_PE_r04.md`

### 10. Что осталось
- Всё сделано: отчёт `REPORT_PE_r04.md` финализирован, скрины сохранены в `work_bot/screens/`.
- **Новая задача:** реализовать долгосрочную память на PostgreSQL вместо `user_data.json`.
  - План сохранён в `PLAN_long_term_postgres.md`.
  - Подход: Docker Compose (локально) + PostgreSQL + гибридное извлечение фактов (правила + LLM).
  - Цель: хранить множество фактов о многих пользователях, не только имя.
- Опционально: протестировать долгосрочную память (`Меня зовут Имя`) и сделать скрин.
  - `top3_filo.png`
  - `top5_filo.png`
  - `ingest_result.png`
- Вставить скрины в `REPORT_PE_r04.md`.
- Финализировать отчёт (убрать TODO, обновить описание улучшений).

---

## Конфигурация `.env` (итоговая)

```env
BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
MODEL=qwen3-max
RAG_EMBED_MODEL=text-embedding-v3
RAG_CHAT_MODEL=qwen3-max
RAG_RERANK_ON=1
RAG_RERANK_MIN_SCORE=0.0
RAG_RERANK_MODEL=qwen3-rerank
RAG_MAX_CONTEXT=8000
RAG_ANSWER_VERIFY=1
```

---

## Следующий шаг
Ждём скринов из Telegram для вставки в отчёт.
