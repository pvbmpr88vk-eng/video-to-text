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
| `GPU_SHARING_URL` | `http://81.163.244.151` |
| `GPU_SHARING_API_KEY` | `gpu_sk_...` |
| `GPU_SHARING_ENABLED` | `true` — проверка в `app health` |
| `GPU_SHARING_RUNTIME` | `onnx_cuda` (по умолчанию) |
| `GPU_SHARING_TEST_MODEL_URL` | Прямой URL ONNX для smoke (без редиректов) |

**Устарело (v1/v2):** `GPU_SHARING_TRANSCRIPT=1` — Docker jobs с faster-whisper на GPU; API больше не поддерживает allowlist образов.

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

Swagger: http://81.163.244.151/docs/

## STT через GPU (следующий этап)

1. На VPS: экспорт Whisper → ONNX, подготовка батчей входов.
2. Загрузка `model_url` / `inputs_url` в HTTP/S3 (без редиректов).
3. `POST /v1/gpu/invoke` → опрос → декодирование выходов локально.

Пока STT в боте — **локальный** faster-whisper в `worker-transcript` (`GPU_SHARING_TRANSCRIPT` не включать).
