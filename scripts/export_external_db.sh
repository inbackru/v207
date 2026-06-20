#!/bin/bash

# Скрипт для выгрузки PostgreSQL базы данных из другого аккаунта Replit
# Использование: ./export_external_db.sh

echo "=== Экспорт базы данных из внешнего источника ==="

# Запрос DATABASE_URL из другого аккаунта
echo ""
echo "Введите DATABASE_URL из другого аккаунта Replit:"
echo "(Формат: postgresql://user:password@host:port/database)"
read -r EXTERNAL_DATABASE_URL

if [ -z "$EXTERNAL_DATABASE_URL" ]; then
    echo "❌ Ошибка: DATABASE_URL не может быть пустым"
    exit 1
fi

# Создание папки для бэкапов если её нет
mkdir -p database_backup

# Генерация имени файла с датой и временем
BACKUP_FILE="database_backup/db_export_$(date +%Y%m%d_%H%M%S).sql"

echo ""
echo "📦 Начинаю экспорт базы данных..."
echo "📁 Файл: $BACKUP_FILE"

# Экспорт базы данных с использованием pg_dump
if pg_dump "$EXTERNAL_DATABASE_URL" > "$BACKUP_FILE"; then
    echo ""
    echo "✅ Экспорт успешно завершен!"
    echo "📊 Размер файла: $(du -h "$BACKUP_FILE" | cut -f1)"
    echo ""
    echo "Для импорта в текущую базу используйте:"
    echo "  psql \$DATABASE_URL < $BACKUP_FILE"
else
    echo ""
    echo "❌ Ошибка при экспорте базы данных"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# Опционально: сжатие файла
echo ""
read -p "Сжать файл в gzip? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[YyДд]$ ]]; then
    echo "🗜️ Сжатие файла..."
    gzip "$BACKUP_FILE"
    echo "✅ Создан архив: ${BACKUP_FILE}.gz"
fi

echo ""
echo "✅ Готово!"
