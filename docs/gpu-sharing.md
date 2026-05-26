# GPU Sharing v3 (ONNX на удалённом CUDA)

Ключ и URL — только в `.env` (см. `deploy/env/gpu-sharing.env.example`), **не в git**.  
Актуальный handoff: `tenant-handoff.md` от администратора GPU Sharing.

## Модель v3

| У вас (Mac / VPS) | На GPU-узле |
|-------------------|-------------|
| Docker, Python, faster-whisper, экспорт ONNX | Только **CUDA + ONNX Runtime** |
| Подготовка входов, постобработка | Forward по URL артефактов |

**Не используются:** `POST /v1/jobs` (`image` / `command`), `POST /v1/compute/transcribe`.

## Переменные

| ENV | Описание |
|-----|----------|
| `GPU_SHARING_URL` | `http://85.198.66.114:8082` |
| `GPU_SHARING_API_KEY` | `gpu_sk_...` |
| `GPU_SHARING_ENABLED` | `true` — проверка в `app health` |
| `GPU_SHARING_RUNTIME` | `onnx_cuda` (по умолчанию) |
| `GPU_SHARING_TEST_MODEL_URL` | Прямой URL ONNX для smoke (без редиректов) |

| `GPU_SHARING_TRANSCRIPT` | `1` — сначала GPU Sharing, при ошибке — локальный Whisper (`GPU_SHARING_STT_FALLBACK_CPU`) |
| `GPU_SHARING_STT_PUBLISH_HOST` | Публичный IP VPS для URL аудио (например `62.217.176.132`) |
| `GPU_SHARING_STT_STAGING_DIR` | `/staging/gpu-audio` в контейнере (volume + `scripts/ensure-gpu-staging.sh` на хосте) |
| `GPU_SHARING_STT_FALLBACK_CPU` | `true` — Whisper на VPS, если v3 jobs/ONNX недоступны |

**Устарело (v1/v2):** Docker jobs (`POST /v1/jobs`) с faster-whisper на GPU — API возвращает 404; реальный STT на CUDA только через ONNX invoke.

## Проверка

```bash
# В .env:
# GPU_SHARING_TEST_MODEL_URL=http://62.217.176.132:18888/mnist-12.onnx
python -m app gpu-sharing-check
python -m app gpu-sharing-check --skip-invoke   # только health/nodes/runtimes
```

На VPS для теста нужен **прямой** URL модели (GitHub raw редиректит — GPU-узел отклонит):

```bash
mkdir -p /tmp/vtt-gpu-audio
curl -sfL -o /tmp/vtt-gpu-audio/mnist-12.onnx \
  'https://github.com/onnx/models/raw/main/validated/vision/classification/mnist/model/mnist-12.onnx'
cd /tmp/vtt-gpu-audio && nohup python3 -m http.server 18888 >/tmp/vtt-http-18888.log 2>&1 &
ufw allow 18888/tcp
```

## API (кратко)

- `GET /health`, `GET /v1/nodes`, `GET /v1/gpu/runtimes`
- `POST /v1/gpu/invoke` — `runtime`, `model_url`, `inputs_url`, `timeout_sec`
- `GET /v1/gpu/invokes/{id}`, `.../logs`

Клиент: `app/gpu_sharing/client.py` (`create_invoke`, `run_invoke`, …).

Swagger: http://85.198.66.114:8082/docs/

## STT через GPU (следующий этап)

1. На VPS: экспорт Whisper → ONNX, подготовка батчей входов.
2. Загрузка `model_url` / `inputs_url` в HTTP/S3 (без редиректов).
3. `POST /v1/gpu/invoke` → опрос → декодирование выходов локально.

С `GPU_SHARING_TRANSCRIPT=1` worker проверяет узел GPU, публикует WAV на `:18888`, пробует remote STT; при 404/ошибке — **локальный** faster-whisper на VPS (если `GPU_SHARING_STT_FALLBACK_CPU=1`).

На сервере после деплоя: `./scripts/ensure-gpu-staging.sh` (или в `deploy-remote.sh`).
