# Настройка уведомлений о заявках — InBack

Когда клиент оставляет заявку на сайте, система отправляет уведомление в **Telegram** и на **email**.

---

## Часть 1: Уведомления о заявках клиентов

### 1.1 Telegram-уведомления о новых заявках

**Шаг 1. Создать Telegram-бота**

1. Напишите [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте команду `/newbot`
3. Введите название бота (например: `InBack Заявки`)
4. Введите имя пользователя (например: `inback_leads_bot`)
5. BotFather выдаст токен вида: `1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ`

**Шаг 2. Узнать ваш Telegram chat_id**

1. Напишите боту [@userinfobot](https://t.me/userinfobot) — он ответит вашим ID
2. Или после создания бота напишите ему любое сообщение, затем откройте:
   `https://api.telegram.org/bot<ВАШ_ТОКЕН>/getUpdates`
   В ответе найдите `"chat":{"id":XXXXX}` — это ваш chat_id

**Шаг 3. Переменные окружения**

На **Replit** (в Secrets):
```
TELEGRAM_BOT_TOKEN = 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID = 730764738
MANAGER_TELEGRAM_IDS = 730764738,987654321
```

На **VPS** (файл `/var/www/inback/.env`):
```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=730764738
MANAGER_TELEGRAM_IDS=730764738,987654321
```

**Что будет приходить в Telegram:**
```
🏠 НОВАЯ ЗАЯВКА НА ПОДБОР ЖИЛЬЯ

👤 КОНТАКТНАЯ ИНФОРМАЦИЯ:
• Имя: Иван Иванов
• Телефон: +7 900 123-45-67
• Email: ivan@mail.ru

🏢 ИНТЕРЕСУЮЩАЯ КВАРТИРА:
• Объект: 2-комн, 65 м²
• ЖК: Самолёт
• Цена: 7 500 000 руб.
💰 Потенциальный кэшбек: 225 000 руб. (3%)
```

---

### 1.2 Email-уведомления о новых заявках

Email отправляется менеджеру, закреплённому за клиентом. Система сначала пробует SendGrid, затем SMTP.

**Вариант А — SendGrid (рекомендуется)**

1. Зарегистрируйтесь на [sendgrid.com](https://sendgrid.com) (бесплатно до 100 писем/день)
2. Settings → API Keys → Create API Key → Full Access
3. Верифицируйте домен или email отправителя

```env
SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxxxxxx
EMAIL_FROM=noreply@inback.ru
```

**Вариант Б — Gmail SMTP**

1. Включите двухфакторную аутентификацию на Gmail
2. Google Account → Безопасность → Пароли приложений → Создать для «InBack»
3. Скопируйте 16-значный пароль (без пробелов)

```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=ваш-email@gmail.com
EMAIL_PASSWORD=abcdefghijklmnop
```

---

## Типы заявок и кто получает уведомление

| Тип заявки | Telegram | Email |
|------------|----------|-------|
| Заявка на подбор жилья (`/api/application`) | ✅ MANAGER_TELEGRAM_IDS | ✅ Email менеджера из БД |
| Заявка на бронирование (`/api/booking`) | ✅ TELEGRAM_CHAT_ID | ✅ Email менеджера из БД |
| Callback-запрос (`/api/callback-request`) | ✅ Через app.py | ✅ Через app.py |

---

## Часть 2: Уведомления о новых объектах (для подписчиков)

Система также отправляет пользователям уведомления о новых объектах по их сохранённым поискам.

### Типы:
- **Мгновенные** — в течение 5 минут после появления нового объекта (лимит 15/день)
- **Ежедневные** — сводка в 8:00 утра
- **Еженедельные** — сводка по понедельникам в 8:00

### Активация:
Требует `ENABLE_SCHEDULER=true` в переменных окружения — APScheduler запускает фоновые задачи.

---

## Проверка без настройки (режим разработки)

Если переменные не заданы — система **не падает**, а пишет в консоль:
```
📧 Email not configured (no EMAIL_USER/EMAIL_PASSWORD). Would send to manager@email.ru: Новая заявка
```
Telegram тоже молча пропускается если нет `TELEGRAM_BOT_TOKEN`.

---

## Устранение проблем

**Telegram не приходит:**
1. Убедитесь что токен точный (без пробелов)
2. Напишите своему боту хотя бы одно сообщение — бот не пишет первым без инициализации чата
3. TELEGRAM_CHAT_ID — это число (ваш chat_id), не имя пользователя

**Email не приходит:**
1. Проверьте логи: `sudo journalctl -u inback | grep "Email"`
2. SendGrid: проверьте Activity Feed в личном кабинете
3. Gmail: убедитесь что используется **пароль приложения**, не обычный пароль
4. Проверьте папку Спам у получателя
