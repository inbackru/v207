# InBack — Полный гайд по переезду на новый хостинг

> Этот файл — ваш единственный документ при переезде. Всё, что нужно настроить, описано здесь.

---

## Содержание

1. [Что нужно перед стартом](#1-что-нужно-перед-стартом)
2. [База данных PostgreSQL](#2-база-данных-postgresql)
3. [Обязательные переменные окружения](#3-обязательные-переменные-окружения)
4. [Telegram Bot](#4-telegram-bot)
5. [DaData (адреса)](#5-dadata-адреса)
6. [Email (SendGrid или SMTP)](#6-email-sendgrid-или-smtp)
7. [Яндекс Карты](#7-яндекс-карты)
8. [SMS и верификация телефонов](#8-sms-и-верификация-телефонов)
9. [OAuth (Google, VK, Mail.ru)](#9-oauth-google-vk-mailru)
10. [OpenAI (умный поиск)](#10-openai-умный-поиск)
11. [Push-уведомления (VAPID)](#11-push-уведомления-vapid)
12. [Настройки приложения](#12-настройки-приложения)
13. [Запуск приложения](#13-запуск-приложения)
14. [Проверочный чеклист](#14-проверочный-чеклист)

---

## 1. Что нужно перед стартом

**Минимальный набор (без него сайт не запустится):**
- PostgreSQL база данных
- `SESSION_SECRET` — случайная строка
- `DATABASE_URL` — строка подключения к БД

**Нужно для полной работы:**
- Telegram Bot Token
- DaData API ключи
- Яндекс Карты API ключ
- SendGrid или SMTP для писем

---

## 2. База данных PostgreSQL

### Получить DATABASE_URL

На большинстве хостингов (Railway, Render, VPS с PostgreSQL) вы получите строку вида:

```
postgresql://USERNAME:PASSWORD@HOST:PORT/DBNAME
```

Пример:
```
postgresql://inback_user:mypassword123@db.example.com:5432/inback_db
```

### Переменные окружения для БД

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname

# Эти нужны только если DATABASE_URL не задан (устаревший формат)
PGUSER=inback_user
PGPASSWORD=mypassword123
PGHOST=db.example.com
PGPORT=5432
PGDATABASE=inback_db
```

### Первый запуск — миграции

При первом запуске приложение само создаёт все таблицы (через `db.create_all()`).  
Если нужно перенести данные со старой БД:

```bash
# На старом сервере — дамп
pg_dump -U postgres inback_db > backup.sql

# На новом сервере — восстановление
psql -U postgres -d inback_db_new < backup.sql
```

---

## 3. Обязательные переменные окружения

Это минимум для запуска. Установите их **до** старта приложения.

| Переменная | Описание | Пример |
|---|---|---|
| `SESSION_SECRET` | Секретный ключ сессий Flask. Сгенерируйте случайную строку | `openssl rand -hex 32` |
| `DATABASE_URL` | Строка подключения к PostgreSQL | `postgresql://...` |
| `ENABLE_SCHEDULER` | Включить планировщик задач (APScheduler) | `true` |

### Как сгенерировать SESSION_SECRET

```bash
# В терминале:
openssl rand -hex 32
# Пример вывода: a3f5c8d2e1b4...
```

---

## 4. Telegram Bot

### Шаг 1 — Создать бота у @BotFather

1. Откройте Telegram → найдите **@BotFather**
2. Отправьте `/newbot`
3. Придумайте имя и username (должен заканчиваться на `bot`)
4. Скопируйте токен вида: `8377782722:AAFJwdlHa-gO_hPRNVm9Eb4-X71pbjC5fKQ`

### Шаг 2 — Узнать ваш Chat ID (для уведомлений владельца)

1. Напишите что-нибудь вашему боту
2. Откройте в браузере: `https://api.telegram.org/botТОКЕН/getUpdates`
3. Найдите `"chat":{"id":XXXXXXXX}` — это и есть ваш Chat ID

### Переменные окружения

```env
TELEGRAM_BOT_TOKEN=8377782722:AAFJwdlHa-gO_hPRNVm9Eb4-X71pbjC5fKQ
TELEGRAM_CHAT_ID=730764738          # Ваш личный Chat ID (для уведомлений владельца)
TELEGRAM_BOT_USERNAME=Inback_bot    # Username без @
BOT_WEBHOOK_SECRET=inback_bot_secret_2024  # Любая секретная строка для API
```

### Шаг 3 — Запустить бота

```bash
python run_bot.py
```

Бот работает как отдельный процесс (второй воркфлоу). На сервере запустите его через systemd или supervisor.

### Как менеджеры подключают бот

1. Менеджер заходит на сайт → **Профиль → раздел "Telegram-аккаунт"**
2. Нажимает **"Получить код для Telegram"** — появляется 6-значный код на 10 минут
3. Открывает бота (`@Inback_bot`) и отправляет: `/link 123456`
4. Бот привязывает аккаунт и показывает Панель менеджера

### Команды бота для менеджеров

| Команда | Что делает |
|---|---|
| `/start` | Открыть главное меню / панель менеджера |
| `/link КОД` | Привязать аккаунт менеджера (6-значный код с сайта) |
| `/online` | Установить статус "Онлайн" |
| `/offline` | Установить статус "Офлайн" |
| `/stop` | Завершить чат поддержки (для клиентов) |
| `/close_N` | Менеджер закрывает чат №N |

---

## 5. DaData (адреса)

DaData используется для умного поиска адресов — нормализует, подсказывает улицы, геокодирует.

### Получить ключи

1. Зарегистрируйтесь на **[dadata.ru](https://dadata.ru)**
2. Перейдите в профиль → **API-ключи**
3. Скопируйте **Token (API-ключ)** и **Secret (секретный ключ)**

> Бесплатный тариф: 10 000 запросов/день — для начала хватит.

### Переменные окружения

```env
DADATA_API_KEY=ваш_token_из_личного_кабинета
DADATA_SECRET_KEY=ваш_secret_из_личного_кабинета
```

### Как работает (проверено)

DaData в проекте делает три вещи:

1. **Подсказки адресов** при поиске на сайте — возвращает улицы, районы, города с координатами
2. **Нормализация адресов** при импорте объектов — разбивает строку адреса на компоненты (город, улица, дом)
3. **Геокодирование** — получает координаты lat/lon для адреса

Клиент (`services/dadata_client.py`) умеет:
- Кешировать результаты (улицы — 1 час, города — 12 часов)
- Фильтровать по FIAS-ID города или региона из базы
- Корректно работает без ключей — просто отключает подсказки, не ломает сайт

### Проверить что DaData работает

```python
# Запустите в Python-консоли на сервере:
from services.dadata_client import get_dadata_client
client = get_dadata_client()
print("Доступна:", client.is_available())
result = client.suggest_address("Сочи, Курортный проспект", count=3)
for r in result:
    print(r['text'], r['type'], r['data']['geo_lat'], r['data']['geo_lon'])
```

Ожидаемый вывод:
```
✅ DaData client initialized successfully
Доступна: True
Краснодарский край, г Сочи, Курортный пр-кт street 43.585... 39.723...
```

---

## 6. Email (SendGrid или SMTP)

В проекте два варианта отправки писем. Используется первый доступный.

### Вариант A — SendGrid (рекомендуется)

1. Зарегистрируйтесь на **[sendgrid.com](https://sendgrid.com)**
2. Settings → API Keys → Create API Key (Full Access)
3. Скопируйте ключ (показывается только один раз!)

```env
SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Вариант B — SMTP (Gmail или другой)

Если SendGrid не настроен, система использует SMTP.

```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=your.email@gmail.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx   # App Password от Google (не основной пароль!)
```

**Как получить App Password для Gmail:**
1. myaccount.google.com → Безопасность → Двухэтапная аутентификация (включить)
2. Безопасность → Пароли приложений → Создать → Другое → Ввести "InBack"
3. Скопировать 16-значный пароль

---

## 7. Яндекс Карты

Используется для отображения карты объектов и геокодирования.

### Получить ключ

1. **[developer.tech.yandex.ru](https://developer.tech.yandex.ru)** → Подключить API
2. Выберите **JavaScript API и HTTP Геокодер**
3. Создайте ключ, укажите домен вашего сайта

```env
YANDEX_MAPS_API_KEY=ваш_ключ_яндекс_карт
YANDEX_API_KEY=тот_же_ключ   # Дублируется для совместимости старого кода
```

> Без этого ключа карта на сайте работать не будет.

---

## 8. SMS и верификация телефонов

Используется для верификации при регистрации и смене телефона. Работает в цепочке:  
**Telegram Gateway → RED SMS (SMSC) → SMS.ru**

### 8.1 — Telegram Gateway (первичный канал)

Пользователи с Telegram получают код через бота `@VerificationCodes` — бесплатно.

1. **[gateway.telegram.org](https://gateway.telegram.org)** → Войти через Telegram
2. Создать проект → скопировать токен

```env
TELEGRAM_GATEWAY_TOKEN=ваш_токен_gateway
```

### 8.2 — SMSC.ru (основной SMS)

1. Зарегистрируйтесь на **[smsc.ru](https://smsc.ru)**
2. Пополните баланс (минимум ~100 ₽)
3. Настройки → API

```env
SMSC_LOGIN=ваш_логин_smsc
SMSC_PASSWORD=ваш_пароль_smsc
```

### 8.3 — SMS.ru (резерв)

```env
SMS_RU_API_KEY=ваш_api_ключ_smsru
```

> Если ни один SMS-сервис не настроен — верификация телефона будет недоступна. Регистрация через email будет работать.

---

## 9. OAuth (Google, VK, Mail.ru)

Кнопки "Войти через..." на странице авторизации. Если ключи не заданы — кнопки отображаются неактивными (серыми), сайт работает нормально.

### Google OAuth

1. **[console.cloud.google.com](https://console.cloud.google.com)** → Новый проект
2. APIs & Services → Credentials → Create OAuth 2.0 Client ID
3. Тип: Web application
4. Authorized redirect URIs: `https://ваш-сайт.ru/auth/google/callback`

```env
GOOGLE_OAUTH_CLIENT_ID=123456789-xxx.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxx
```

### VK OAuth

1. **[vk.com/editapp?act=create](https://vk.com/editapp?act=create)** → Создать приложение
2. Настройки → Адрес сайта: `https://ваш-сайт.ru`
3. Redirect URI: `https://ваш-сайт.ru/auth/vk/callback`

```env
VK_CLIENT_ID=12345678
VK_CLIENT_SECRET=ваш_защищённый_ключ
```

### Mail.ru OAuth

1. **[o2.mail.ru](https://o2.mail.ru)** → Добавить сайт
2. Redirect URI: `https://ваш-сайт.ru/auth/mailru/callback`

```env
MAILRU_CLIENT_ID=ваш_client_id
MAILRU_CLIENT_SECRET=ваш_client_secret
```

---

## 10. OpenAI (умный поиск)

Используется для смарт-поиска объектов на сайте и парсинга данных.

1. **[platform.openai.com](https://platform.openai.com)** → API keys → Create new secret key
2. Пополните баланс (минимум $5)

```env
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxx
```

> Без этого ключа умный поиск переходит в режим обычного текстового поиска.

---

## 11. Push-уведомления (VAPID)

Для браузерных push-уведомлений. Если ключи не заданы — используются дефолтные (менее безопасно).

### Сгенерировать новые ключи

```bash
pip install py-vapid
vapid --gen
# Создаст файлы private_key.pem и public_key.pem
vapid --applicationServerKey
```

Или онлайн: **[web-push-codelab.glitch.me](https://web-push-codelab.glitch.me)**

```env
VAPID_PUBLIC_KEY=BGfIV-CV2dR_VC64j20pPWwaqnlJEuB2sv-9sy__gScPQX1G-O9bGl98k72Mv50HWUOv3c4zjnAZbnX_ZbSMJ_k
VAPID_PRIVATE_KEY=2ru13vmOlxSnoUDR7apBbnSOFdwPDv_DacLGwG0yfqg
```

> Текущие ключи выше уже вшиты в код как дефолтные. Для продакшна сгенерируйте свои.

---

## 12. Настройки приложения

```env
SITE_URL=https://inback.ru          # Полный URL сайта (без слеша в конце)
QR_DOMAIN=https://inback.ru        # Домен для QR-кодов (обычно тот же)
ENABLE_SCHEDULER=true              # APScheduler: планировщик задач (рассылки, дайджесты)
MANAGER_TELEGRAM_IDS=730764738,987654321  # Telegram ID менеджеров через запятую (опционально)
BOT_WEBHOOK_SECRET=ваша_строка_2024  # Секрет для вебхука бота
```

---

## 13. Запуск приложения

### Основное приложение (Flask + Gunicorn)

```bash
gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 120 main:app
```

### Telegram Bot (отдельный процесс)

```bash
python run_bot.py
```

### Через systemd (на VPS)

Создайте файл `/etc/systemd/system/inback-web.service`:
```ini
[Unit]
Description=InBack Web Application
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/inback
EnvironmentFile=/var/www/inback/.env
ExecStart=/usr/bin/gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 120 main:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Файл `/etc/systemd/system/inback-bot.service`:
```ini
[Unit]
Description=InBack Telegram Bot
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/inback
EnvironmentFile=/var/www/inback/.env
ExecStart=/usr/bin/python3 run_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable inback-web inback-bot
systemctl start inback-web inback-bot
```

### Файл .env (создайте в корне проекта)

```env
# === ОБЯЗАТЕЛЬНЫЕ ===
SESSION_SECRET=сгенерируйте_через_openssl_rand_hex_32
DATABASE_URL=postgresql://user:password@localhost:5432/inback_db
ENABLE_SCHEDULER=true
SITE_URL=https://ваш-сайт.ru

# === TELEGRAM ===
TELEGRAM_BOT_TOKEN=токен_от_botfather
TELEGRAM_CHAT_ID=ваш_chat_id
TELEGRAM_BOT_USERNAME=Inback_bot
BOT_WEBHOOK_SECRET=любая_секретная_строка

# === DADATA ===
DADATA_API_KEY=token_из_личного_кабинета_dadata
DADATA_SECRET_KEY=secret_из_личного_кабинета_dadata

# === EMAIL (один из двух) ===
SENDGRID_API_KEY=SG.xxxxxxxxxxxx
# ИЛИ SMTP:
# EMAIL_HOST=smtp.gmail.com
# EMAIL_PORT=587
# EMAIL_USER=your@gmail.com
# EMAIL_PASSWORD=app_password

# === ЯНДЕКС КАРТЫ ===
YANDEX_MAPS_API_KEY=ваш_ключ
YANDEX_API_KEY=тот_же_ключ

# === SMS (хотя бы один) ===
TELEGRAM_GATEWAY_TOKEN=ваш_gateway_token
SMSC_LOGIN=ваш_логин
SMSC_PASSWORD=ваш_пароль

# === OAUTH (опционально) ===
GOOGLE_OAUTH_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxx
VK_CLIENT_ID=12345678
VK_CLIENT_SECRET=ваш_секрет
MAILRU_CLIENT_ID=ваш_id
MAILRU_CLIENT_SECRET=ваш_секрет

# === OPENAI (опционально) ===
OPENAI_API_KEY=sk-proj-xxxxx

# === VAPID (опционально) ===
VAPID_PUBLIC_KEY=BGfIV-...
VAPID_PRIVATE_KEY=2ru13v...

# === QR-коды (опционально) ===
QR_DOMAIN=https://ваш-сайт.ru
```

---

## 14. Проверочный чеклист

После настройки проверьте каждый пункт:

### Базовое

- [ ] Сайт открывается: `https://ваш-сайт.ru`
- [ ] Главная страница загружается (карточки объектов видны)
- [ ] Карта открывается (Яндекс Карты)
- [ ] Регистрация пользователя работает

### Telegram Bot

- [ ] Бот отвечает на `/start`
- [ ] Главное меню отображается с кнопками
- [ ] Тест: нажмите "💰 Как работает" — информация открывается
- [ ] Тест: нажмите "📝 Подать заявку" — форма из 4 шагов работает
- [ ] Тест: отправьте боту `/link НЕПРАВИЛЬНЫЙ_КОД` — бот отвечает ошибкой
- [ ] Владелец (TELEGRAM_CHAT_ID) получил уведомление о старте... нет такого, но при первой заявке — получит

### Менеджер: привязка Telegram

- [ ] Зайдите в профиль менеджера → раздел "Telegram-аккаунт" виден
- [ ] Нажмите "Получить код" → код появляется с таймером
- [ ] Отправьте `/link КОД` в бот → статус изменился на ✅ Привязан
- [ ] Менеджер видит панель в боте с кнопками "Онлайн/Офлайн"

### DaData

- [ ] Введите в поиск на сайте "Сочи, Курортный" — появляются подсказки из DaData
- [ ] В логах видно: `✅ DaData client initialized successfully`

### Email

- [ ] Зарегистрируйте нового пользователя — письмо подтверждения пришло
- [ ] В логах нет ошибок SendGrid/SMTP

### Планировщик (APScheduler)

- [ ] В логах видно: `Running job "Проверка новых объектов..."`
- [ ] Нет ошибок "scheduler not running"

---

## Где смотреть логи

```bash
# Systemd
journalctl -u inback-web -f
journalctl -u inback-bot -f

# Gunicorn напрямую
gunicorn --bind 0.0.0.0:5000 --workers 1 --log-level debug main:app

# Python бот напрямую
python run_bot.py
```

---

*Дата последнего обновления: май 2026*
*Версия: InBack/Clickback 2026*
