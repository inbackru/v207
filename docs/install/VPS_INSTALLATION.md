# Установка InBack на VPS — пошаговая инструкция

## Требования к серверу

- Ubuntu 22.04 LTS (рекомендуется) или Debian 12
- RAM: от 2 GB (рекомендуется 4 GB)
- Disk: от 20 GB SSD
- Python 3.11+
- PostgreSQL 14+
- Nginx

---

## 1. Базовая настройка сервера

```bash
# Обновить систему
sudo apt update && sudo apt upgrade -y

# Установить базовые пакеты
sudo apt install -y git python3.11 python3.11-venv python3.11-dev \
    build-essential libpq-dev nginx certbot python3-certbot-nginx \
    postgresql postgresql-contrib supervisor

# Проверить версию Python
python3.11 --version
```

---

## 2. База данных PostgreSQL

```bash
# Запустить PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Создать пользователя и базу данных
sudo -u postgres psql << 'EOF'
CREATE USER inback_user WITH PASSWORD 'ВАШ_НАДЁЖНЫЙ_ПАРОЛЬ';
CREATE DATABASE inback_db OWNER inback_user;
GRANT ALL PRIVILEGES ON DATABASE inback_db TO inback_user;
\q
EOF
```

**Сохраните строку подключения:**
```
DATABASE_URL=postgresql://inback_user:ВАШ_НАДЁЖНЫЙ_ПАРОЛЬ@localhost:5432/inback_db
```

---

## 3. Клонирование и настройка приложения

```bash
# Создать директорию
sudo mkdir -p /var/www/inback
sudo chown $USER:$USER /var/www/inback
cd /var/www/inback

# Клонировать репозиторий
git clone https://github.com/ВАШ_ЮЗЕ/inback.git .
# ИЛИ скопировать файлы через scp/rsync с вашего компьютера:
# rsync -avz --exclude='.git' --exclude='__pycache__' ./local_dir/ user@SERVER_IP:/var/www/inback/

# Создать виртуальное окружение
python3.11 -m venv venv
source venv/bin/activate

# Установить зависимости
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 4. Файл секретов (.env)

Создайте файл `/var/www/inback/.env` со всеми переменными окружения:

```bash
sudo nano /var/www/inback/.env
```

Вставьте следующее (заполните своими значениями):

```env
# ═══ ОБЯЗАТЕЛЬНЫЕ ═══════════════════════════════════════════

# База данных PostgreSQL
DATABASE_URL=postgresql://inback_user:ПАРОЛЬ@localhost:5432/inback_db

# Секретный ключ Flask (сгенерируйте: python3 -c "import secrets; print(secrets.token_hex(32))")
SESSION_SECRET=ВАШЕ_СЛУЧАЙНОЕ_ЗНАЧЕНИЕ_32_СИМВОЛА

# ═══ УВЕДОМЛЕНИЯ О ЗАЯВКАХ (важно!) ══════════════════════════

# Telegram-бот для получения заявок
# Получить у @BotFather: /newbot
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ

# Ваш Telegram chat_id (узнать: написать боту @userinfobot)
TELEGRAM_CHAT_ID=730764738

# Telegram ID всех менеджеров через запятую (получить у @userinfobot)
MANAGER_TELEGRAM_IDS=730764738,987654321

# ═══ EMAIL-УВЕДОМЛЕНИЯ (выберите один вариант) ════════════════

# Вариант А — SendGrid (рекомендуется для продакшна)
SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxxxxxx
EMAIL_FROM=noreply@ваш-домен.ru

# Вариант Б — Gmail SMTP
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=ваш-email@gmail.com
EMAIL_PASSWORD=пароль-приложения-gmail  # не основной пароль!

# Куда слать уведомления о заявках (email менеджера/админа)
ADMIN_EMAIL=admin@ваш-домен.ru

# ═══ КАРТЫ И ГЕОКОДИРОВАНИЕ ══════════════════════════════════

# Яндекс.Карты (для интерактивных карт)
YANDEX_MAPS_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxx

# DaData (нормализация адресов, необязательно)
DADATA_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DADATA_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ═══ СОЦИАЛЬНЫЕ СЕТИ (OAuth-авторизация, необязательно) ══════

GOOGLE_CLIENT_ID=xxxxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
VK_CLIENT_ID=12345678
VK_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
MAILRU_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxx
MAILRU_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx

# ═══ ОБОГАЩЕНИЕ ДАННЫХ (необязательно) ═══════════════════════

# Прокси для обращений к ЦИАН (без него скрапер не работает!)
ENRICH_PROXY_URL=http://user:password@proxy-host:port

# ═══ ФОНОВЫЕ ЗАДАЧИ ══════════════════════════════════════════

ENABLE_SCHEDULER=true

# ═══ ПРОЧЕЕ ══════════════════════════════════════════════════

FLASK_ENV=production
```

**Защитите файл секретов:**
```bash
chmod 600 /var/www/inback/.env
chown www-data:www-data /var/www/inback/.env
```

---

## 5. Загрузка переменных окружения

Отредактируйте `/var/www/inback/app.py` — убедитесь, что в начале файла есть загрузка `.env`:

```python
from dotenv import load_dotenv
load_dotenv()  # загружает .env файл
```

Установите python-dotenv если нет:
```bash
pip install python-dotenv
```

**ИЛИ** экспортируйте переменные через systemd (см. шаг 7).

---

## 6. Инициализация базы данных

```bash
cd /var/www/inback
source venv/bin/activate

# Создать все таблицы
python3 -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('Таблицы созданы')
"
```

---

## 7. Systemd — автозапуск приложения

Создайте файл сервиса:

```bash
sudo nano /etc/systemd/system/inback.service
```

```ini
[Unit]
Description=InBack Real Estate Platform
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/inback
EnvironmentFile=/var/www/inback/.env
ExecStart=/var/www/inback/venv/bin/gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 3 \
    --timeout 120 \
    --keep-alive 5 \
    --reuse-port \
    main:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Активировать и запустить
sudo systemctl daemon-reload
sudo systemctl enable inback
sudo systemctl start inback

# Проверить статус
sudo systemctl status inback

# Посмотреть логи
sudo journalctl -u inback -f
```

---

## 8. Nginx — веб-сервер и SSL

```bash
sudo nano /etc/nginx/sites-available/inback
```

```nginx
server {
    listen 80;
    server_name ваш-домен.ru www.ваш-домен.ru;

    # Редирект на HTTPS (раскомментировать после настройки SSL)
    # return 301 https://$host$request_uri;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
    }

    # Статические файлы — отдаём напрямую через Nginx (быстрее)
    location /static/ {
        alias /var/www/inback/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # Загруженные медиафайлы
    location /uploads/ {
        alias /var/www/inback/static/uploads/;
        expires 30d;
    }

    client_max_body_size 20M;
}
```

```bash
# Включить конфиг
sudo ln -s /etc/nginx/sites-available/inback /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### SSL (Let's Encrypt — бесплатный HTTPS)

```bash
sudo certbot --nginx -d ваш-домен.ru -d www.ваш-домен.ru

# Авторобновление
sudo systemctl enable certbot.timer
```

---

## 9. Права на папки

```bash
sudo chown -R www-data:www-data /var/www/inback
sudo chmod -R 755 /var/www/inback
sudo chmod -R 775 /var/www/inback/static/uploads
```

---

## 10. Брандмауэр

```bash
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

---

## 11. Проверка работоспособности

```bash
# Приложение запущено?
curl -I http://localhost:5000/

# Nginx работает?
curl -I http://ваш-домен.ru/

# Логи приложения
sudo journalctl -u inback -n 50

# Логи Nginx
sudo tail -f /var/log/nginx/error.log
```

---

## Обновление приложения

```bash
cd /var/www/inback
git pull origin main             # или rsync новых файлов
source venv/bin/activate
pip install -r requirements.txt  # если изменились зависимости
sudo systemctl restart inback
```

---

## Частые проблемы

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `502 Bad Gateway` | Gunicorn не запущен | `sudo systemctl status inback` |
| `connection refused :5000` | Gunicorn упал | `sudo journalctl -u inback -n 30` |
| `password authentication failed` | Неверный DATABASE_URL | Проверить пароль в `.env` |
| Пустая БД | Не запущен `db.create_all()` | Выполнить шаг 6 |
| Нет уведомлений | Не заданы TELEGRAM_BOT_TOKEN или EMAIL_* | Заполнить `.env` по шагу 4 |
