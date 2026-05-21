# Deploy on VPS (2 vCPU / 4 GB RAM)

## 1. Prerequisites

- Ubuntu 22.04+ (or Debian 12+)
- Docker Engine 24+ and Compose v2
- [Ollama](https://ollama.com) **on the host** (not in Docker on 4 GB):

```bash
curl -fsSL https://ollama.com/install.sh | sh
./scripts/pull-summary-model.sh
# or: ollama pull qwen2.5:3b-instruct
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
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
./scripts/deploy-check.sh
```

## 4. Maintenance

```bash
docker compose logs -f bot
docker compose exec bot python -m app jobs reset-stuck
docker compose exec bot python -m app jobs cleanup
```

## RAM note

Do **not** enable `with-ollama` profile on 4 GB — run Ollama on the host only. One STT job + host Ollama must fit in 4 GB total.
