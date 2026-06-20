# Руководство по развёртыванию InBack на новом сервере

## Требования к серверу

- **ОС**: Ubuntu 22.04 / Debian 12 (рекомендуется)
- **RAM**: минимум 2 GB (рекомендуется 4 GB)
- **CPU**: 2+ ядра
- **Диск**: 20+ GB (для фото с наш.дом.рф и баз данных)
- **Python**: 3.11+
- **PostgreSQL**: 15+
- **Node.js**: 20+ (для mockup-sandbox, опционально)

---

## 1. Установка системных зависимостей

```bash
sudo apt update && sudo apt upgrade -y

# Python и pip
sudo apt install -y python3.11 python3.11-venv python3.11-dev python3-pip

# PostgreSQL
sudo apt install -y postgresql postgresql-contrib

# Chromium + Chromedriver (для Selenium/Playwright обогатителей)
sudo apt install -y chromium-browser chromium-chromedriver

# Зависимости для WeasyPrint (PDF)
sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
  libfontconfig1 libcairo2 libgdk-pixbuf2.0-0 shared-mime-info

# Зависимости для Pillow (изображения)
sudo apt install -y libjpeg-dev libpng-dev libwebp-dev

# Unrar (для распаковки архивов)
sudo apt install -y unrar-free p7zip-full

# Прочее
sudo apt install -y git curl wget build-essential libssl-dev libffi-dev
```

---

## 2. Создание пользователя и клонирование проекта

```bash
# Создаём пользователя
sudo adduser inback
sudo usermod -aG sudo inback
su - inback

# Клонируем проект (или копируем файлы)
git clone https://your-repo-url.git /home/inback/app
# ИЛИ
# scp -r user@old-server:/path/to/project /home/inback/app

cd /home/inback/app
```

---

## 3. Виртуальное окружение Python и зависимости

```bash
cd /home/inback/app

# Создаём виртуальное окружение
python3.11 -m venv venv
source venv/bin/activate

# Устанавливаем зависимости
pip install --upgrade pip wheel
pip install -r requirements.txt

# Playwright (если используется)
playwright install chromium
playwright install-deps chromium
```

---

## 4. База данных PostgreSQL

```bash
# Создаём пользователя и базу
sudo -u postgres psql << 'EOF'
CREATE USER inback WITH PASSWORD 'ЗАМЕНИТЕ_НА_СЛОЖНЫЙ_ПАРОЛЬ';
CREATE DATABASE inbackdb OWNER inback ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE inbackdb TO inback;
\q
EOF
```

### 4.1 Восстановление данных из дампа (если есть)

```bash
# Дамп должен быть получен с предыдущего сервера:
# pg_dump -h old_host -U postgres -d old_db > backup.sql

psql -h localhost -U inback -d inbackdb < backup.sql
```

### 4.2 Первый запуск без дампа (пустая БД)

```bash
# Схема создаётся автоматически при запуске app.py через db.create_all()
# Достаточно запустить приложение один раз
python3 main.py
# Ctrl+C после "Database tables created successfully!"
```

---

## 5. Переменные окружения (.env)

Создайте файл `/home/inback/app/.env` или экспортируйте переменные:

```bash
cat > /home/inback/app/.env << 'EOF'
# Обязательные
DATABASE_URL=postgresql://inback:ПАРОЛЬ@localhost/inbackdb
SESSION_SECRET=ДЛИННАЯ_СЛУЧАЙНАЯ_СТРОКА_МИНИМУМ_32_СИМВОЛА

# Telegram
TELEGRAM_BOT_TOKEN=токен_от_BotFather
TELEGRAM_GATEWAY_TOKEN=токен_gateway
TELEGRAM_BOT_USERNAME=имя_бота

# Email
SENDGRID_API_KEY=ключ_sendgrid

# ИИ
OPENAI_API_KEY=ключ_openai

# Карты и геокодинг
YANDEX_MAPS_API_KEY=ключ_yandex
DADATA_API_KEY=ключ_dadata
DADATA_SECRET_KEY=секрет_dadata

# SMS (резервный)
RED_SMS_LOGIN=логин
RED_SMS_API_KEY=ключ

# Настройки
ENABLE_SCHEDULER=true
TEST_SMS_MODE=false
EOF

chmod 600 .env
```

### Загрузка .env при запуске

Добавьте в начало вашего systemd-сервиса или используйте `python-dotenv`:

```bash
pip install python-dotenv
```

Или экспортируйте переменные:
```bash
export $(cat .env | grep -v '^#' | xargs)
```

---

## 6. Настройка Gunicorn + Systemd

### Создаём systemd-сервис для веб-приложения

```bash
sudo nano /etc/systemd/system/inback.service
```

```ini
[Unit]
Description=InBack Flask Application
After=network.target postgresql.service

[Service]
Type=notify
User=inback
Group=inback
WorkingDirectory=/home/inback/app
EnvironmentFile=/home/inback/app/.env
ExecStart=/home/inback/app/venv/bin/gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    --worker-class sync \
    --timeout 120 \
    --keepalive 5 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --log-level info \
    --access-logfile /var/log/inback/access.log \
    --error-logfile /var/log/inback/error.log \
    main:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Создаём директорию для логов
sudo mkdir -p /var/log/inback
sudo chown inback:inback /var/log/inback

# Включаем и запускаем
sudo systemctl daemon-reload
sudo systemctl enable inback
sudo systemctl start inback
sudo systemctl status inback
```

### Telegram-бот как отдельный сервис

```bash
sudo nano /etc/systemd/system/inback-bot.service
```

```ini
[Unit]
Description=InBack Telegram Bot
After=network.target inback.service

[Service]
User=inback
WorkingDirectory=/home/inback/app
EnvironmentFile=/home/inback/app/.env
ExecStart=/home/inback/app/venv/bin/python3 run_bot.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable inback-bot
sudo systemctl start inback-bot
```

---

## 7. Обогатители (cron / systemd-timer)

### 7.1 Обогатитель ЦИАН (enrich_complexes.py)

Настройка через cron (запуск каждое воскресенье в 02:00):

```bash
crontab -e
```

```cron
# Полный прогон ЦИАН - Краснодар (воскресенье 02:00)
0 2 * * 0 cd /home/inback/app && /home/inback/app/venv/bin/python3 -u scripts/run_city.py --city 1 --mode full >> /var/log/inback/cian_city1.log 2>&1

# Обновление цен ЦИАН - Краснодар (пн-сб 06:00)
0 6 * * 1-6 cd /home/inback/app && /home/inback/app/venv/bin/python3 -u scripts/run_city.py --city 1 --mode prices >> /var/log/inback/cian_prices.log 2>&1

# Обогащение наш.дом.рф - Краснодар (понедельник 03:00)
0 3 * * 1 cd /home/inback/app && /home/inback/app/venv/bin/python3 -u scripts/nashdom_scraper.py --city 1 >> /var/log/inback/nashdom.log 2>&1

# Обновление nearby (инфраструктура ЖК) - среда 03:00
0 3 * * 3 cd /home/inback/app && /home/inback/app/venv/bin/python3 -u scripts/update_complex_nearby.py >> /var/log/inback/nearby.log 2>&1
```

### 7.2 Наш.дом.рф обогатитель: важные примечания

**Как работает:**
1. Скачивает все здания города с `xn--80az8a.xn--d1aqf.xn--p1ai` (наш.дом.рф)
2. Сопоставляет ЖК по названию (нечёткое сравнение, порог 50%)
3. Для каждого совпавшего ЖК:
   - Скачивает чистое фото (без водяных знаков) в `/static/uploads/nashdom_photos/`
   - Сохраняет в `residential_complexes.nashdom_photos` (JSON-массив)
   - Заменяет `main_image` если текущее с CIAN
   - Создаёт/обновляет записи литеров в `buildings` через `ON CONFLICT`
   - Сохраняет ИНН/ОГРН застройщика

**Дедупликация зданий:**
- Ключ: `(complex_id, building_id)` — уникальный индекс
- Повторный запуск обновляет поля, не создаёт дубликаты

**Фото — логика выбора:**
- Берётся `hobjRenderPhotoUrl` первого здания с фото
- Скачивается локально в `static/uploads/nashdom_photos/rc{id}_{hash}.jpg`
- `main_image` заменяется только если текущее содержит 'cian' в URL
- В `nashdom_photos` всегда записывается актуальное фото (JSON-массив)

---

## 8. Nginx (обратный прокси)

```bash
sudo apt install -y nginx

sudo nano /etc/nginx/sites-available/inback
```

```nginx
server {
    listen 80;
    server_name yourdomain.ru www.yourdomain.ru;

    client_max_body_size 50M;

    location /static/ {
        alias /home/inback/app/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_read_timeout 120s;
        proxy_buffering on;
        proxy_buffer_size 8k;
        proxy_buffers 16 8k;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/inback /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### SSL через Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.ru -d www.yourdomain.ru
```

---

## 9. Перенос файлов (статика, фото)

```bash
# С текущего сервера (Replit) на новый
# Перенос nashdom фото
scp -r /home/inback/app/static/uploads/ user@new-server:/home/inback/app/static/

# Перенос загруженных файлов
scp -r /home/inback/app/static/uploads/properties/ user@new-server:/home/inback/app/static/uploads/
```

---

## 10. Проверка после запуска

```bash
# Статус всех сервисов
sudo systemctl status inback inback-bot nginx postgresql

# Логи приложения
journalctl -u inback -f

# Проверка доступности
curl http://localhost:5000/health

# Тест nashdom
cd /home/inback/app
source venv/bin/activate
python3 scripts/test_nashdom.py --test db

# Тест обогатителя (сухой прогон, без записи в БД)
python3 scripts/nashdom_scraper.py --city 1 --limit 3 --dry-run
```

---

## 11. Частые проблемы

| Проблема | Решение |
|----------|---------|
| `ModuleNotFoundError` | `source venv/bin/activate` + `pip install -r requirements.txt` |
| `psycopg2.OperationalError` | Проверьте `DATABASE_URL` и доступность PostgreSQL |
| WeasyPrint не генерирует PDF | `sudo apt install -y libpango-1.0-0 libcairo2` |
| Selenium/Playwright не запускается | `playwright install-deps chromium` |
| `nashdom_photos` не скачиваются | Проверьте доступность `xn--80az8a.xn--d1aqf.xn--p1ai` |
| Ошибка CSRF | Проверьте `SESSION_SECRET` в `.env` |
| APScheduler не запускается | Проверьте `ENABLE_SCHEDULER=true` в env |

---

## 12. Резервное копирование

```bash
# Дамп БД (ежедневно)
crontab -e
```

```cron
# Ежедневный дамп БД в 01:00
0 1 * * * pg_dump -h localhost -U inback inbackdb | gzip > /backup/db_$(date +\%Y\%m\%d).sql.gz
# Удаляем дампы старше 30 дней
0 2 * * * find /backup -name "db_*.sql.gz" -mtime +30 -delete
```

---

## Контакты и ресурсы

- Наш.дом.рф API: `xn--80az8a.xn--d1aqf.xn--p1ai/api/ng/object`
- ЦИАН API: через скрипт `scripts/enrich_complexes.py`
- Админ-панель: `/admin/enrichment` (логин администратора)
- Тесты: `python3 scripts/test_nashdom.py`
