#!/usr/bin/env bash
# Обновление Work Bot на VPS: pull → пересборка образа → перезапуск контейнера.
# Запуск: cd /opt/work-bot && sudo bash deploy/redeploy.sh
# Тома (данные переживают пересоздание контейнера):
#   /opt/work-bot/state            → /app/state   (база пользователей/документов, WORK_BOT_DB)
#   /opt/rag-ved/state/data        → /app/rag_data/docs (общая база источников ВЭД с ask.cygnusweb.ru)
set -euo pipefail
cd /opt/work-bot

git pull

sudo docker build -t work-bot .
sudo docker rm -f work-bot 2>/dev/null || true
sudo docker run -d --name work-bot --restart unless-stopped \
    --env-file /opt/work-bot/.env \
    -e WORK_BOT_DB=/app/state/work_bot.db \
    -v /opt/work-bot/state:/app/state \
    -v /opt/rag-ved/state/data:/app/rag_data/docs \
    work-bot

echo "Готово. Проверка: sudo docker ps | grep work-bot ; sudo docker logs work-bot --tail 20"