#!/usr/bin/env python3
"""
scripts/backup_db.py — Ежедневный бекап PostgreSQL в gzip-файл.

Использование:
    python scripts/backup_db.py

Переменные окружения:
    DATABASE_URL  — строка подключения PostgreSQL (обязательно)
    BACKUP_DIR    — папка для хранения бекапов (по умолчанию: backups/)
    BACKUP_KEEP_DAYS — сколько дней хранить бекапы (по умолчанию: 7)
"""

import gzip
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [backup] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def run_backup() -> bool:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        log.error("DATABASE_URL не задан — бекап невозможен")
        return False

    backup_dir = Path(os.environ.get("BACKUP_DIR", "backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)

    keep_days = int(os.environ.get("BACKUP_KEEP_DAYS", "7"))
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    raw_path = backup_dir / f"backup_{timestamp}.sql"
    gz_path = backup_dir / f"backup_{timestamp}.sql.gz"

    log.info("Начинаю pg_dump → %s", gz_path)

    try:
        result = subprocess.run(
            ["pg_dump", database_url],
            capture_output=True,
            timeout=300,
        )
        if result.returncode != 0:
            log.error("pg_dump завершился с ошибкой: %s", result.stderr.decode())
            return False

        with gzip.open(gz_path, "wb") as f_out:
            f_out.write(result.stdout)

        size_mb = gz_path.stat().st_size / 1024 / 1024
        log.info("✅ Бекап создан: %s (%.1f МБ)", gz_path.name, size_mb)

    except FileNotFoundError:
        log.error("pg_dump не найден. Установите postgresql-client.")
        return False
    except subprocess.TimeoutExpired:
        log.error("pg_dump превысил таймаут 300 сек.")
        return False
    except Exception as e:
        log.error("Ошибка при создании бекапа: %s", e)
        return False

    _rotate_old_backups(backup_dir, keep_days)
    return True


def _rotate_old_backups(backup_dir: Path, keep_days: int):
    cutoff = datetime.utcnow() - timedelta(days=keep_days)
    removed = 0
    for f in backup_dir.glob("backup_*.sql.gz"):
        mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            f.unlink()
            removed += 1
            log.info("Удалён старый бекап: %s", f.name)
    if removed:
        log.info("Ротация: удалено %d файлов старше %d дней", removed, keep_days)


if __name__ == "__main__":
    success = run_backup()
    sys.exit(0 if success else 1)
