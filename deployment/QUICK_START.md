# ⚡ Быстрый старт InBack

## 🎯 Для нетерпеливых

### На Replit (рекомендуется)

```bash
# 1. Импортируйте проект
https://replit.com/import/github

# 2. Создайте базу данных
Tools → Database → Create PostgreSQL

# 3. Добавьте секреты
Tools → Secrets → Add:
- TELEGRAM_BOT_TOKEN
- MANAGER_TELEGRAM_IDS
- SENDGRID_API_KEY

# 4. Нажмите Run ▶️
Готово! 🎉
```

---

### Локально (5 минут)

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/ВАШ_ПОЛЬЗОВАТЕЛЬ/inback.git
cd inback

# 2. Установите зависимости
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 3. Создайте базу данных PostgreSQL
sudo -u postgres psql
CREATE DATABASE inback_db;
CREATE USER inback_user WITH PASSWORD 'password';
GRANT ALL PRIVILEGES ON DATABASE inback_db TO inback_user;
\q

# 4. Настройте переменные окружения
cp deployment/.env.example .env
# Отредактируйте .env - добавьте свои ключи

# 5. Запустите
gunicorn --bind 0.0.0.0:5000 --reload main:app

# Откройте http://localhost:5000
```

---

## 🔑 Минимальные требования

### Обязательно нужны:
- ✅ PostgreSQL база данных
- ✅ Python 3.11+
- ✅ Переменные: `DATABASE_URL`, `SESSION_SECRET`

### Опционально (для полной функциональности):
- 📱 `TELEGRAM_BOT_TOKEN` - уведомления в Telegram
- ✉️ `SENDGRID_API_KEY` - email уведомления

---

## 📋 Проверочный список

После установки проверьте:

```bash
# ✅ База данных подключена
psql $DATABASE_URL -c "SELECT 1;"

# ✅ Таблицы созданы
psql $DATABASE_URL -c "\dt"

# ✅ Приложение запускается
curl http://localhost:5000

# ✅ Секреты настроены
echo $TELEGRAM_BOT_TOKEN
echo $DATABASE_URL
```

---

## 🆘 Проблемы?

| Проблема | Решение |
|----------|---------|
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| `Database connection failed` | Проверьте `DATABASE_URL` |
| `Tables not found` | Перезапустите приложение - таблицы создадутся автоматически |
| `Port 5000 already in use` | `pkill -f gunicorn` или используйте другой порт |

---

## 📚 Полная документация

Смотрите [README.md](README.md) для подробных инструкций.

---

**Готово!** Теперь можно работать с платформой InBack 🏠
