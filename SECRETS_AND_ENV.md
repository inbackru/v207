# Секреты и переменные окружения InBack

При переносе сайта на новый сервер нужно настроить следующие переменные окружения.
В Replit они задаются через вкладку **Secrets** (замочек в левой панели).
На обычном сервере — через `.env` файл или переменные окружения системы.

---

## 1. Обязательные (сайт не запустится без них)

| Переменная | Описание | Где получить |
|---|---|---|
| `DATABASE_URL` | Строка подключения к PostgreSQL | `postgresql://user:password@host:5432/dbname` |
| `SESSION_SECRET` | Секретный ключ Flask для сессий | Любая случайная строка (минимум 32 символа). Генерация: `python3 -c "import secrets; print(secrets.token_hex(32))"` |

---

## 2. Telegram (уведомления + бот)

| Переменная | Описание | Где получить |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота | Через [@BotFather](https://t.me/BotFather) → `/newbot` или `/mybots` |
| `TELEGRAM_CHAT_ID` | ID чата для уведомлений | Отправьте боту сообщение, затем откройте `https://api.telegram.org/bot<TOKEN>/getUpdates` — chat.id |
| `TELEGRAM_BOT_USERNAME` | Имя бота (без @) | По умолчанию `InBackBot`. Менять только если создали нового бота |
| `MANAGER_TELEGRAM_IDS` | Telegram ID менеджеров (через запятую) | Каждый менеджер пишет [@userinfobot](https://t.me/userinfobot) и получает свой ID |
| `TELEGRAM_GATEWAY_TOKEN` | Токен для Telegram Gateway (верификация) | [Telegram Gateway](https://gateway.telegram.org) |

---

## 3. Email / SendGrid

| Переменная | Описание | Где получить |
|---|---|---|
| `SENDGRID_API_KEY` | API-ключ SendGrid | [sendgrid.com](https://sendgrid.com) → Settings → API Keys → Create |
| `EMAIL_HOST` | SMTP-сервер (если не SendGrid) | По умолчанию `smtp.gmail.com` |
| `EMAIL_PORT` | Порт SMTP | По умолчанию `587` |
| `EMAIL_USER` | Email-адрес отправителя | Ваш email |
| `EMAIL_PASSWORD` | Пароль приложения | Для Gmail: Google Account → Безопасность → Пароли приложений |

---

## 4. SMS (RedSMS)

| Переменная | Описание | Где получить |
|---|---|---|
| `REDSMS_LOGIN` (или `RED_SMS_LOGIN`) | Логин RedSMS | [redsms.ru](https://redsms.ru) → Личный кабинет → API |
| `REDSMS_API_KEY` (или `RED_SMS_API_KEY`) | API-ключ RedSMS | Там же, в разделе API |
| `TEST_SMS_MODE` | Тестовый режим (SMS не отправляются) | Установите `true` для тестирования |

---

## 5. Карты (Яндекс)

| Переменная | Описание | Где получить |
|---|---|---|
| `YANDEX_MAPS_API_KEY` | Ключ Яндекс.Карт JavaScript API | [developer.tech.yandex.ru](https://developer.tech.yandex.ru/) → Кабинет → Подключить API → JavaScript API и HTTP Геокодер |

---

## 6. DaData (подсказки адресов)

| Переменная | Описание | Где получить |
|---|---|---|
| `DADATA_API_KEY` | API-ключ DaData | [dadata.ru](https://dadata.ru) → Личный кабинет → API-ключи |
| `DADATA_SECRET_KEY` | Секретный ключ (необязательный) | Там же |

---

## 7. Авторизация через соцсети (OAuth)

### Google
| Переменная | Описание | Где получить |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | Client ID | [console.cloud.google.com](https://console.cloud.google.com) → APIs & Services → Credentials → OAuth 2.0 Client IDs |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Client Secret | Там же |

### ВКонтакте
| Переменная | Описание | Где получить |
|---|---|---|
| `VK_CLIENT_ID` | ID приложения | [dev.vk.com](https://dev.vk.com) → Мои приложения → Создать → Веб-сайт |
| `VK_CLIENT_SECRET` | Защищённый ключ | Там же, в настройках приложения |

### Mail.ru
| Переменная | Описание | Где получить |
|---|---|---|
| `MAILRU_CLIENT_ID` | Client ID | [o2.mail.ru](https://o2.mail.ru/app) → Создать приложение |
| `MAILRU_CLIENT_SECRET` | Client Secret | Там же |

---

## 8. AI-функции (необязательно)

| Переменная | Описание | Где получить |
|---|---|---|
| `OPENAI_API_KEY` | Ключ OpenAI API | [platform.openai.com](https://platform.openai.com/api-keys) → Create new secret key |

---

## 9. Служебные переменные

| Переменная | Описание | Значение |
|---|---|---|
| `ENABLE_SCHEDULER` | Включить фоновые задачи (обход цен, оповещения) | `true` или не задавать (включён по умолчанию) |
| `QR_DOMAIN` | Домен для QR-кодов | Ваш домен сайта |
| `REPLIT_DEV_DOMAIN` | Домен Replit (автоматически) | Задаётся Replit автоматически |

---

## Как добавить секреты

### В Replit
1. Откройте проект
2. Нажмите на замочек (Secrets) в левой панели
3. Добавьте каждую переменную: Ключ → Значение → Add

### На обычном сервере (VPS / хостинг)

**Вариант 1: Файл `.env` в корне проекта**
```
DATABASE_URL=postgresql://user:password@localhost:5432/inback
SESSION_SECRET=your-random-secret-key-here
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890
SENDGRID_API_KEY=SG.xxxxxxxxxxxx
REDSMS_LOGIN=your_login
REDSMS_API_KEY=your_api_key
YANDEX_MAPS_API_KEY=your_key
DADATA_API_KEY=your_key
```

Для загрузки `.env` в Flask используйте `python-dotenv`:
```bash
pip install python-dotenv
```
Добавьте в начало `app.py`:
```python
from dotenv import load_dotenv
load_dotenv()
```

**Вариант 2: Системные переменные (systemd)**
В файле сервиса `/etc/systemd/system/inback.service`:
```ini
[Service]
Environment="DATABASE_URL=postgresql://..."
Environment="SESSION_SECRET=..."
Environment="TELEGRAM_BOT_TOKEN=..."
```

**Вариант 3: Nginx + Gunicorn**
В конфигурации Gunicorn или в скрипте запуска:
```bash
export DATABASE_URL="postgresql://..."
export SESSION_SECRET="..."
gunicorn --bind 0.0.0.0:5000 main:app
```

---

## Минимальный набор для запуска

Если нужно быстро запустить сайт без всех интеграций:

1. `DATABASE_URL` — без базы ничего не работает
2. `SESSION_SECRET` — без него не работают сессии и авторизация

Всё остальное опционально — сайт запустится, но соответствующие функции будут отключены (SMS, email, Telegram, карты и т.д.).
