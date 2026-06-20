#!/bin/bash

# ================================================
# InBack - Скрипт автоматической установки
# ================================================

set -e  # Выход при ошибке

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  InBack - Установка платформы${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Проверка Python
echo -e "${YELLOW}[1/6]${NC} Проверка Python..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 не установлен!${NC}"
    echo "Установите Python 3.11 или выше: https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo -e "${GREEN}✅ Python $PYTHON_VERSION найден${NC}"

# Проверка PostgreSQL
echo -e "${YELLOW}[2/6]${NC} Проверка PostgreSQL..."
if ! command -v psql &> /dev/null; then
    echo -e "${RED}❌ PostgreSQL не установлен!${NC}"
    echo "Установите PostgreSQL: https://www.postgresql.org/download/"
    exit 1
fi

POSTGRES_VERSION=$(psql --version | cut -d' ' -f3 | cut -d'.' -f1)
echo -e "${GREEN}✅ PostgreSQL $POSTGRES_VERSION найден${NC}"

# Создание виртуального окружения
echo -e "${YELLOW}[3/6]${NC} Создание виртуального окружения..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✅ Виртуальное окружение создано${NC}"
else
    echo -e "${BLUE}ℹ️  Виртуальное окружение уже существует${NC}"
fi

# Активация виртуального окружения
echo -e "${YELLOW}[4/6]${NC} Активация окружения и установка зависимостей..."
source venv/bin/activate

# Установка зависимостей
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt
echo -e "${GREEN}✅ Зависимости установлены${NC}"

# Настройка .env
echo -e "${YELLOW}[5/6]${NC} Настройка переменных окружения..."
if [ ! -f ".env" ]; then
    cp deployment/.env.example .env
    echo -e "${GREEN}✅ Файл .env создан${NC}"
    echo -e "${YELLOW}⚠️  ВАЖНО: Отредактируйте .env и добавьте свои ключи!${NC}"
else
    echo -e "${BLUE}ℹ️  Файл .env уже существует${NC}"
fi

# Создание базы данных (опционально)
echo -e "${YELLOW}[6/6]${NC} Настройка базы данных..."
echo -e "${BLUE}Хотите создать базу данных PostgreSQL? (y/n)${NC}"
read -r CREATE_DB

if [ "$CREATE_DB" = "y" ] || [ "$CREATE_DB" = "Y" ]; then
    echo -e "${BLUE}Введите имя базы данных [inback_db]:${NC}"
    read -r DB_NAME
    DB_NAME=${DB_NAME:-inback_db}
    
    echo -e "${BLUE}Введите имя пользователя БД [inback_user]:${NC}"
    read -r DB_USER
    DB_USER=${DB_USER:-inback_user}
    
    echo -e "${BLUE}Введите пароль для БД:${NC}"
    read -rs DB_PASSWORD
    
    # Создание базы данных
    sudo -u postgres psql <<EOF
CREATE DATABASE $DB_NAME;
CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
EOF
    
    echo -e "${GREEN}✅ База данных создана${NC}"
    
    # Обновление .env
    sed -i "s|DATABASE_URL=.*|DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME|g" .env
    sed -i "s|PGDATABASE=.*|PGDATABASE=$DB_NAME|g" .env
    sed -i "s|PGUSER=.*|PGUSER=$DB_USER|g" .env
    sed -i "s|PGPASSWORD=.*|PGPASSWORD=$DB_PASSWORD|g" .env
    
    echo -e "${GREEN}✅ .env обновлен с данными БД${NC}"
else
    echo -e "${BLUE}ℹ️  Пропущено. Настройте базу данных вручную.${NC}"
fi

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  ✅ Установка завершена!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${YELLOW}Следующие шаги:${NC}"
echo -e "1. Отредактируйте ${BLUE}.env${NC} - добавьте API ключи"
echo -e "2. Запустите приложение:"
echo -e "   ${BLUE}source venv/bin/activate${NC}"
echo -e "   ${BLUE}gunicorn --bind 0.0.0.0:5000 --reload main:app${NC}"
echo -e "3. Откройте ${BLUE}http://localhost:5000${NC}"
echo ""
echo -e "${GREEN}Готово! 🎉${NC}"
