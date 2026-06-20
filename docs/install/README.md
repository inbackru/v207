# Руководство по установке платформы InBack / Clickback

## Полное развёртывание на новом сервере

---

## Оглавление

1. [Требования к серверу](#1-требования-к-серверу)
2. [Установка системных зависимостей](#2-установка-системных-зависимостей)
3. [PostgreSQL — настройка базы данных](#3-postgresql--настройка-базы-данных)
4. [Клонирование проекта](#4-клонирование-проекта)
5. [Python-окружение и зависимости](#5-python-окружение-и-зависимости)
6. [Переменные окружения и секретные ключи](#6-переменные-окружения-и-секретные-ключи)
7. [Инициализация базы данных](#7-инициализация-базы-данных)
8. [Настройка Gunicorn + systemd](#8-настройка-gunicorn--systemd)
9. [Nginx — обратный прокси и SSL](#9-nginx--обратный-прокси-и-ssl)
10. [Telegram-бот](#10-telegram-бот)
11. [Парсер CIAN / Telegram-промо](#11-парсер-cian--telegram-промо)
12. [Статические файлы и загрузки](#12-статические-файлы-и-загрузки)
13. [Резервное копирование](#13-резервное-копирование)
14. [Мониторинг и логи](#14-мониторинг-и-логи)
15. [Чек-лист запуска](#15-чек-лист-запуска)

---

## 1. Требования к серверу

| Параметр | Минимум | Рекомендуется |
|---|---|---|
| ОС | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| CPU | 2 ядра | 4+ ядра |
| RAM | 4 GB | 8+ GB |
| Диск | 40 GB SSD | 100+ GB SSD |
| Python | 3.10+ | 3.11 |
| PostgreSQL | 14+ | 16 |

> Платформа работает только на Linux. Windows не поддерживается.

---

## 2. Установка системных зависимостей

```bash
sudo apt update && sudo apt upgrade -y

# Базовые пакеты
sudo apt install -y \
  python3 python3-pip python3-venv python3-dev \
  postgresql postgresql-contrib libpq-dev \
  nginx certbot python3-certbot-nginx \
  git curl wget unzip unar \
  build-essential libssl-dev libffi-dev \
  libjpeg-dev libpng-dev libwebp-dev \
  wkhtmltopdf

# Node.js (для npm, если нужен фронтенд сборщик)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Google Chrome + Chromedriver (для Selenium/Playwright парсеров)
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list'
sudo apt update && sudo apt install -y google-chrome-stable

# Playwright (альтернатива Selenium)
pip install playwright
playwright install chromium
playwright install-deps

# WeasyPrint системные зависимости (PDF-генерация)
sudo apt install -y libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
  libgdk-pixbuf2.0-0 libffi-dev shared-mime-info
```

---

## 3. PostgreSQL — настройка базы данных

```bash
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Создаём пользователя и БД
sudo -u postgres psql << 'EOF'
CREATE USER inback_user WITH PASSWORD 'ЗАМЕНИ_НА_СЛОЖНЫЙ_ПАРОЛЬ';
CREATE DATABASE inbackdb OWNER inback_user;
GRANT ALL PRIVILEGES ON DATABASE inbackdb TO inback_user;
ALTER USER inback_user CREATEDB;
EOF
```

### Восстановление из дампа (если есть)

```bash
# Если дамп в RAR (v5) — используй unar:
unar backup.rar -o /tmp/restore/

# Восстановление
psql "postgresql://inback_user:ПАРОЛЬ@localhost/inbackdb" -f /tmp/restore/dump.sql

# Проверка
psql "postgresql://inback_user:ПАРОЛЬ@localhost/inbackdb" -c "
  SELECT
    (SELECT count(*) FROM residential_complexes) as complexes,
    (SELECT count(*) FROM properties) as properties,
    (SELECT count(*) FROM users) as users;
"
```

---

## 4. Клонирование проекта

```bash
# Создаём директорию
sudo mkdir -p /var/www/inback
sudo chown $USER:$USER /var/www/inback

# Клонируем
cd /var/www/inback
git clone https://github.com/YOUR_ORG/inback.git .
# ИЛИ копируем архив:
# tar -xzf inback_backup.tar.gz -C /var/www/inback/

# Структура должна выглядеть так:
# /var/www/inback/
#   app.py
#   main.py
#   models.py
#   requirements.txt (или pyproject.toml)
#   templates/
#   static/
#   scripts/
#   ...
```

---

## 5. Python-окружение и зависимости

```bash
cd /var/www/inback

# Создаём виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Устанавливаем зависимости
pip install --upgrade pip

# Если есть requirements.txt:
pip install -r requirements.txt

# Если только pyproject.toml:
pip install -e .

# Ключевые пакеты (если нет файла зависимостей):
pip install \
  flask flask-sqlalchemy flask-login \
  gunicorn psycopg2-binary \
  sqlalchemy alembic \
  requests httpx \
  selenium playwright undetected-chromedriver \
  beautifulsoup4 lxml \
  telethon \
  pillow weasyprint reportlab \
  openai \
  sendgrid \
  apscheduler \
  python-dotenv \
  werkzeug \
  flask-wtf \
  redis celery
```

---

## 6. Переменные окружения и секретные ключи

Создайте файл `/var/www/inback/.env`:

```bash
nano /var/www/inback/.env
```

Содержимое файла:

```env
# ========== ОБЯЗАТЕЛЬНЫЕ ==========

# Flask
SESSION_SECRET=ЗАМЕНИ_НА_ДЛИННУЮ_СЛУЧАЙНУЮ_СТРОКУ_64_СИМВОЛА

# База данных
DATABASE_URL=postgresql://inback_user:ПАРОЛЬ@localhost/inbackdb

# ========== TELEGRAM ==========

# Токен основного бота (получить у @BotFather)
TELEGRAM_BOT_TOKEN=1234567890:AABBCCDDaabbccddEEFFeegg

# Токен Telegram Gateway (для SMS через Telegram)
# https://gateway.telegram.org/
TELEGRAM_GATEWAY_TOKEN=ваш_gateway_token

# Для Telegram-парсера акций (получить на my.telegram.org)
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
TELEGRAM_BOT_USERNAME=@ваш_бот

# ========== EMAIL ==========

# SendGrid (https://sendgrid.com)
SENDGRID_API_KEY=SG.xxxxxxxxx

# ========== AI ==========

# OpenAI (https://platform.openai.com)
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx

# ========== КАРТЫ ==========

# Яндекс.Карты (https://developer.tech.yandex.ru)
YANDEX_MAPS_API_KEY=ваш_ключ_яндекс_карт

# ========== ДАННЫЕ ==========

# DaData (https://dadata.ru)
DADATA_API_KEY=ваш_dadata_api_key
DADATA_SECRET_KEY=ваш_dadata_secret_key

# RED SMS (резервный SMS-провайдер)
# REDSMS_API_KEY=ваш_ключ

# ========== OAUTH (опционально) ==========

# Google OAuth
# GOOGLE_OAUTH_CLIENT_ID=xxxx.apps.googleusercontent.com
# GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxx

# VK OAuth
# VK_CLIENT_ID=12345678
# VK_CLIENT_SECRET=ваш_vk_secret

# Mail.ru OAuth
# MAILRU_CLIENT_ID=ваш_mailru_id
# MAILRU_CLIENT_SECRET=ваш_mailru_secret

# ========== АНАЛИТИКА (опционально) ==========

# Google Analytics
# GA_MEASUREMENT_ID=G-XXXXXXXXXX

# LaunchDarkly (feature flags)
# LAUNCHDARKLY_SDK_KEY=sdk-xxxx

# reCAPTCHA
# RECAPTCHA_SITE_KEY=ваш_ключ
# RECAPTCHA_SECRET_KEY=ваш_секрет
```

### Защита файла .env

```bash
chmod 600 /var/www/inback/.env
chown www-data:www-data /var/www/inback/.env
```

### Как получить секретные ключи

| Ключ | Где получить |
|---|---|
| `SESSION_SECRET` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `TELEGRAM_BOT_TOKEN` | Написать @BotFather в Telegram |
| `TELEGRAM_API_ID/HASH` | https://my.telegram.org → API development tools (нужен мобильный браузер если есть VPN-ошибки) |
| `TELEGRAM_GATEWAY_TOKEN` | https://gateway.telegram.org/ → зарегистрировать |
| `SENDGRID_API_KEY` | https://app.sendgrid.com → Settings → API Keys |
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| `YANDEX_MAPS_API_KEY` | https://developer.tech.yandex.ru → Создать ключ → JS API |
| `DADATA_API_KEY` | https://dadata.ru → Профиль → API-ключи |

---

## 7. Инициализация базы данных

```bash
cd /var/www/inback
source venv/bin/activate

# Загружаем переменные окружения
export $(cat .env | grep -v '^#' | xargs)

# Инициализация таблиц (создаёт всё, чего нет в БД)
python3 -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('OK: все таблицы созданы')
"
```

---

## 8. Настройка Gunicorn + systemd

### Тест запуска

```bash
cd /var/www/inback
source venv/bin/activate
export $(cat .env | grep -v '^#' | xargs)
gunicorn --bind 0.0.0.0:5000 --workers 2 --reload main:app
# Откройте http://IP:5000 — сайт должен работать
# Ctrl+C чтобы остановить
```

### Создаём systemd-сервис

```bash
sudo nano /etc/systemd/system/inback.service
```

```ini
[Unit]
Description=InBack Flask Application
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/inback
EnvironmentFile=/var/www/inback/.env
ExecStart=/var/www/inback/venv/bin/gunicorn \
    --workers 4 \
    --bind unix:/var/www/inback/inback.sock \
    --access-logfile /var/log/inback/access.log \
    --error-logfile /var/log/inback/error.log \
    --timeout 120 \
    --reload \
    main:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Создаём директорию для логов
sudo mkdir -p /var/log/inback
sudo chown www-data:www-data /var/log/inback

# Задаём права на проект
sudo chown -R www-data:www-data /var/www/inback

# Активируем и запускаем
sudo systemctl daemon-reload
sudo systemctl enable inback
sudo systemctl start inback
sudo systemctl status inback
```

---

## 9. Nginx — обратный прокси и SSL

```bash
sudo nano /etc/nginx/sites-available/inback
```

```nginx
server {
    listen 80;
    server_name ваш-домен.ru www.ваш-домен.ru;

    # Максимальный размер загружаемых файлов (для фото ЖК)
    client_max_body_size 50M;

    # Статические файлы напрямую через Nginx (быстрее)
    location /static/ {
        alias /var/www/inback/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # Загрузки пользователей
    location /uploads/ {
        alias /var/www/inback/static/uploads/;
        expires 1d;
    }

    # Flask приложение
    location / {
        proxy_pass http://unix:/var/www/inback/inback.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/inback /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# SSL сертификат (Let's Encrypt)
sudo certbot --nginx -d ваш-домен.ru -d www.ваш-домен.ru
# Следуйте инструкциям certbot
```

---

## 10. Telegram-бот

```bash
sudo nano /etc/systemd/system/inback-bot.service
```

```ini
[Unit]
Description=InBack Telegram Bot
After=network.target inback.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/inback
EnvironmentFile=/var/www/inback/.env
ExecStart=/var/www/inback/venv/bin/python3 run_bot.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/inback/bot.log
StandardError=append:/var/log/inback/bot-error.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable inback-bot
sudo systemctl start inback-bot
```

---

## 11. Парсер CIAN / Telegram-промо

### Первичная авторизация Telegram-парсера

```bash
cd /var/www/inback
source venv/bin/activate
export $(cat .env | grep -v '^#' | xargs)

# Создаём папку для сессий
mkdir -p sessions

# Интерактивная авторизация (один раз!)
python3 scripts/telegram_auth_setup.py
# Введите номер телефона, затем код из Telegram
# Файл sessions/promo_parser.session будет создан
```

### Systemd-сервис парсера (если нужен непрерывный мониторинг)

```bash
sudo nano /etc/systemd/system/inback-parser.service
```

```ini
[Unit]
Description=InBack CIAN Parser
After=network.target postgresql.service

[Service]
User=www-data
WorkingDirectory=/var/www/inback
EnvironmentFile=/var/www/inback/.env
ExecStart=/var/www/inback/venv/bin/python3 -u scripts/run_city.py --city 1 --mode full
Restart=on-failure
RestartSec=60
StandardOutput=append:/var/log/inback/parser.log
StandardError=append:/var/log/inback/parser-error.log

[Install]
WantedBy=multi-user.target
```

### Cron для ежедневного парсинга

```bash
sudo crontab -u www-data -e
```

```cron
# Парсер CIAN — каждый день в 04:00
0 4 * * * /var/www/inback/venv/bin/python3 /var/www/inback/scripts/run_city.py --city 1 --mode full >> /var/log/inback/cian-cron.log 2>&1

# Парсер Telegram-акций — каждый день в 07:00
0 7 * * * /var/www/inback/venv/bin/python3 /var/www/inback/scripts/telegram_promo_parser.py >> /var/log/inback/tg-promo-cron.log 2>&1

# Обновление ближайших объектов — раз в неделю (воскресенье в 03:00)
0 3 * * 0 /var/www/inback/venv/bin/python3 /var/www/inback/scripts/update_complex_nearby.py >> /var/log/inback/nearby-cron.log 2>&1
```

---

## 12. Статические файлы и загрузки

```bash
# Создаём необходимые папки
mkdir -p /var/www/inback/static/uploads/{complexes,properties,developers,tg_promos,avatars}
mkdir -p /var/www/inback/static/images/banks

# Задаём права
sudo chown -R www-data:www-data /var/www/inback/static/uploads/
sudo chmod -R 755 /var/www/inback/static/uploads/
```

### Если переносите с другого сервера

```bash
# На старом сервере:
tar -czf uploads_backup.tar.gz /var/www/inback/static/uploads/

# На новом сервере:
scp user@старый-сервер:/var/www/inback/uploads_backup.tar.gz .
tar -xzf uploads_backup.tar.gz -C /
sudo chown -R www-data:www-data /var/www/inback/static/uploads/
```

---

## 13. Резервное копирование

### Скрипт резервного копирования БД

```bash
sudo nano /usr/local/bin/inback-backup.sh
```

```bash
#!/bin/bash
set -e

BACKUP_DIR="/var/backups/inback"
DATE=$(date +%Y%m%d_%H%M%S)
DB_URL="postgresql://inback_user:ПАРОЛЬ@localhost/inbackdb"

mkdir -p "$BACKUP_DIR"

# Дамп БД
pg_dump "$DB_URL" | gzip > "$BACKUP_DIR/db_${DATE}.sql.gz"

# Архив загрузок
tar -czf "$BACKUP_DIR/uploads_${DATE}.tar.gz" /var/www/inback/static/uploads/ 2>/dev/null || true

# Удаляем старые бэкапы (старше 30 дней)
find "$BACKUP_DIR" -name "*.gz" -mtime +30 -delete

echo "Backup complete: $DATE"
```

```bash
sudo chmod +x /usr/local/bin/inback-backup.sh

# Добавляем в cron (ежедневно в 02:00)
echo "0 2 * * * root /usr/local/bin/inback-backup.sh >> /var/log/inback/backup.log 2>&1" | sudo tee /etc/cron.d/inback-backup
```

---

## 14. Мониторинг и логи

```bash
# Статус всех сервисов
sudo systemctl status inback inback-bot

# Логи приложения (real-time)
sudo tail -f /var/log/inback/error.log

# Логи бота
sudo tail -f /var/log/inback/bot.log

# Логи Nginx
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# PostgreSQL
sudo tail -f /var/log/postgresql/postgresql-*.log

# Проверка сокета Gunicorn
ls -la /var/www/inback/inback.sock

# Перезапуск после изменений кода
sudo systemctl restart inback

# Принудительное обновление кода и перезапуск
cd /var/www/inback && git pull && sudo systemctl restart inback
```

---

## 15. Чек-лист запуска

Проверьте каждый пункт перед запуском в продакшн:

### Сервер и ОС
- [ ] Ubuntu 22.04+ установлена, обновлена
- [ ] Все системные пакеты установлены (см. раздел 2)
- [ ] Пользователь `www-data` имеет доступ к `/var/www/inback`

### База данных
- [ ] PostgreSQL запущен и работает
- [ ] Пользователь и БД созданы
- [ ] Дамп восстановлен или таблицы инициализированы через `db.create_all()`
- [ ] Проверены счётчики: complexes, developers, properties

### Переменные окружения (`.env`)
- [ ] `SESSION_SECRET` — установлен длинный случайный ключ
- [ ] `DATABASE_URL` — правильный connection string
- [ ] `TELEGRAM_BOT_TOKEN` — токен бота от @BotFather
- [ ] `SENDGRID_API_KEY` — ключ для отправки email
- [ ] `OPENAI_API_KEY` — ключ OpenAI (если используется AI-функционал)
- [ ] `YANDEX_MAPS_API_KEY` — ключ Яндекс.Карт
- [ ] `DADATA_API_KEY` / `DADATA_SECRET_KEY` — для проверки адресов

### Приложение
- [ ] `gunicorn` запускается без ошибок
- [ ] Systemd-сервис `inback` активен и работает
- [ ] Открывается главная страница по IP сервера

### Nginx + SSL
- [ ] Nginx запущен, конфиг проверен (`nginx -t`)
- [ ] SSL-сертификат получен через certbot
- [ ] Редирект с HTTP на HTTPS работает
- [ ] Статика отдаётся напрямую через Nginx

### Telegram
- [ ] Бот (`inback-bot`) запущен
- [ ] Бот отвечает на `/start`
- [ ] Для парсера акций: авторизация выполнена, файл `sessions/promo_parser.session` существует

### Парсеры и задачи
- [ ] Cron настроен для ежедневного парсинга
- [ ] Папка `static/uploads/` существует с правами `www-data`

### Безопасность
- [ ] Файл `.env` имеет права `600`
- [ ] Администраторский URL защищён (не `/admin` в открытом доступе)
- [ ] Firewall: открыты только порты 80, 443, 22

---

## Быстрые команды

```bash
# Перезапустить приложение
sudo systemctl restart inback

# Посмотреть ошибки Flask
sudo journalctl -u inback -n 50 --no-pager

# Подключиться к БД
psql "postgresql://inback_user:ПАРОЛЬ@localhost/inbackdb"

# Запустить парсер вручную (Краснодар)
cd /var/www/inback && source venv/bin/activate && \
  python3 scripts/run_city.py --city 1 --mode full

# Запустить парсер Telegram-акций вручную
cd /var/www/inback && source venv/bin/activate && \
  python3 scripts/telegram_promo_parser.py

# Обновить код с git и перезапустить
cd /var/www/inback && git pull origin main && \
  sudo systemctl restart inback inback-bot
```

---

*Создано: июнь 2026. Актуально для Python 3.11, PostgreSQL 16, Ubuntu 22/24.*
