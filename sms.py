#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SMS verification code module.
Mock implementation for development — prints code to console.
Replace with real SMS provider (Aliyun/Tencent) for production.
"""

import secrets
import string
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from db import get_connection, DB_PATH

# ── 防爆破（进程内存态，单进程部署下有效）──
_MAX_VERIFY_FAILURES = 5      # 连续失败 5 次
_LOCK_SECONDS = 15 * 60       # 锁定 15 分钟
_SEND_COOLDOWN_SECONDS = 60   # 同号发送冷却

_lock = threading.Lock()
_verify_failures = {}  # phone -> [fail_count, lock_until_ts]
_last_sent = {}        # phone -> ts


def _check_send_cooldown(phone: str) -> bool:
    """发送冷却检查。允许发送返回 True。"""
    with _lock:
        last = _last_sent.get(phone, 0)
        if time.time() - last < _SEND_COOLDOWN_SECONDS:
            return False
        _last_sent[phone] = time.time()
        return True


def _register_verify_failure(phone: str) -> None:
    with _lock:
        count, _ = _verify_failures.get(phone, (0, 0))
        count += 1
        lock_until = time.time() + _LOCK_SECONDS if count >= _MAX_VERIFY_FAILURES else 0
        _verify_failures[phone] = (count, lock_until)


def _is_verify_locked(phone: str) -> bool:
    with _lock:
        entry = _verify_failures.get(phone)
        if not entry:
            return False
        count, lock_until = entry
        if lock_until and time.time() < lock_until:
            return True
        if lock_until and time.time() >= lock_until:
            del _verify_failures[phone]  # 锁过期，重新计数
        return False


def _clear_verify_failures(phone: str) -> None:
    with _lock:
        _verify_failures.pop(phone, None)


def generate_code(length: int = 6) -> str:
    """Generate a numeric verification code（加密随机）."""
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def send_verification_code(phone: str, purpose: str = 'login', db_path: str = DB_PATH) -> str:
    """
    Generate and 'send' a verification code.
    In production, replace the print with actual SMS API call.
    Returns the generated code (for testing convenience).
    """
    if not _check_send_cooldown(phone):
        raise ValueError("发送过于频繁，请 1 分钟后再试")

    code = generate_code()
    expires_at = (datetime.now() + timedelta(minutes=5)).isoformat()

    conn = get_connection(db_path)
    # Invalidate any existing unused codes for this phone+purpose
    conn.execute(
        "UPDATE sms_codes SET used = 1 WHERE phone = ? AND purpose = ? AND used = 0",
        [phone, purpose],
    )
    conn.execute(
        "INSERT INTO sms_codes (phone, code, purpose, expires_at) VALUES (?, ?, ?, ?)",
        [phone, code, purpose, expires_at],
    )
    conn.commit()
    conn.close()

    # Mock: print to console. In production, call SMS API here.
    print(f"\n{'='*50}")
    print(f"📱 SMS Verification Code")
    print(f"   Phone:   {phone}")
    print(f"   Code:    {code}")
    print(f"   Purpose: {purpose}")
    print(f"   Expires: {expires_at}")
    print(f"{'='*50}\n")

    return code


def verify_code(phone: str, code: str, purpose: str = 'login', db_path: str = DB_PATH) -> bool:
    """
    Verify a SMS code. Returns True if valid, False otherwise.
    Marks the code as used if valid. 连续失败达上限后锁定该手机号。
    """
    if _is_verify_locked(phone):
        return False
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT id, expires_at, used FROM sms_codes
        WHERE phone = ? AND code = ? AND purpose = ? AND used = 0
        ORDER BY created_at DESC LIMIT 1
    """, [phone, code, purpose]).fetchone()

    if not row:
        conn.close()
        _register_verify_failure(phone)
        return False

    # Check expiry
    expires_at = datetime.fromisoformat(row['expires_at'])
    if datetime.now() > expires_at:
        conn.close()
        _register_verify_failure(phone)
        return False

    # Mark as used
    conn.execute("UPDATE sms_codes SET used = 1 WHERE id = ?", [row['id']])
    conn.commit()
    conn.close()
    _clear_verify_failures(phone)
    return True


def get_admin_by_phone(phone: str, db_path: str = DB_PATH) -> Optional[dict]:
    """Find an admin/teacher user by phone number."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM admin_users WHERE phone = ?", [phone]
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def set_admin_phone(user_id: int, phone: str, db_path: str = DB_PATH) -> None:
    """Set phone number for an admin/teacher user."""
    conn = get_connection(db_path)
    conn.execute("UPDATE admin_users SET phone = ? WHERE id = ?", [phone, user_id])
    conn.commit()
    conn.close()
