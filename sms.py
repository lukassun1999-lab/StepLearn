#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SMS verification code module.
Mock implementation for development — prints code to console.
Replace with real SMS provider (Aliyun/Tencent) for production.
"""

import random
import string
from datetime import datetime, timedelta
from typing import Optional

from db import get_connection, DB_PATH


def generate_code(length: int = 6) -> str:
    """Generate a numeric verification code."""
    return ''.join(random.choices(string.digits, k=length))


def send_verification_code(phone: str, purpose: str = 'login', db_path: str = DB_PATH) -> str:
    """
    Generate and 'send' a verification code.
    In production, replace the print with actual SMS API call.
    Returns the generated code (for testing convenience).
    """
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
    Marks the code as used if valid.
    """
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT id, expires_at, used FROM sms_codes
        WHERE phone = ? AND code = ? AND purpose = ? AND used = 0
        ORDER BY created_at DESC LIMIT 1
    """, [phone, code, purpose]).fetchone()

    if not row:
        conn.close()
        return False

    # Check expiry
    expires_at = datetime.fromisoformat(row['expires_at'])
    if datetime.now() > expires_at:
        conn.close()
        return False

    # Mark as used
    conn.execute("UPDATE sms_codes SET used = 1 WHERE id = ?", [row['id']])
    conn.commit()
    conn.close()
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
