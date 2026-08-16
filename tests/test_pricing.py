#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""计价体系测试（2026-08 定版）。

规则：
- trial    3 次一次性池，不按月重置；
- monthly  ¥39/月，40 次/月，自然月清零（当月未用完作废）；
- yearly   ¥399/年，600 次池，订阅期内有效，续费换新池；
- unlimited 超级账号，不限次、不计数；
- 付款联动套餐升级；改套餐不清当月用量。
"""

from datetime import date, timedelta

import pytest

import db


def _get_sub(student_id, db_path):
    conn = db.get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE student_id = ?", [student_id]).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _set_sub(student_id, db_path, **fields):
    conn = db.get_connection(db_path)
    try:
        for k, v in fields.items():
            conn.execute(
                f"UPDATE subscriptions SET {k} = ? WHERE student_id = ?", [v, student_id])
        conn.commit()
    finally:
        conn.close()


# ── trial：3 次一次性池 ──────────────────────────────

def test_trial_quota_is_3(test_db_path):
    assert db.PRICING["trial"]["monthly_quota"] == 3


def test_trial_exhausts_and_never_resets_monthly(test_db_path):
    sid = db.create_student({"name": "体验池", "plan": "trial"}, db_path=test_db_path)
    for _ in range(3):
        assert db.consume_quota(sid, db_path=test_db_path) is True
    assert db.consume_quota(sid, db_path=test_db_path) is False

    # 模拟跨月：把 reset_month 拨回上个月，trial 不应回血
    _set_sub(sid, test_db_path, reset_month="2020-01")
    ok, remaining = db.check_quota(sid, db_path=test_db_path)
    assert ok is False and remaining == 0


# ── monthly：40 次/月，自然月清零 ────────────────────

def test_monthly_resets_on_calendar_month(test_db_path):
    sid = db.create_student({"name": "包月", "plan": "monthly"}, db_path=test_db_path)
    sub = _get_sub(sid, test_db_path)
    assert sub["monthly_quota"] == db.PRICING["monthly"]["monthly_quota"] == 40
    # 建号即计时：付费套餐有有效期
    assert sub["end_date"] == (date.today() + timedelta(days=30)).isoformat()

    for _ in range(5):
        assert db.consume_quota(sid, db_path=test_db_path) is True
    # 模拟跨月 → used_count 清零、额度回来
    _set_sub(sid, test_db_path, reset_month="2020-01")
    ok, remaining = db.check_quota(sid, db_path=test_db_path)
    assert ok is True and remaining == 40
    assert _get_sub(sid, test_db_path)["used_count"] == 0


# ── yearly：600 次池，不按月清零，续费换新池 ──────────

def test_yearly_pool_not_cleared_monthly(test_db_path):
    sid = db.create_student({"name": "包年", "plan": "yearly"}, db_path=test_db_path)
    for _ in range(10):
        assert db.consume_quota(sid, db_path=test_db_path) is True

    _set_sub(sid, test_db_path, reset_month="2020-01")
    ok, remaining = db.check_quota(sid, db_path=test_db_path)
    # 跨月不清零：仍是 600 - 10
    assert ok is True and remaining == 600 - 10


def test_yearly_renewal_resets_pool_and_extends_year(test_db_path):
    sid = db.create_student({"name": "包年续费", "plan": "yearly"}, db_path=test_db_path)
    for _ in range(100):
        db.consume_quota(sid, db_path=test_db_path)
    # 模拟一年期已消耗完（有效期到今天），续费应从今天起算新一年
    _set_sub(sid, test_db_path, end_date=date.today().isoformat())

    db.record_payment(sid, "yearly", 399, "续费", db_path=test_db_path)
    sub = _get_sub(sid, test_db_path)
    assert sub["used_count"] == 0
    assert sub["monthly_quota"] == 600
    assert sub["end_date"] == (date.today() + timedelta(days=365)).isoformat()
    assert sub["status"] == "active"


# ── 付款联动套餐升级 ─────────────────────────────────

def test_payment_upgrades_trial_to_monthly(test_db_path):
    sid = db.create_student({"name": "升级", "plan": "trial"}, db_path=test_db_path)
    db.consume_quota(sid, db_path=test_db_path)  # 用掉 1 次体验

    db.record_payment(sid, "monthly", 39, "微信转账", db_path=test_db_path)
    sub = _get_sub(sid, test_db_path)
    assert sub["plan"] == "monthly"
    assert sub["monthly_quota"] == 40
    # 套餐变更 → 换新池
    assert sub["used_count"] == 0
    assert sub["end_date"] == (date.today() + timedelta(days=30)).isoformat()

    # payments 记录入账
    payments = db.get_payments(sid, db_path=test_db_path)
    assert len(payments) == 1
    assert payments[0]["amount"] == 39


def test_monthly_renewal_keeps_current_month_usage(test_db_path):
    sid = db.create_student({"name": "包月续费", "plan": "monthly"}, db_path=test_db_path)
    for _ in range(5):
        db.consume_quota(sid, db_path=test_db_path)
    # 模拟本期到期（有效期到今天），续费从今天起算新 30 天
    _set_sub(sid, test_db_path, end_date=date.today().isoformat())

    db.record_payment(sid, "monthly", 39, "续费", db_path=test_db_path)
    sub = _get_sub(sid, test_db_path)
    # 同套餐续费不清当月用量（自然月重置自会清零）
    assert sub["used_count"] == 5
    assert sub["end_date"] == (date.today() + timedelta(days=30)).isoformat()


def test_payment_extends_from_current_end_date(test_db_path):
    sid = db.create_student({"name": "顺延", "plan": "monthly"}, db_path=test_db_path)
    future_end = date.today() + timedelta(days=10)
    _set_sub(sid, test_db_path, end_date=future_end.isoformat())

    db.record_payment(sid, "monthly", 39, "", db_path=test_db_path)
    sub = _get_sub(sid, test_db_path)
    # 未过期：从原有效期顺延 30 天，而非从今天
    assert sub["end_date"] == (future_end + timedelta(days=30)).isoformat()


def test_payment_rejects_unknown_plan(test_db_path):
    sid = db.create_student({"name": "非法套餐", "plan": "trial"}, db_path=test_db_path)
    with pytest.raises(ValueError):
        db.record_payment(sid, "unlimited", 0, "", db_path=test_db_path)


# ── 超级账号 ─────────────────────────────────────────

def test_unlimited_plan_bypasses_quota(test_db_path):
    sid = db.create_student({"name": "超级", "plan": "unlimited"}, db_path=test_db_path)
    for _ in range(10):
        assert db.consume_quota(sid, db_path=test_db_path) is True
    # 不计数
    assert _get_sub(sid, test_db_path)["used_count"] == 0


# ── 扣减原子性与改套餐保用量 ─────────────────────────

def test_consume_quota_guard_prevents_oversell(test_db_path):
    sid = db.create_student({"name": "守卫", "plan": "monthly"}, db_path=test_db_path)
    # 人为把 used_count 拉到额度上限（模拟历史数据/并发脏数据）
    _set_sub(sid, test_db_path, used_count=40)
    assert db.consume_quota(sid, db_path=test_db_path) is False
    assert _get_sub(sid, test_db_path)["used_count"] == 40


def test_update_student_plan_preserves_usage(test_db_path):
    sid = db.create_student({"name": "改套餐", "plan": "monthly"}, db_path=test_db_path)
    for _ in range(5):
        db.consume_quota(sid, db_path=test_db_path)
    end = (date.today() + timedelta(days=15)).isoformat()
    _set_sub(sid, test_db_path, end_date=end)

    db.update_student(sid, {"name": "改套餐", "grade": "高二", "school_type": "住校",
                            "plan": "yearly"},
                      db_path=test_db_path)
    sub = _get_sub(sid, test_db_path)
    assert sub["plan"] == "yearly"
    assert sub["monthly_quota"] == 600
    assert sub["used_count"] == 5  # 不清零
    assert sub["end_date"] == end  # 有效期不丢


# ── 存量迁移：旧套餐名映射 ───────────────────────────

def test_legacy_plan_migration(test_db_path):
    sid = db.create_student({"name": "旧套餐", "plan": "monthly"}, db_path=test_db_path)
    _set_sub(sid, test_db_path, plan="basic", monthly_quota=8)
    # 再跑一遍 init_db（幂等迁移），basic → monthly、额度按 PRICING 回填
    db.init_db(test_db_path)
    sub = _get_sub(sid, test_db_path)
    assert sub["plan"] == "monthly"
    assert sub["monthly_quota"] == 40
