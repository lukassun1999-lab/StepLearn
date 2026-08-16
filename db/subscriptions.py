#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订阅与额度：套餐、支付、额度闸门（原子扣减/退还/重置）。

从 db.py 拆出（2026-08 第 3 周提交 5）；db 包门面继续对外提供全部符号。
"""

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from db.core import DB_PATH, PRICING, _LEGACY_PLAN_MAP, get_connection
# ═══════════════════════════════════════════════════
# Subscription Operations
# ═══════════════════════════════════════════════════

def _subscription_status(end_date_str: Optional[str]) -> str:
    """Determine subscription status based on end_date."""
    if not end_date_str:
        return "active"  # No end date means active indefinitely
    try:
        end = date.fromisoformat(end_date_str)
        today = date.today()
        if end < today:
            return "expired"
        return "active"
    except (ValueError, TypeError):
        return "active"


def refresh_subscription_status(student_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Refresh subscription status based on current date and end_date."""
    sub = get_subscription(student_id, db_path)
    if not sub:
        return None

    new_status = _subscription_status(sub.get("end_date"))
    if sub.get("status") != new_status:
        conn = get_connection(db_path)
        conn.execute(
            "UPDATE subscriptions SET status = ? WHERE student_id = ?",
            [new_status, student_id],
        )
        conn.commit()
        conn.close()
        sub["status"] = new_status
    return sub


def get_subscription(student_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM subscriptions WHERE student_id = ?",
                       [student_id]).fetchone()
    conn.close()
    if not row:
        return None
    sub = dict(row)
    # Auto-correct status based on end_date
    sub["status"] = _subscription_status(sub.get("end_date"))
    return sub


def save_subscription(data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    try:
        plan = data["plan"]
        if plan not in PRICING:
            plan = "trial"
        price = data.get("price", PRICING[plan]["price"])
        monthly_quota = PRICING[plan]["monthly_quota"]
        reset_month = data.get("reset_month") or date.today().strftime("%Y-%m")
        # UPSERT：保留 used_count / start_date / reset_month，只改套餐相关字段
        conn.execute("""
            INSERT INTO subscriptions
                (student_id, plan, price, monthly_quota, reset_month, status, start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(student_id) DO UPDATE SET
                plan = excluded.plan,
                price = excluded.price,
                monthly_quota = excluded.monthly_quota,
                status = excluded.status,
                end_date = excluded.end_date
        """, [data["student_id"], plan, price, monthly_quota, reset_month,
              data["status"], data["start_date"], data.get("end_date")])
        conn.commit()
    finally:
        conn.close()


def record_payment(student_id: int, plan: str, amount: Optional[float] = None,
                   note: str = "", db_path: str = DB_PATH) -> int:
    """记录一笔线下收款，并联动订阅升级/续期。

    - monthly（¥39/月，40 次/月）：有效期 +30 天；套餐变更时清零当月计数，
      同套餐续费不动 used_count（自然月重置自会清零）；
    - yearly（¥399/年，600 次池）：有效期 +365 天，换新 600 次池（清零计数）；
    - payments.weeks 列按"月数"存储（monthly=1，yearly=12）以兼容展示。

    amount 缺省取 PRICING 标准价；允许运营录入折后价（只入账，不影响权益）。
    Returns the payment id.
    """
    if plan not in ("monthly", "yearly"):
        raise ValueError(f"收款套餐必须是 monthly/yearly，收到: {plan}")
    info = PRICING[plan]
    if amount is None:
        amount = float(info["price"])
    amount = float(amount)
    days = 30 if plan == "monthly" else 365
    months = 1 if plan == "monthly" else 12

    conn = get_connection(db_path)
    try:
        cur = conn.execute("""
            INSERT INTO payments (student_id, amount, weeks, note)
            VALUES (?, ?, ?, ?)
        """, [student_id, amount, months, note])
        payment_id = cur.lastrowid

        sub_row = conn.execute(
            "SELECT * FROM subscriptions WHERE student_id = ?", [student_id]
        ).fetchone()

        today = date.today()
        new_end = today + timedelta(days=days)
        if sub_row:
            current_plan = sub_row["plan"]
            current_end_str = sub_row["end_date"]
            if current_end_str:
                try:
                    current_end = date.fromisoformat(current_end_str)
                    # 未过期则在原有效期基础上顺延
                    new_end = max(current_end, today) + timedelta(days=days)
                except (ValueError, TypeError):
                    pass
            # 换新池的条件：套餐变更，或包年续费（600 次池以付款为重置点）
            reset_pool = (current_plan != plan) or (plan == "yearly")
            conn.execute("""
                UPDATE subscriptions
                SET plan = ?, price = ?, monthly_quota = ?, end_date = ?, status = 'active'
                    , used_count = CASE WHEN ? THEN 0 ELSE used_count END
                    , reset_month = ?
                WHERE student_id = ?
            """, [plan, amount, info["monthly_quota"], new_end.isoformat(),
                  1 if reset_pool else 0, today.strftime("%Y-%m"), student_id])
        else:
            conn.execute("""
                INSERT INTO subscriptions
                    (student_id, plan, price, monthly_quota, used_count, reset_month,
                     status, start_date, end_date)
                VALUES (?, ?, ?, ?, 0, ?, 'active', ?, ?)
            """, [student_id, plan, amount, info["monthly_quota"],
                  today.strftime("%Y-%m"), today.isoformat(), new_end.isoformat()])

        conn.commit()
        return payment_id
    finally:
        conn.close()


def get_payments(student_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get payment history for a student."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM payments WHERE student_id = ? ORDER BY paid_at DESC
    """, [student_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_subscription_summary(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get subscription details enriched with payments, days remaining, etc."""
    sub = get_subscription(student_id, db_path)
    if not sub:
        return {
            "student_id": student_id,
            "plan": "trial",
            "plan_label": "试用",
            "status": "active",
            "status_label": "活跃",
            "start_date": None,
            "end_date": None,
            "days_remaining": None,
            "price": 0,
            "payments": [],
            "total_paid": 0,
        }

    plan = sub.get("plan", "trial")
    plan_info = PRICING.get(plan, {"label": plan, "price": 0})
    end_date_str = sub.get("end_date")
    days_remaining = None
    if end_date_str:
        try:
            days_remaining = (date.fromisoformat(end_date_str) - date.today()).days
        except (ValueError, TypeError):
            pass

    status = sub.get("status", "active")
    status_labels = {"active": "有效", "expired": "已过期", "paused": "暂停"}

    payments = get_payments(student_id, db_path)
    total_paid = sum(p.get("amount", 0) or 0 for p in payments)

    # Monthly quota info（trial/yearly 为一次性池，不随自然月清零）
    monthly_quota = sub.get("monthly_quota") or plan_info.get("monthly_quota", 0)
    used_count = sub.get("used_count") or 0
    reset_month = sub.get("reset_month") or date.today().strftime("%Y-%m")
    current_month = date.today().strftime("%Y-%m")
    is_unlimited = bool(plan_info.get("unlimited"))
    if (not is_unlimited
            and plan_info.get("reset_period") == "monthly"
            and reset_month != current_month):
        used_count = 0
    remaining_quota = 999999 if is_unlimited else max(0, monthly_quota - used_count)

    return {
        "student_id": student_id,
        "plan": plan,
        "plan_label": plan_info["label"],
        "status": status,
        "status_label": status_labels.get(status, status),
        "start_date": sub.get("start_date"),
        "end_date": end_date_str,
        "days_remaining": days_remaining,
        "price": sub.get("price") or plan_info["price"],
        "monthly_quota": monthly_quota,
        "used_count": used_count,
        "remaining_quota": remaining_quota,
        "reset_month": reset_month,
        "payments": payments,
        "total_paid": total_paid,
    }


def _ensure_quota_reset(conn: sqlite3.Connection, sub: Dict[str, Any]) -> Dict[str, Any]:
    """按套餐重置语义刷新 used_count。

    - monthly（包月）：自然月切换时清零（当月未用完作废）；
    - trial / yearly / unlimited：一次性池，不按月清零
      （trial 3 次用完即止；yearly 600 次池在续费时由 record_payment 换新）。
    """
    reset_month = sub.get("reset_month") or date.today().strftime("%Y-%m")
    current_month = date.today().strftime("%Y-%m")
    monthly_quota = sub.get("monthly_quota") or 0
    # 兜底：历史/异常订阅额度为 0 时按 PRICING 回填（单一收口点）
    if not monthly_quota:
        plan_quota = PRICING.get(sub.get("plan", ""), {}).get("monthly_quota", 0)
        if plan_quota:
            monthly_quota = plan_quota
            conn.execute(
                "UPDATE subscriptions SET monthly_quota = ? WHERE student_id = ?",
                [plan_quota, sub["student_id"]],
            )
            conn.commit()
    used_count = sub.get("used_count") or 0
    plan = sub.get("plan", "")
    resets_monthly = PRICING.get(plan, {}).get("reset_period") == "monthly"
    if resets_monthly and reset_month != current_month:
        used_count = 0
        reset_month = current_month
        conn.execute(
            "UPDATE subscriptions SET used_count = 0, reset_month = ? WHERE student_id = ?",
            [reset_month, sub["student_id"]],
        )
        conn.commit()
    sub["monthly_quota"] = monthly_quota
    sub["used_count"] = used_count
    sub["reset_month"] = reset_month
    return sub


def get_remaining_quota(student_id: int, db_path: str = DB_PATH) -> int:
    """Return remaining analysis quota for the current month."""
    sub = get_subscription(student_id, db_path)
    if not sub:
        return 0
    conn = get_connection(db_path)
    try:
        _ensure_quota_reset(conn, sub)
    finally:
        conn.close()
    # 测试无限套餐：不限次数
    if PRICING.get(sub["plan"], {}).get("unlimited"):
        return 999999
    return max(0, sub["monthly_quota"] - sub["used_count"])


def check_quota(student_id: int, db_path: str = DB_PATH) -> Tuple[bool, int]:
    """Check whether the student has remaining quota.

    Returns (has_quota, remaining_count).
    """
    remaining = get_remaining_quota(student_id, db_path)
    return remaining > 0, remaining


def consume_quota(student_id: int, db_path: str = DB_PATH) -> bool:
    """Consume one analysis quota. Returns True if successful.

    扣减用单条条件 UPDATE + rowcount 判定，保证并发下不超卖
    （与 refund_quota 的写法对称）。
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE student_id = ?", [student_id]
        ).fetchone()
        if not row:
            return False
        sub = dict(row)
        # 超级账号：不计数、不限制
        if PRICING.get(sub["plan"], {}).get("unlimited"):
            return True
        _ensure_quota_reset(conn, sub)
        cur = conn.execute(
            "UPDATE subscriptions SET used_count = used_count + 1 "
            "WHERE student_id = ? AND used_count < monthly_quota",
            [student_id],
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def refund_quota(student_id: int, db_path: str = DB_PATH) -> bool:
    """Refund one analysis quota (e.g. when a task failed after charging).
    Returns True if a quota unit was actually refunded."""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "UPDATE subscriptions SET used_count = MAX(used_count - 1, 0) "
            "WHERE student_id = ? AND used_count > 0",
            [student_id],
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_expiring_subscriptions(days: int = 7, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get active subscriptions that expire within N days or already expired."""
    conn = get_connection(db_path)
    today = date.today()
    alert_date = (today + timedelta(days=days)).isoformat()

    rows = conn.execute("""
        SELECT s.id, s.name, s.grade, sub.plan, sub.end_date, sub.status
        FROM students s
        JOIN subscriptions sub ON sub.student_id = s.id
        WHERE s.status = 'active'
          AND (sub.end_date IS NULL OR sub.end_date <= ? OR sub.status = 'expired')
        ORDER BY sub.end_date IS NULL, sub.end_date ASC, s.name
    """, [alert_date]).fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        end_date_str = d.get("end_date")
        d["days_remaining"] = None
        if end_date_str:
            try:
                d["days_remaining"] = (date.fromisoformat(end_date_str) - today).days
            except (ValueError, TypeError):
                pass
        d["plan_label"] = PRICING.get(d.get("plan", "trial"), {}).get("label", d.get("plan"))
        results.append(d)
    return results

