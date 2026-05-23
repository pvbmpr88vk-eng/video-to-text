# Инструкция: сайт pible.ru

Краткое руководство по лендингу проекта. Сайт **не связан** с кодом бота: отдельные Docker-контейнеры, отдельный `docker-compose.site.yml`.

---

## Что уже сделано

| Параметр | Значение |
|----------|----------|
| Домен | **pible.ru**, **www.pible.ru** |
| DNS (reg.ru) | NS: `ns1.reg.ru`, `ns2.reg.ru` |
| A-записи | `@` и `www` → **62.217.176.132** |
| Сервер | VPS с ботом (`/opt/video-to-text`) |
| HTTPS | Caddy + Let's Encrypt (автообновление) |
| Страница | `website/public/` (HTML + CSS) |

Проверка в браузере: **https://pible.ru** и https://www.pible.ru  

**Не открывайте сайт по IP** (`https://62.217.176.132`) — для IP нет обычного SSL-сертификата, браузер пишет «не может обеспечить безопасное подключение». Это нормально. Используйте только домен.

---

## Как устроено

```
Интернет → :443 / :80 на VPS (62.217.176.132)
              ↓
         site-caddy (Caddy)     — TLS, редирект HTTP→HTTPS
              ↓
         site (nginx)           — статика из website/public/
```

Бот Telegram (`bot`, `worker-*`, `redis`) работает **параллельно**, домен для бота не нужен.

---

## Где лежат файлы

| Путь | Назначение |
|------|------------|
| `website/public/index.html` | Текст и разметка главной |
| `website/public/styles.css` | Оформление |
| `website/public/favicon.svg` | Иконка во вкладке |
| `docker-compose.site.yml` | Описание контейнеров |
| `deploy/caddy/Caddyfile` | Прокси и HTTPS |
| `deploy/env/site.env.example` | Пример переменных для `.env` |
| `scripts/deploy-site-remote.sh` | Деплой сайта на VPS с Mac |
| `scripts/up-site.sh` | Запуск сайта на сервере (если уже залогинены по SSH) |

На VPS всё в **`/opt/video-to-text/`** (те же пути).

В `.env` на сервере:

```bash
SITE_DOMAIN="pible.ru, www.pible.ru"
SITE_EMAIL=admin@pible.ru
```

---

## Как изменить текст или дизайн

1. Отредактируйте файлы в `website/public/` на Mac (в Cursor).
2. Залейте на сервер и пересоберите контейнер (см. ниже «Обновление с Mac»).
3. Обновите страницу в браузере (при необходимости Ctrl+F5).

Ссылку на Telegram-бота пока даёт администратор вручную (в HTML блок «Как подключиться»). При появлении постоянного `@username` бота — добавьте кнопку в `index.html`:

```html
<a class="btn btn--primary" href="https://t.me/ВАШ_БОТ">Открыть в Telegram</a>
```

---

## Обновление с Mac (рекомендуется)

На Mac в папке проекта:

```bash
cd "/Users/aleksejlassal/Desktop/project/video to text"

export DEPLOY_HOST=62.217.176.132
export DEPLOY_USER=root
export SITE_DOMAIN='pible.ru, www.pible.ru'
export SITE_EMAIL=admin@pible.ru

./scripts/deploy-site-remote.sh
```

Скрипт: копирует `website/`, Caddyfile и compose на VPS → обновляет `SITE_*` в `.env` → `docker compose -f docker-compose.site.yml up -d --build`.

---

## Команды на VPS (по SSH)

Подключение:

```bash
ssh -i ssh-keys/id_ed25519 root@62.217.176.132
cd /opt/video-to-text
```

| Действие | Команда |
|----------|---------|
| Статус | `docker compose -f docker-compose.site.yml ps` |
| Логи | `docker compose -f docker-compose.site.yml logs -f site site-caddy` |
| Перезапуск | `docker compose -f docker-compose.site.yml restart` |
| Пересборка после правок | `docker compose -f docker-compose.site.yml up -d --build` |
| Проверка HTTP | `curl -sI https://pible.ru/` |

Порты на фаерволе (если сайт не открывается снаружи):

```bash
ufw allow 80/tcp
ufw allow 443/tcp
```

---

## Если видите заглушку «Домен припаркован в Рег.ру»

Это **не наш сайт**. Reg.ru отдаёт парковку с IP **`95.163.244.138`**, пока домен «припаркован» или A-запись ещё указывает туда.

Наш лендинг Pible уже на VPS **`62.217.176.132`** — при прямом обращении к серверу он открывается. Нужно **отключить парковку** и выставить A-записи.

### Шаги в личном кабинете reg.ru

1. [reg.ru](https://www.reg.ru) → **Домены** → **pible.ru**.
2. **Отключить парковку домена** (если включена):
   - раздел вроде «Парковка» / «Настройки домена» → **выключить** / «Разместить на NS»;
   - не должно быть статуса «Домен припаркован».
3. **DNS-серверы:** `ns1.reg.ru`, `ns2.reg.ru` (стандартные NS reg.ru).
4. **Ресурсные записи** (зона DNS), удалите лишние A на `95.163.244.138`:

| Тип | Имя / Subdomain | Значение |
|-----|-----------------|----------|
| **A** | `@` (корень) | `62.217.176.132` |
| **A** | `www` | `62.217.176.132` |

5. Сохранить. Подождать **15–60 минут** (иногда до 24 ч).
6. Проверка (должен быть **только** IP VPS):

```bash
dig @8.8.8.8 +short pible.ru
# ожидается: 62.217.176.132
```

7. В браузере: https://pible.ru — заголовок вкладки **«Pible — видео в текст…»**, а не «Домен зарегистрирован в Рег.ру».

На Mac после смены DNS иногда помогает сброс кэша:

```bash
sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder
```

---

## DNS в reg.ru (справочник)

| Тип | Subdomain | Значение |
|-----|-----------|----------|
| A | `@` | `62.217.176.132` |
| A | `www` | `62.217.176.132` |

После смены IP перезапустите Caddy, чтобы перевыпустить сертификат:

```bash
docker compose -f docker-compose.site.yml restart site-caddy
```

---

## Локальный просмотр на Mac (без домена)

```bash
SITE_DOMAIN=:80 SITE_EMAIL= docker compose -f docker-compose.site.yml up -d --build
open http://127.0.0.1/
```

HTTPS локально не настраивается — только проверка вёрстки.

---

## Если что-то не работает

| Симптом | Что проверить |
|---------|----------------|
| **Заглушка Рег.ру** («припаркован») | Отключить парковку в reg.ru; A → `62.217.176.132`, не `95.163.244.138` |
| Сайт не открывается | `dig @8.8.8.8 pible.ru` — IP должен быть **62.217.176.132** |
| Нет HTTPS / «небезопасно» | Логи Caddy: `logs site-caddy`; DNS должен указывать на VPS **до** выпуска сертификата |
| 502 / пустая страница | `docker compose -f docker-compose.site.yml ps` — контейнер `site` должен быть `healthy` |
| Старая версия в браузере | Жёсткое обновление (Ctrl+F5) или режим инкогнито |
| Ошибка в `.env` с запятой в домене | Домен в кавычках: `SITE_DOMAIN="pible.ru, www.pible.ru"` |

Проверка DNS с Google:

```bash
dig @8.8.8.8 +short pible.ru
```

Проверка сайта напрямую по IP (минуя кэш DNS):

```bash
curl -sI --resolve pible.ru:443:62.217.176.132 https://pible.ru/
```

---

## Связь с ботом и полным деплоем

- **Только сайт:** `./scripts/deploy-site-remote.sh`
- **Бот + воркеры:** `./scripts/deploy-remote.sh` (см. `deploy/README.md`)
- Если в локальном `.env` задан `SITE_DOMAIN`, при полном деплое сайт тоже поднимается автоматически.

Сайт и бот на одном VPS — это нормально: разные контейнеры, общий IP, разные роли (веб vs Telegram).

---

## Полезные ссылки

- Репозиторий: https://github.com/pvbmpr88vk-eng/video-to-text  
- Деплой бота: [deploy/README.md](../deploy/README.md)  
- Пример env: [deploy/env/site.env.example](../deploy/env/site.env.example)
