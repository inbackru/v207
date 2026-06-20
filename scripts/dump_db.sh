#!/bin/bash
# Database dump script for InBack/Clickback
# Usage: bash scripts/dump_db.sh
# Dumps are saved to dumps/ folder with timestamp

DUMP_DIR="dumps"
mkdir -p "$DUMP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DUMP_FILE="$DUMP_DIR/inback_${TIMESTAMP}.sql"

echo "📦 Создаю дамп базы данных..."
echo "   Файл: $DUMP_FILE"

if [ -z "$DATABASE_URL" ]; then
    echo "❌ Переменная DATABASE_URL не задана"
    exit 1
fi

pg_dump "$DATABASE_URL" \
    --no-owner \
    --no-acl \
    --format=plain \
    --file="$DUMP_FILE"

if [ $? -eq 0 ]; then
    SIZE=$(du -sh "$DUMP_FILE" | cut -f1)
    echo "✅ Дамп создан успешно: $DUMP_FILE ($SIZE)"
    
    # Keep only last 10 dumps
    DUMP_COUNT=$(ls -1 "$DUMP_DIR"/*.sql 2>/dev/null | wc -l)
    if [ "$DUMP_COUNT" -gt 10 ]; then
        echo "🧹 Удаляю старые дампы (оставляю последние 10)..."
        ls -1t "$DUMP_DIR"/*.sql | tail -n +11 | xargs rm -f
    fi
    
    echo "📁 Все дампы:"
    ls -lh "$DUMP_DIR"/*.sql 2>/dev/null
else
    echo "❌ Ошибка создания дампа"
    rm -f "$DUMP_FILE"
    exit 1
fi
