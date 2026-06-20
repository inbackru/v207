#!/bin/bash

# Быстрый экспорт без интерактивных вопросов
# Использование: ./quick_export.sh "postgresql://user:password@host:port/database"

if [ -z "$1" ]; then
    echo "❌ Использование: $0 <DATABASE_URL>"
    echo "Пример: $0 'postgresql://user:pass@host.provider.com:5432/database'"
    exit 1
fi

EXTERNAL_DB_URL="$1"
mkdir -p database_backup
BACKUP_FILE="database_backup/quick_export_$(date +%Y%m%d_%H%M%S).sql"

echo "📦 Экспорт базы данных в $BACKUP_FILE..."

if pg_dump "$EXTERNAL_DB_URL" > "$BACKUP_FILE"; then
    echo "✅ Готово! Размер: $(du -h "$BACKUP_FILE" | cut -f1)"
    
    # Автоматическое сжатие
    gzip "$BACKUP_FILE"
    echo "🗜️ Сжато: ${BACKUP_FILE}.gz"
else
    echo "❌ Ошибка экспорта"
    rm -f "$BACKUP_FILE"
    exit 1
fi
