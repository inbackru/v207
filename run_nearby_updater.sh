#!/bin/bash
# Скрипт для автоматического обновления nearby данных
# Использование: ./run_nearby_updater.sh

cd /home/runner/workspace
python3 nearby_auto_updater.py

echo ""
echo "✅ Обновление завершено: $(date)"
