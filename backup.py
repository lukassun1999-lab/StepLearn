#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLite 自动备份模块
纯标准库实现，使用 sqlite3.backup() 保证一致性。
"""

import os
import sqlite3
from datetime import datetime
from typing import Dict, Optional

from db import DB_PATH, record_backup, get_backups, cleanup_old_backups

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "backups")


def ensure_backup_dir() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _backup_filename(backup_type: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"data_{backup_type}_{ts}.db"


def run_backup(backup_type: str = "daily") -> str:
    """Perform a SQLite online backup and record it.

    Returns the backup file path.
    """
    ensure_backup_dir()
    filename = _backup_filename(backup_type)
    backup_path = os.path.join(BACKUP_DIR, filename)

    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()

    file_size = os.path.getsize(backup_path)
    record_backup(backup_path, backup_type, file_size)
    return backup_path


def auto_cleanup(daily_keep: int = 7, weekly_keep: int = 4) -> Dict[str, any]:
    """Run retention policy cleanup."""
    return cleanup_old_backups(daily_keep=daily_keep, weekly_keep=weekly_keep)


def get_backup_path(backup_id: int) -> Optional[str]:
    """Return the filesystem path for a recorded backup."""
    for b in get_backups():
        if b["id"] == backup_id:
            return b["backup_path"]
    return None


if __name__ == "__main__":
    path = run_backup("manual")
    print(f"Backup created: {path}")
    print(auto_cleanup())
