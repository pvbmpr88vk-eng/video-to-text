# Deploy on VPS (2 vCPU / 4 GB RAM)

## 1. Prerequisites

- Ubuntu 22.04+ (or Debian 12+)
- Docker Engine 24+ and Compose v2
- [Ollama](https://ollama.com) **on the host** (not in Docker on 4 GB):

```bash
curl -fsSL https://ollama.com/install.sh | sh
# Allow Docker containers to reach Ollama on the host:
mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0:11434\n' \
  > /etc/systemd/system/ollama.service.d/override.conf
systemctl daemon-reload && systemctl restart ollama
ollama pull qwen2.5:3b-instruct
```

## 2. Configure

```bash
git clone <repo> && cd video-to-text
cp deploy/env/minimal-4gb.env .env
# Edit .env: TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_IDS
cp telegram-bot.access.example.txt telegram-bot.access.txt  # or TELEGRAM_BOT_TOKEN in .env
```

## 3. Start

```bash
mkdir -p output/jobs output/telegram/inbox
sudo chown -R 1000:1000 output   # обязательно: контейнеры пишут как uid 1000
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
./scripts/deploy-check.sh
```

Если ссылки не качаются — проверьте права: `ls -la output` (должен владелец **1000:1000**), иначе бот не создаст `output/jobs/...`.

После первого `docker compose up` выполните (или `./scripts/fix-docker-volumes.sh`):

```bash
sudo chown -R 1000:1000 output
docker compose run --rm --user root worker-transcript sh -c \
  'mkdir -p /home/appuser/.cache/huggingface/hub && chown -R 1000:1000 /home/appuser/.cache'
```

Если бот пишет **«Модель распознавания не загружена»** — в логах worker-transcript часто `Permission denied` на `/home/appuser/.cache/huggingface/hub`: том `whisper_cache` создан от root. Команды выше + прогрев модели:

```bash
docker compose exec -T worker-transcript python -c \
  "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
```

## 4. Local Bot API (файлы >20 MB, TZ-09)

Опционально, отдельный контейнер + автоочистка кэша (TTL 6 h по умолчанию).

```bash
# В .env добавить из deploy/env/local-bot-api.env.example:
# TELEGRAM_API_ID, TELEGRAM_API_HASH (my.telegram.org)

./scripts/up-with-local-bot-api.sh
# или: ENABLE_LOCAL_BOT_API=1 ./scripts/deploy-remote.sh

./scripts/telegram-bot-api-cleanup.sh 6   # ручная очистка при необходимости
```

Подробно: [docs/TZ-09-local-bot-api.md](../docs/TZ-09-local-bot-api.md).

## 5. Maintenance

```bash
docker compose logs -f bot
docker compose exec bot python -m app jobs reset-stuck
docker compose exec bot python -m app jobs cleanup
```

## RAM note

Do **not** enable `with-ollama` profile on 4 GB — run Ollama on the host only. One STT job + host Ollama must fit in 4 GB total.

## 6. Сайт pible.ru

Лендинг: **https://pible.ru** (контейнеры `site` + `site-caddy`, отдельно от бота).

**Полная инструкция:** [docs/deploy-site.md](../docs/deploy-site.md) — правка HTML, деплой с Mac, DNS reg.ru, HTTPS, troubleshooting.

Быстрое обновление с Mac:

```bash
export DEPLOY_HOST=62.217.176.132 DEPLOY_USER=root
export SITE_DOMAIN='pible.ru, www.pible.ru' SITE_EMAIL=admin@pible.ru
./scripts/deploy-site-remote.sh
```
