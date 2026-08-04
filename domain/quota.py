#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一额度闸门：订阅校验 + 额度消耗的唯一收口（核心链路架构设计.md §5.2）。

闸门顺序：订阅 active → 额度检查 → consume_quota。
- staff（老师/管理员）豁免；
- 是否消耗由调用方按 stage 决定（analysis_only / report_only 免费）；
- 任务失败时由 pipeline_worker 调 db.refund_quota 退还（input_data
  需带 quota_charged=True 标记）。
"""

from typing import Optional, Tuple

import db


def charge_analysis(student_id: int, is_staff: bool = False,
                    db_path: str = None) -> Tuple[bool, Optional[str]]:
    """消耗 1 次分析额度。返回 (ok, error_message)。

    staff 直接放行（不计数）。
    """
    db_path = db_path or db.DB_PATH
    sub = db.get_subscription(student_id, db_path)
    if not sub or sub.get("status") != "active":
        return False, "订阅已过期，请联系老师续费"
    if is_staff:
        return True, None
    has_quota, remaining = db.check_quota(student_id, db_path)
    if not has_quota:
        plan_label = db.PRICING.get(sub.get("plan", "trial"), {}).get("label", "体验")
        return False, (f"本月 {plan_label} 额度已用完（剩余 {remaining} 次），"
                       f"请续费或升级套餐")
    if not db.consume_quota(student_id, db_path):
        return False, "额度扣减失败，请刷新后重试"
    return True, None
