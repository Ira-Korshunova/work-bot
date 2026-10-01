#!/usr/bin/env bash
# Обновление Work Bot на VPS: pull → пересборка образа → перезапуск контейнера.
# Запуск: cd /opt/work-bot && sudo bash deploy/redeploy.sh
set -euo pipefail
cd /opt/work-bot

git pull

sudo docker build -t work-bot .
sudo docker rm -f work-bot 2>/dev/null || true
sudo docker run -d --name work-bot --restart unless-stopped \
    --env-file /opt/work-bot/.env \
    work-bot

echo "Готово. Проверка: sudo docker ps | grep work-bot ; sudo docker logs work-bot --tail 20"