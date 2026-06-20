# Инструкция по выгрузке базы данных из другого аккаунта Replit

## Вариант 1: Интерактивный скрипт (рекомендуется для начинающих)

```bash
./scripts/export_external_db.sh
```

Скрипт спросит у вас DATABASE_URL и проведёт через весь процесс.

## Вариант 2: Быстрый экспорт (одна команда)

```bash
./scripts/quick_export.sh "postgresql://user:password@host:5432/database"
```

## Как получить DATABASE_URL из другого проекта Replit:

1. Откройте проект-источник в Replit
2. Откройте Shell
3. Выполните команду:
   ```bash
   echo $DATABASE_URL
   ```
4. Скопируйте полученную строку (она будет в формате `postgresql://...`)

## Прямой экспорт (без скрипта):

Если вы хотите выполнить экспорт напрямую:

```bash
# Создать папку для бэкапов
mkdir -p database_backup

# Экспорт базы
pg_dump "postgresql://user:password@host:5432/database" > database_backup/backup.sql

# Сжать файл (опционально)
gzip database_backup/backup.sql
```

## Импорт в текущую базу данных:

После выгрузки вы можете импортировать данные в текущую базу:

```bash
# Если файл сжат
gunzip database_backup/backup.sql.gz

# Импорт
psql $DATABASE_URL < database_backup/backup.sql
```

## Примечания:

- Все бэкапы сохраняются в папку `database_backup/`
- Файлы автоматически называются с датой и временем
- Быстрый скрипт автоматически сжимает файлы в gzip
- DATABASE_URL должен содержать полные учетные данные для подключения

## Безопасность:

⚠️ **Важно**: DATABASE_URL содержит пароль. Не сохраняйте его в коде и не коммитьте в Git!
