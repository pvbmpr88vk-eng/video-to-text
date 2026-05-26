# ТЗ-10: Базовый слой GPU-интеграций

**Проект:** video-to-text
**Этап:** 10 (расширяемая GPU-инфраструктура)
**Зависит от:** [ТЗ-02](TZ-02-stt.md), [ТЗ-05](TZ-05-parallel-backend.md), [ТЗ-08](TZ-08-docker-deploy.md), [ТЗ-09](TZ-09-local-bot-api.md)
**Версия ТЗ:** 1.0
**Дата:** 2026-05-27

---

## 1. Цель

Сделать **единый базовый слой для GPU-провайдеров** в режиме **GPU-only**, чтобы текущий GPU Sharing v3 и следующие GPU-интеграции подключались через стабильный contract, без переписывания Telegram-бота, очередей, STT/summary pipeline и deploy-скриптов.

Главная идея: бизнес-логика работает с внутренними задачами `stt`, `llm`, `onnx_invoke`, а конкретный GPU backend скрыт за adapter-интерфейсом. Если GPU provider недоступен или не поддерживает задачу, job завершается ошибкой; локальный CPU не используется как резервный путь.

**Не в scope v1:**

- Полный ONNX Whisper decoder и production STT на CUDA.
- Собственный GPU scheduler.
- Kubernetes / autoscaling.
- Хранение пользовательских медиа в публичном облаке.
- Замена Ollama на GPU LLM backend.

---

## 2. Контекст

### 2.1. Текущая проблема

Сейчас GPU Sharing подключён точечно:

- `app/gpu_sharing/client.py` знает API v3 (`/v1/gpu/invoke`).
- `worker-transcript` публикует WAV в HTTP staging.
- `GPU_SHARING_TRANSCRIPT=1` пытается использовать remote STT, но реальная STT-задача не может ускориться, потому что v3 больше не поддерживает Docker jobs (`/v1/jobs`) и требует ONNX pipeline.

Это полезно для health-check, но не является полноценной архитектурой GPU-вычислений. Если завтра появится другой GPU backend, придётся снова вносить правки в pipeline.

### 2.2. Целевое решение

```
[Telegram / URL]
      ↓
extract_audio
      ↓
GPU gateway (внутренний contract)
      ├─ provider: gpu_sharing_v3
      ├─ provider: future_http_stt
      └─ provider: future_self_hosted_cuda
      ↓
TranscriptionResult / SummaryResult
```

Все внешние интеграции должны реализовывать один adapter API и возвращать нормализованный результат, понятный остальному приложению.

---

## 3. Термины

| Термин | Значение |
|--------|----------|
| `GPU provider` | Внешняя или внутренняя GPU-система: GPU Sharing v3, будущий HTTP STT, self-hosted CUDA |
| `adapter` | Python-класс, который реализует единый интерфейс для provider |
| `artifact` | Файл, который отдаётся GPU: WAV, ONNX, NPZ, JSON inputs |
| `staging` | Локальный каталог + HTTP server на VPS для прямых URL без редиректов |
| `invoke` | Низкоуровневый ONNX вызов: `model_url` + `inputs_url` → outputs |
| `GPU-only` | Режим, в котором STT/LLM GPU-задача не выполняется на CPU при ошибке provider |

---

## 4. Архитектура

### 4.1. Новые модули

```text
app/gpu/
  __init__.py
  config.py              # общий GPU config поверх env
  types.py               # dataclass/request/result/status/error
  artifacts.py           # staging publish + cleanup
  registry.py            # выбор provider по env
  health.py              # единый health/readiness
  providers/
    base.py              # интерфейс GPUProvider
    gpu_sharing_v3.py    # adapter текущего API v3
```

Старый пакет `app/gpu_sharing/` на первом этапе не удалять: обернуть его adapter-ом и постепенно перенести код.

### 4.2. Интерфейс provider

```python
class GPUProvider(Protocol):
    provider_id: str

    def health(self) -> GPUHealth:
        ...

    def transcribe(self, request: STTRequest) -> STTResult:
        ...

    def invoke_onnx(self, request: ONNXInvokeRequest) -> ONNXInvokeResult:
        ...
```

v1 обязан поддержать:

- `health()`;
- `invoke_onnx()` для GPU Sharing v3;
- `transcribe()` с понятным статусом `unsupported` для provider, где STT ещё не реализован;
- единый fail-fast путь для `unsupported` / offline / timeout.

### 4.3. Нормализованные типы

```python
@dataclass(frozen=True)
class STTRequest:
    wav_path: Path
    output_dir: Path
    language: str | None
    model: str
    timeout_sec: int
    job_id: str | None = None


@dataclass(frozen=True)
class STTResult:
    text: str
    language: str
    duration_sec: float
    provider_id: str
    remote_job_id: str | None
    device: str | None
    txt_path: Path
    json_path: Path
```

Ошибка provider не должна протекать наружу как `httpx`/`PermissionError`. На границе adapter-а всё превращается в:

- `GPUConfigError`;
- `GPUUnavailableError`;
- `GPUUnsupportedError`;
- `GPUInvokeError`;
- `GPUArtifactError`;
- `GPUTimeoutError`.

---

## 5. Artifact Staging

### 5.1. Требования

Для GPU Sharing v3 URL должен быть:

- прямой HTTP/HTTPS;
- без редиректов;
- доступный с GPU-узла;
- без ключей в query string;
- с TTL/cleanup, чтобы диск VPS не рос бесконечно.

### 5.2. Каталог

| Путь | Назначение |
|------|------------|
| host: `/opt/video-to-text/staging/gpu-audio` | файлы для HTTP server |
| container: `/staging/gpu-audio` | mount в `worker-transcript` |
| port: `18888` | `python3 -m http.server` на VPS |

Права обязательны:

```bash
chown -R 1000:1000 /opt/video-to-text/staging/gpu-audio
chmod 775 /opt/video-to-text/staging/gpu-audio
```

`scripts/ensure-gpu-staging.sh` должен всегда чинить права **до** проверки занятого порта.

### 5.3. Cleanup

Добавить cleanup старых staging-файлов:

| ENV | Default | Описание |
|-----|---------|----------|
| `GPU_ARTIFACT_TTL_HOURS` | `24` | удалить staging-файлы старше TTL |
| `GPU_ARTIFACT_MAX_BYTES` | `2147483648` | мягкий лимит каталога |

Cleanup запускать:

- в `ensure-gpu-staging.sh`;
- опционально из worker startup;
- без удаления файлов младше 1 часа.

---

## 6. Конфигурация

### 6.1. Общие ENV

| ENV | Default | Описание |
|-----|---------|----------|
| `GPU_PROVIDER` | `gpu_sharing_v3` | активный provider |
| `GPU_ENABLED` | `true` | общий флаг GPU-интеграций |
| `GPU_TASKS` | `stt,onnx` | какие задачи можно отдавать на GPU |
| `GPU_REQUIRED` | `true` | GPU обязателен для задач из `GPU_TASKS` |
| `GPU_FALLBACK_CPU` | `false` | запрещён; оставить только как guard, при `true` приложение не стартует в prod |
| `GPU_REQUEST_TIMEOUT_SEC` | `1800` | общий timeout remote-задачи |
| `GPU_ARTIFACT_TTL_HOURS` | `24` | TTL staging |
| `GPU_HEALTH_REQUIRED` | `true` | health падает при offline GPU |

### 6.2. GPU Sharing v3 ENV

| ENV | Описание |
|-----|----------|
| `GPU_SHARING_URL` | например `http://85.198.66.114:8082` |
| `GPU_SHARING_API_KEY` | только `.env` / VPS, не git |
| `GPU_SHARING_RUNTIME` | `onnx_cuda` |
| `GPU_SHARING_TEST_MODEL_URL` | прямой URL MNIST/другой ONNX для smoke |
| `GPU_SHARING_STT_PUBLISH_HOST` | публичный IP VPS |
| `GPU_SHARING_STT_STAGING_DIR` | `/staging/gpu-audio` |

Существующие `GPU_SHARING_*` оставить для совместимости, но новые части приложения должны читать общий `GPU_PROVIDER` и provider config.

---

## 7. Поведение STT

### 7.1. Алгоритм v1

1. `worker-transcript` извлекает WAV как сейчас.
2. `run_transcript_job()` вызывает `gpu.registry.get_provider()`.
3. Если `GPU_ENABLED=false` в prod → startup/config error. Для локальных тестов допускается отдельный test profile, но не production путь.
4. Если provider `health()` не готов → job failed с понятной ошибкой.
5. Если provider поддерживает `transcribe()` → remote STT.
6. Если provider возвращает `unsupported` → job failed: текущий GPU backend не поддерживает STT.
7. В sidecar JSON записываются metadata: `provider_id`, `device`, `remote_job_id`, `gpu_required=true`.

### 7.2. UX в Telegram

Сообщения пользователю:

- `Распознаю речь на GPU…` — только если provider реально поддерживает STT.
- `GPU сейчас недоступен. Задача остановлена, попробуйте позже.` — при offline/timeout.
- `GPU backend пока не поддерживает STT. Нужен ONNX STT provider.` — при `unsupported`.

Не писать пользователю низкоуровневые ошибки вроде `Permission denied`, `HTTP 401`, `404 /v1/jobs`. Они должны попадать в логи, а пользователю — короткая понятная причина.

---

## 8. ONNX Invoke

### 8.1. Требования к adapter

`gpu_sharing_v3.invoke_onnx()` должен:

1. Валидировать `model_url` и `inputs_url`.
2. Создать invoke через `POST /v1/gpu/invoke`.
3. Опросить статус.
4. Получить логи.
5. Нормализовать результат:
   - `status`;
   - `device`;
   - `metrics`;
   - `outputs_url`;
   - `outputs_inline_base64`;
   - `logs_tail`.

### 8.2. Smoke

Команда:

```bash
python -m app gpu check
python -m app gpu check --provider gpu_sharing_v3
python -m app gpu invoke-smoke --model-url "$GPU_SHARING_TEST_MODEL_URL"
```

Старую команду `python -m app gpu-sharing-check` оставить как alias до удаления.

---

## 9. Health и диагностика

### 9.1. Health уровни

| Уровень | Что проверяет | Fail policy |
|---------|---------------|-------------|
| `app health` | Redis, FFmpeg, Local Bot API, Ollama, GPU basic | GPU error, если `GPU_REQUIRED=true` |
| `gpu health` | provider credentials, runtimes/nodes | exit non-zero при ошибке |
| `gpu smoke` | реальный ONNX invoke | ручной/деплойный smoke |

### 9.2. Логи

Каждая GPU-задача логирует:

- `job_id` внутренний;
- `provider_id`;
- `remote_job_id` / `invoke_id`;
- `artifact_url` без секретов;
- `device`;
- `gpu_required`;
- длительность по этапам: publish, queue, compute, download/decode.

Секреты не логировать:

- API keys;
- Telegram tokens;
- signed URLs, если появятся.

---

## 10. Безопасность

1. `GPU_SHARING_API_KEY` только в `.env` и на VPS.
2. Handoff-файлы не коммитить.
3. Staging URL не должен содержать секреты.
4. Staging cleanup обязателен.
5. Не отдавать наружу весь `/opt/video-to-text`; только staging-каталог.
6. В публичном site API не показывать ключ, токены, raw errors.
7. Любой новый provider должен иметь список разрешённых env и секретов.

---

## 11. Файлы и изменения

### 11.1. Добавить

| Файл | Назначение |
|------|------------|
| `app/gpu/types.py` | request/result/error types |
| `app/gpu/artifacts.py` | staging publish + cleanup |
| `app/gpu/providers/base.py` | provider contract |
| `app/gpu/providers/gpu_sharing_v3.py` | adapter текущего API |
| `app/gpu/registry.py` | выбор provider |
| `app/gpu/health.py` | единый health |
| `tests/test_gpu_*.py` | unit tests |

### 11.2. Изменить

| Файл | Изменение |
|------|-----------|
| `app/queue/tasks.py` | вызывать общий GPU gateway вместо прямого `app.gpu_sharing` |
| `app/__main__.py` | новые команды `gpu check`, `gpu smoke`, alias старой команды |
| `app/worker/health.py` | использовать `app.gpu.health` |
| `app/site/gpu_api.py` | брать публичный статус из `app.gpu.health` |
| `docker-compose.yml` | staging volume оставить, имя не менять |
| `scripts/ensure-gpu-staging.sh` | права + cleanup + smoke-ready |
| `deploy/env/*.env.example` | общие `GPU_*` + provider-specific секция |

---

## 12. Миграция

### Этап A — базовый слой GPU-only

- Ввести `app/gpu/*`.
- Adapter `gpu_sharing_v3` внутри использует текущий `app/gpu_sharing/client.py`.
- STT не уходит на CPU, если provider не поддерживает production STT.
- `GPU_REQUIRED=true` и `GPU_FALLBACK_CPU=false` фиксируются для prod.
- Если текущий provider не готов к STT, пользователь получает понятную ошибку, а задача не маскируется локальным CPU.

### Этап B — нормальный artifact layer

- Перенести `publish_file_to_staging()` в `app/gpu/artifacts.py`.
- Добавить cleanup.
- Добавить тест записи в staging в `deploy-check.sh`.

### Этап C — ONNX STT

- Согласовать формат Whisper ONNX inputs/outputs.
- Реализовать packaging WAV → inputs.
- Реализовать decoder outputs → transcript.
- Включить remote STT только при green smoke.

### Этап D — новые provider

- `future_http_stt`: если админ даст готовый STT endpoint.
- `future_self_hosted_cuda`: если появится свой GPU/VPS.
- `future_gpu_llm`: если тезисы будут уходить на GPU LLM.

---

## 13. Тесты

### 13.1. Unit

- provider registry выбирает нужный backend;
- prod config запрещает `GPU_FALLBACK_CPU=true`;
- `gpu_sharing_v3` корректно обрабатывает:
  - health ok;
  - 401;
  - 503;
  - timeout;
  - `nodes` unavailable, но runtime enabled;
- staging publish создаёт файл с `uid/gid`-совместимыми правами;
- `unsupported` превращается в failed job без CPU fallback.

### 13.2. Integration

Локально:

```bash
python -m pytest tests/test_gpu_*.py
python -m app gpu check --skip-smoke
```

На VPS:

```bash
./scripts/ensure-gpu-staging.sh
python -m app gpu check
python -m app gpu invoke-smoke
./scripts/deploy-check.sh
```

### 13.3. Acceptance

- `worker-transcript` завершает job понятной ошибкой при недоступном GPU.
- Ошибка staging прав ловится в deploy-check до пользовательской задачи.
- Смена `GPU_SHARING_URL`/ключа не требует правки кода.
- Новый provider добавляется новым adapter-файлом и env, без правки Telegram handlers.
- В sidecar transcript JSON видно, какой GPU provider/device использовался.

---

## 14. Риски

| Риск | Митигирование |
|------|---------------|
| GPU API меняет endpoints | adapter изолирует изменения |
| `nodes` endpoint недоступен tenant-ключу | readiness по runtime + invoke smoke |
| Staging permission denied | `ensure-gpu-staging.sh` + deploy-check write test |
| Диск забивается WAV/NPZ | TTL cleanup |
| Пользователь видит техническую ошибку | нормализованные exceptions + user-friendly messages |
| ONNX Whisper сложен | включать production STT только после отдельного smoke и decoder tests |
| GPU offline останавливает прод-задачи | честный fail-fast, алертинг и ручной retry вместо скрытого CPU fallback |

---

## 15. Definition of Done

- Есть `app/gpu` contract и adapter `gpu_sharing_v3`.
- `run_transcript_job()` не импортирует напрямую provider-specific код.
- `python -m app gpu check` работает локально и на VPS.
- `deploy-check.sh` проверяет staging write + GPU health.
- Существующие тесты зелёные.
- В документации описано, как добавить новый provider.
- Прод не использует CPU fallback: `GPU_REQUIRED=true`, `GPU_FALLBACK_CPU=false`.
