#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拾阶而上 — 统一数据库层 (SQLite)
整合原 app.py 的业务表 + data_manager.py 的教学表，单一数据源。
"""

import sqlite3
import json
import os
import shutil
import uuid
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = os.environ.get("WEEKEND_ENGLISH_DB", os.path.join(os.path.dirname(__file__), "data.db"))

# ═══════════════════════════════════════════════════
# Subscription Pricing
# ═══════════════════════════════════════════════════

# 计价体系（2026-08 定版）：
# - trial    3 次，一次性池（不按月重置），不设有效期；
# - monthly  ¥39/月，40 次/月，自然月重置、当月未用完清零；
# - yearly   ¥399/年，600 次池，订阅期内有效（不按月清零），续费时换新池；
# - unlimited 超级账号，不限次数。
# reset_period 决定 _ensure_quota_reset 是否做月度清零：
#   "monthly" → 每自然月清零；"none" → 一次性池，由付款/建号时给定。
PRICING = {
    "trial": {
        "label": "体验",
        "price": 0,
        "unit": "次",
        "monthly_quota": 3,
        "reset_period": "none",
        "description": "注册赠送 3 次分析额度（一次性，用完即止）",
    },
    "monthly": {
        "label": "包月",
        "price": 39,
        "unit": "月",
        "monthly_quota": 40,
        "reset_period": "monthly",
        "description": "¥39/月，每月 40 次，当月未用完月底清零",
    },
    "yearly": {
        "label": "包年",
        "price": 399,
        "unit": "年",
        "monthly_quota": 600,
        "reset_period": "none",
        "description": "¥399/年，共 600 次，订阅期内有效",
    },
    "unlimited": {
        "label": "超级账号",
        "price": 0,
        "unit": "月",
        "monthly_quota": 999999,
        "reset_period": "none",
        "unlimited": True,
        "description": "超级账号，不限调用次数",
    },
}

# 旧套餐名 → 现行套餐名（迁移映射）
_LEGACY_PLAN_MAP = {
    "standard": "monthly",
    "basic": "monthly",
    "premium": "yearly",
}


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _migrate_db(conn: sqlite3.Connection) -> None:
    """Run lightweight migrations for schema updates."""
    # Add role column to admin_users if missing
    cols = conn.execute("PRAGMA table_info(admin_users)").fetchall()
    col_names = [c["name"] for c in cols]
    if "role" not in col_names:
        conn.execute("ALTER TABLE admin_users ADD COLUMN role TEXT DEFAULT 'teacher'")
        conn.commit()
    # Add phone column to admin_users if missing (for SMS verification code login)
    if "phone" not in col_names:
        conn.execute("ALTER TABLE admin_users ADD COLUMN phone TEXT")
        conn.commit()
    # Add subject column to admin_users if missing
    if "subject" not in col_names:
        conn.execute("ALTER TABLE admin_users ADD COLUMN subject TEXT DEFAULT '英语'")
        conn.commit()
    # Add school_id column to admin_users if missing
    if "school_id" not in col_names:
        conn.execute("ALTER TABLE admin_users ADD COLUMN school_id INTEGER")
        conn.commit()

    # Add subscription quota columns if missing
    sub_cols = conn.execute("PRAGMA table_info(subscriptions)").fetchall()
    sub_col_names = [c["name"] for c in sub_cols]
    for col in ("monthly_quota", "used_count"):
        if col not in sub_col_names:
            conn.execute(f"ALTER TABLE subscriptions ADD COLUMN {col} INTEGER DEFAULT 0")
            conn.commit()
    if "reset_month" not in sub_col_names:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN reset_month TEXT")
        conn.commit()
    # P3-16：price 列防御性迁移（原属第一个 _migrate_db 定义，该定义因重复被遮蔽）
    if "price" not in sub_col_names:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN price REAL DEFAULT 0")
        conn.commit()
    # 套餐体系迁移（2026-08 定版）：standard/basic → monthly，premium → yearly
    for legacy, current in _LEGACY_PLAN_MAP.items():
        conn.execute("UPDATE subscriptions SET plan = ? WHERE plan = ?", [current, legacy])
    # Backfill subscriptions with quota/price from PRICING（PRICING 为配额唯一真相源，
    # 无条件回填，保证存量行与现行计价一致；used_count 不动）
    for plan, info in PRICING.items():
        conn.execute(
            "UPDATE subscriptions SET monthly_quota = ? WHERE plan = ?",
            [info["monthly_quota"], plan],
        )
        conn.execute(
            "UPDATE subscriptions SET price = ? WHERE plan = ? AND (price IS NULL OR price = 0)",
            [info["price"], plan],
        )
    # Add student profile related columns to students if missing
    student_cols = conn.execute("PRAGMA table_info(students)").fetchall()
    student_col_names = [c["name"] for c in student_cols]
    for col in ("gender", "textbook_version", "semester"):
        if col not in student_col_names:
            conn.execute(f"ALTER TABLE students ADD COLUMN {col} TEXT")
            conn.commit()
    # Add school/class/auth columns to students for student self-registration
    for col, col_type in [("school_id", "INTEGER"), ("class_id", "INTEGER"),
                          ("phone", "TEXT"), ("password_hash", "TEXT")]:
        if col not in student_col_names:
            conn.execute(f"ALTER TABLE students ADD COLUMN {col} {col_type}")
            conn.commit()
    # Add parent_task_progress column to student_profiles if missing
    profile_cols = conn.execute("PRAGMA table_info(student_profiles)").fetchall()
    profile_col_names = [c["name"] for c in profile_cols]
    if "parent_task_progress" not in profile_col_names:
        conn.execute("ALTER TABLE student_profiles ADD COLUMN parent_task_progress TEXT DEFAULT '{}'")
        conn.commit()
    # Add learning_style_detail column to student_profiles if missing
    if "learning_style_detail" not in profile_col_names:
        conn.execute("ALTER TABLE student_profiles ADD COLUMN learning_style_detail TEXT DEFAULT '{}'")
        conn.commit()
    # Add spaced repetition columns to mistakes if missing
    mistake_cols = conn.execute("PRAGMA table_info(mistakes)").fetchall()
    mistake_col_names = [c["name"] for c in mistake_cols]
    for col, default in [("next_review_at", "NULL"), ("review_interval_hours", "0"), ("review_stage", "0")]:
        if col not in mistake_col_names:
            conn.execute(f"ALTER TABLE mistakes ADD COLUMN {col} {'TEXT' if col == 'next_review_at' else 'REAL' if 'hours' in col else 'INTEGER'} DEFAULT {default}")
            conn.commit()
    # Add error-cause columns to mistakes (错因因果链: 受控五类 + 判断证据)
    for col in ("error_cause", "cause_evidence"):
        if col not in mistake_col_names:
            conn.execute(f"ALTER TABLE mistakes ADD COLUMN {col} TEXT")
            conn.commit()
    # Add passage column to mistakes (阅读题所属短文原文，练习生成时随题展示)
    if "passage" not in mistake_col_names:
        conn.execute("ALTER TABLE mistakes ADD COLUMN passage TEXT")
        conn.commit()
    # Add source_mistake_id to questions for similar question tracking
    question_cols = conn.execute("PRAGMA table_info(questions)").fetchall()
    question_col_names = [c["name"] for c in question_cols]
    if "source_mistake_id" not in question_col_names:
        conn.execute("ALTER TABLE questions ADD COLUMN source_mistake_id INTEGER")
        conn.commit()
    # Create achievements table if missing (for databases created before this feature)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                achievement_key TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                icon TEXT DEFAULT '🏆',
                tier INTEGER DEFAULT 1,
                earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id),
                UNIQUE(student_id, achievement_key)
            )
        """)
        conn.commit()
    except sqlite3.OperationalError:
        pass
    # Create metacognitive_reviews table if missing
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metacognitive_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                template_questions TEXT DEFAULT '{}',
                child_answers TEXT DEFAULT '{}',
                parent_answers TEXT DEFAULT '{}',
                child_mood INTEGER,
                parent_mood INTEGER,
                child_note TEXT,
                parent_note TEXT,
                status TEXT DEFAULT 'draft',
                submitted_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id),
                UNIQUE(student_id, week_start)
            )
        """)
        conn.commit()
    except sqlite3.OperationalError:
        pass
    # Migrate teacher_profile from singleton to per-teacher model
    tp_cols = conn.execute("PRAGMA table_info(teacher_profile)").fetchall()
    tp_col_names = [c["name"] for c in tp_cols] if tp_cols else []
    if tp_col_names and "teacher_id" not in tp_col_names:
        # Old schema with CHECK(id=1) — recreate as per-teacher
        conn.execute("DROP TABLE IF EXISTS teacher_profile")
        conn.commit()
        conn.execute("""
            CREATE TABLE teacher_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER UNIQUE,
                institution_name TEXT DEFAULT '',
                teacher_name TEXT,
                avatar_filename TEXT,
                teaching_years TEXT,
                specialty TEXT,
                philosophy TEXT,
                contact_info TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (teacher_id) REFERENCES admin_users(id)
            )
        """)
        conn.commit()

    # ── P1: Cycle 状态机迁移（核心链路架构设计.md §3）──────────────
    # weekly_records 扶正为 Cycle 表：新增 kind/stage/updated_at，
    # 唯一约束扩展为 (student_id, week_start, kind)。
    # SQLite 无法 ALTER 唯一约束，需重建表（数据量小，幂等）。
    wr_cols = [c["name"] for c in conn.execute("PRAGMA table_info(weekly_records)").fetchall()]
    if wr_cols and "kind" not in wr_cols:
        conn.executescript("""
            CREATE TABLE weekly_records_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                week_start DATE NOT NULL,
                kind TEXT NOT NULL DEFAULT 'weekly',
                stage TEXT NOT NULL DEFAULT 'created',
                paper_submitted INTEGER DEFAULT 0,
                paper_analyzed INTEGER DEFAULT 0,
                exercises_sent INTEGER DEFAULT 0,
                exercises_completed INTEGER DEFAULT 0,
                exercises_graded INTEGER DEFAULT 0,
                report_sent INTEGER DEFAULT 0,
                flashcard_sent INTEGER DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id),
                UNIQUE(student_id, week_start, kind)
            );
            INSERT INTO weekly_records_new (
                id, student_id, week_start, kind, stage,
                paper_submitted, paper_analyzed, exercises_sent, exercises_completed,
                exercises_graded, report_sent, flashcard_sent, notes, created_at
            )
            SELECT id, student_id, week_start, 'weekly',
                CASE
                    WHEN report_sent = 1 THEN 'reported'
                    WHEN exercises_sent = 1 THEN 'exercised'
                    WHEN paper_analyzed = 1 THEN 'graded'
                    WHEN paper_submitted = 1 THEN 'paper_received'
                    ELSE 'created'
                END,
                paper_submitted, paper_analyzed, exercises_sent, exercises_completed,
                exercises_graded, report_sent, flashcard_sent, notes, created_at
            FROM weekly_records;
            DROP TABLE weekly_records;
            ALTER TABLE weekly_records_new RENAME TO weekly_records;
        """)
        conn.commit()

    # ai_tasks 关联 Cycle（按 student_id + week_start 回填）
    task_cols = [c["name"] for c in conn.execute("PRAGMA table_info(ai_tasks)").fetchall()]
    if task_cols and "cycle_id" not in task_cols:
        conn.execute("ALTER TABLE ai_tasks ADD COLUMN cycle_id INTEGER")
        conn.execute("""
            UPDATE ai_tasks SET cycle_id = (
                SELECT wr.id FROM weekly_records wr
                WHERE wr.student_id = ai_tasks.student_id
                  AND wr.week_start = ai_tasks.week_start
                ORDER BY wr.id LIMIT 1
            )
            WHERE week_start IS NOT NULL
        """)
        conn.commit()

    # 监护人同意版本化/撤回（PIPL 合规）：版本号 + 撤回时间
    consent_cols = [c["name"] for c in conn.execute("PRAGMA table_info(parent_consents)").fetchall()]
    if consent_cols:
        if "consent_version" not in consent_cols:
            conn.execute("ALTER TABLE parent_consents ADD COLUMN consent_version TEXT DEFAULT 'v1'")
            conn.commit()
        if "withdrawn_at" not in consent_cols:
            conn.execute("ALTER TABLE parent_consents ADD COLUMN withdrawn_at TIMESTAMP")
            conn.commit()

    # 流水线 analyze 幂等：错题/练习场次关联任务 ID（断点续跑防重复插入）
    if mistake_col_names and "source_task_id" not in mistake_col_names:
        conn.execute("ALTER TABLE mistakes ADD COLUMN source_task_id INTEGER")
        conn.commit()
    session_cols = [c["name"] for c in conn.execute("PRAGMA table_info(practice_sessions)").fetchall()]
    if session_cols and "source_task_id" not in session_cols:
        conn.execute("ALTER TABLE practice_sessions ADD COLUMN source_task_id INTEGER")
        conn.commit()

    conn.commit()


def init_db(db_path: str = DB_PATH) -> None:
    """Create all tables if they don't exist."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        -- ── 业务表 ──────────────────────────────
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            grade TEXT NOT NULL DEFAULT '高二',
            school_type TEXT NOT NULL DEFAULT '住校',
            english_score REAL,
            target_score REAL,
            parent_name TEXT,
            parent_wechat TEXT,
            parent_phone TEXT,
            notes TEXT,
            status TEXT DEFAULT 'active',
            access_code TEXT UNIQUE,
            parent_access_code TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── 学生个性化画像（参考 chat.md 六大部分）────
        CREATE TABLE IF NOT EXISTS student_profiles (
            student_id INTEGER PRIMARY KEY,
            -- Part 1: 基本信息补充
            gender TEXT,
            semester TEXT,
            academic_goal TEXT,
            subject_choice TEXT,
            textbook_version TEXT,

            -- Part 2: 时间全景图
            time_map TEXT DEFAULT '{}',
            weekly_available_hours REAL,
            peak_energy_slots TEXT,
            committed_english_minutes INTEGER,

            -- Part 3: 英语学情
            recent_scores TEXT,
            weak_areas TEXT,
            weak_question_types TEXT,
            score_loss_reason TEXT,
            confused_grammar TEXT,
            existing_resources TEXT,
            vocab_direction TEXT,

            -- Part 4: 深度学习特质
            learning_style TEXT,
            learning_style_detail TEXT DEFAULT '{}',
            learning_medium TEXT,
            vocab_habit TEXT,
            attention_weakness TEXT,
            effective_methods TEXT,
            ineffective_methods TEXT,
            english_identity TEXT,

            -- Part 4.5: 小测评结果
            assessments TEXT DEFAULT '{}',

            -- Part 5: 目标与支持
            target_timeline TEXT,
            one_month_goal TEXT,
            parent_availability TEXT,
            supervision_needed INTEGER DEFAULT 0,
            study_environment TEXT,

            -- Part 6: 孩子的心声
            least_favorite_task TEXT,
            preferred_intensity TEXT,
            aspirational_use TEXT,

            -- 关键抉择
            plan_choices TEXT DEFAULT '{}',
            plan_name TEXT,
            plan_code_name TEXT,

            -- 家长成长任务包完成进度
            parent_task_progress TEXT DEFAULT '{}',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL UNIQUE,
            plan TEXT NOT NULL DEFAULT 'trial',
            price REAL DEFAULT 0,
            monthly_quota INTEGER DEFAULT 0,
            used_count INTEGER DEFAULT 0,
            reset_month TEXT,
            start_date DATE NOT NULL,
            end_date DATE,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        -- weekly_records 即 Cycle 表（学习周期状态机，见 核心链路架构设计.md §3）
        CREATE TABLE IF NOT EXISTS weekly_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            week_start DATE NOT NULL,
            kind TEXT NOT NULL DEFAULT 'weekly',
            stage TEXT NOT NULL DEFAULT 'created',
            paper_submitted INTEGER DEFAULT 0,
            paper_analyzed INTEGER DEFAULT 0,
            exercises_sent INTEGER DEFAULT 0,
            exercises_completed INTEGER DEFAULT 0,
            exercises_graded INTEGER DEFAULT 0,
            report_sent INTEGER DEFAULT 0,
            flashcard_sent INTEGER DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            UNIQUE(student_id, week_start, kind)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            weeks INTEGER DEFAULT 1,
            note TEXT,
            paid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        -- ── 系统设置（成本预算等）────────────────
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── 文件存储 ─────────────────────────────
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            uploader_role TEXT NOT NULL DEFAULT 'parent',
            file_type TEXT NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            week_start DATE,
            file_size INTEGER,
            mime_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        -- ── AI 任务队列 ──────────────────────────
        CREATE TABLE IF NOT EXISTS ai_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            task_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            parent_task_id INTEGER,
            cycle_id INTEGER,
            input_data TEXT,
            output_data TEXT,
            current_step TEXT,
            total_steps INTEGER DEFAULT 7,
            progress INTEGER DEFAULT 0,
            needs_review INTEGER DEFAULT 0,
            error_message TEXT,
            week_start DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (cycle_id) REFERENCES weekly_records(id)
        );

        -- ── LLM 用量 ─────────────────────────────
        CREATE TABLE IF NOT EXISTS llm_usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            call_type TEXT NOT NULL,
            model TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            estimated_cost REAL DEFAULT 0.0,
            duration_ms INTEGER,
            retry_count INTEGER DEFAULT 0,
            cached INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── 教学表 (替代 JSON) ───────────────────
        CREATE TABLE IF NOT EXISTS mistakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            source_exam TEXT,
            question TEXT NOT NULL,
            question_type TEXT,
            correct_answer TEXT,
            user_answer TEXT,
            explanation TEXT,
            knowledge_points TEXT DEFAULT '[]',
            difficulty INTEGER DEFAULT 2,
            mastery_level INTEGER DEFAULT 0,
            review_count INTEGER DEFAULT 0,
            consecutive_correct INTEGER DEFAULT 0,
            last_reviewed_at TIMESTAMP,
            next_review_at TIMESTAMP,
            review_interval_hours REAL DEFAULT 0,
            review_stage INTEGER DEFAULT 0,
            source_task_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS practice_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mistake_id INTEGER NOT NULL,
            user_answer TEXT,
            is_correct INTEGER,
            feedback TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (mistake_id) REFERENCES mistakes(id)
        );

        CREATE TABLE IF NOT EXISTS practice_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            exam_name TEXT,
            status TEXT DEFAULT 'analyzing',
            current_question_index INTEGER DEFAULT 0,
            mistake_ids TEXT DEFAULT '[]',
            source_task_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        -- ── 错因因果链画像 ────────────────────────
        CREATE TABLE IF NOT EXISTS cause_profiles (
            student_id INTEGER PRIMARY KEY,
            primary_cause TEXT,
            primary_evidence TEXT,
            cause_chain TEXT DEFAULT '[]',
            secondary_causes TEXT DEFAULT '[]',
            priority_kps TEXT DEFAULT '[]',
            plain_language TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        -- ── 错因画像历史（跨周对比 / 周报进步叙事）────
        CREATE TABLE IF NOT EXISTS cause_profile_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            week_start TEXT NOT NULL,
            primary_cause TEXT,
            cause_counts TEXT DEFAULT '{}',
            total_count INTEGER DEFAULT 0,
            profile_snapshot TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, week_start),
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        -- ── 未识别知识点池（受控词表归一化未命中，带频次统计，供定期补词）────
        CREATE TABLE IF NOT EXISTS unmapped_kps (
            label TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0,
            first_seen TIMESTAMP,
            last_seen TIMESTAMP
        );

        -- ── 学习方案 ─────────────────────────────
        CREATE TABLE IF NOT EXISTS learning_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL UNIQUE,
            plan_data TEXT NOT NULL DEFAULT '{}',
            weak_point_matrix TEXT DEFAULT '[]',
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS plan_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            week_start DATE NOT NULL,
            change_summary TEXT NOT NULL DEFAULT '{}',
            ai_clinic_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        -- ── 分数历史（用于趋势图）────────────────
        CREATE TABLE IF NOT EXISTS score_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            score REAL NOT NULL,
            score_type TEXT DEFAULT 'weekly_test',
            source_task_id INTEGER,
            week_start DATE,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        -- ── 打卡记录（学生端学习闭环）────────────
        CREATE TABLE IF NOT EXISTS check_ins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            check_in_date DATE NOT NULL,
            content TEXT,
            duration_minutes INTEGER DEFAULT 0,
            source TEXT DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            UNIQUE(student_id, check_in_date)
        );

        -- ── 题库（沉淀 AI 生成题目）──────────────
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT NOT NULL,
            question_type TEXT,
            correct_answer TEXT,
            explanation TEXT,
            knowledge_points TEXT DEFAULT '[]',
            difficulty INTEGER DEFAULT 2,
            source TEXT DEFAULT 'llm',
            usage_count INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── 转介绍/裂变（邀请有礼）──────────────
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_student_id INTEGER NOT NULL,
            referred_student_id INTEGER UNIQUE,
            invite_code TEXT NOT NULL,
            reward_weeks INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            paid_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (referrer_student_id) REFERENCES students(id),
            FOREIGN KEY (referred_student_id) REFERENCES students(id)
        );

        -- ── 家长授权（未成年人数据合规）──────────
        CREATE TABLE IF NOT EXISTS parent_consents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            consent_type TEXT NOT NULL DEFAULT 'data_processing',
            consented_by TEXT NOT NULL,
            contact TEXT,
            ip_address TEXT,
            notes TEXT,
            consent_version TEXT DEFAULT 'v1',
            withdrawn_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        -- ── 数据删除请求（GDPR/未成年人合规）──────
        CREATE TABLE IF NOT EXISTS deletion_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            requested_by TEXT NOT NULL,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            processed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        -- ── AI 内容安全抽检 ──────────────────────
        CREATE TABLE IF NOT EXISTS aigc_safety_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            content_snapshot TEXT,
            safety_status TEXT DEFAULT 'pending',
            issue_flags TEXT DEFAULT '[]',
            reviewed_by TEXT,
            reviewed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES ai_tasks(id)
        );

        -- ── 老师纠错记录 ─────────────────────────
        CREATE TABLE IF NOT EXISTS ai_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            content_type TEXT NOT NULL,       -- 'mistake' | 'question' | 'grading'
            target_id INTEGER,                -- mistake_id / practice_record_id / question_id
            target_field TEXT NOT NULL,       -- 'question' | 'correct_answer' | 'explanation' | 'knowledge_points' | 'is_correct' | 'difficulty' | 'question_type'
            original_value TEXT,
            corrected_value TEXT NOT NULL,
            reason TEXT,
            reviewed_by TEXT,
            status TEXT DEFAULT 'applied',    -- 'applied' | 'reverted'
            resolved_by_task_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES ai_tasks(id),
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        -- ── AI 纠错模式沉淀（用于提示增强）────────
        CREATE TABLE IF NOT EXISTS ai_feedback_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            knowledge_point TEXT,
            content_type TEXT,                -- 'mistake' | 'question' | 'grading'
            issue_type TEXT,                  -- 'wrong_answer' | 'wrong_explanation' | 'wrong_knowledge_point' | 'wrong_grading' | 'other'
            corrected_value TEXT,
            occurrence_count INTEGER DEFAULT 1,
            last_seen_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── 可观测性：告警 ───────────────────────
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT NOT NULL,         -- 'cost_total' | 'cost_student'
            level TEXT NOT NULL,              -- 'warning' | 'critical'
            message TEXT NOT NULL,
            related_id TEXT,                  -- student_id or 'total'
            details TEXT DEFAULT '{}',        -- JSON
            dismissed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dismissed_at TIMESTAMP
        );

        -- ── 可观测性：备份 ───────────────────────
        CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_path TEXT NOT NULL,
            backup_type TEXT NOT NULL DEFAULT 'daily',  -- 'daily' | 'weekly'
            file_size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── 索引 ─────────────────────────────────
        CREATE INDEX IF NOT EXISTS idx_ai_tasks_status ON ai_tasks(status);
        CREATE INDEX IF NOT EXISTS idx_ai_tasks_created_at ON ai_tasks(created_at);
        CREATE INDEX IF NOT EXISTS idx_alerts_dismissed ON alerts(dismissed);

        -- ── 审计日志 ─────────────────────────────
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_type TEXT NOT NULL,
            actor_id TEXT,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            details TEXT,
            ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Admin ────────────────────────────────
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── SMS Verification Codes ───────────────
        CREATE TABLE IF NOT EXISTS sms_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            code TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT 'login',
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Teacher / Institution Profile ─────────
        CREATE TABLE IF NOT EXISTS teacher_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER UNIQUE,
            institution_name TEXT DEFAULT '',
            teacher_name TEXT,
            avatar_filename TEXT,
            teaching_years TEXT,
            specialty TEXT,
            philosophy TEXT,
            contact_info TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES admin_users(id)
        );

        -- ── 元认知复盘表 ──────────────────────────
        CREATE TABLE IF NOT EXISTS metacognitive_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            week_start TEXT NOT NULL,
            template_questions TEXT DEFAULT '{}',
            child_answers TEXT DEFAULT '{}',
            parent_answers TEXT DEFAULT '{}',
            child_mood INTEGER,
            parent_mood INTEGER,
            child_note TEXT,
            parent_note TEXT,
            status TEXT DEFAULT 'draft',
            submitted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            UNIQUE(student_id, week_start)
        );

        -- ── 成就墙 ────────────────────────────────
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            achievement_key TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            icon TEXT DEFAULT '🏆',
            tier INTEGER DEFAULT 1,
            earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            UNIQUE(student_id, achievement_key)
        );

        -- ── 学校与班级 ─────────────────────────────
        CREATE TABLE IF NOT EXISTS schools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            aliases TEXT DEFAULT '[]',
            region TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            grade TEXT,
            teacher_id INTEGER,
            class_code TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (school_id) REFERENCES schools(id),
            FOREIGN KEY (teacher_id) REFERENCES admin_users(id)
        );
    """)
    conn.commit()
    conn.close()

    # Run migrations
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _migrate_db(conn)
    conn.close()


# ═══════════════════════════════════════════════════
# Teacher / Institution Profile
# ═══════════════════════════════════════════════════

def get_teacher_profile(teacher_id: int = None, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Return the profile for a specific teacher, or empty defaults."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM teacher_profile WHERE teacher_id = ?", [teacher_id]).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {
        "teacher_id": teacher_id,
        "institution_name": "",
        "teacher_name": "",
        "avatar_filename": "",
        "teaching_years": "",
        "specialty": "",
        "philosophy": "",
        "contact_info": "",
    }


def save_teacher_profile(teacher_id: int, data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    """Save teacher's institution profile."""
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO teacher_profile (teacher_id, institution_name, teacher_name, avatar_filename,
                                     teaching_years, specialty, philosophy, contact_info)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(teacher_id) DO UPDATE SET
            institution_name = excluded.institution_name,
            teacher_name = excluded.teacher_name,
            avatar_filename = excluded.avatar_filename,
            teaching_years = excluded.teaching_years,
            specialty = excluded.specialty,
            philosophy = excluded.philosophy,
            contact_info = excluded.contact_info,
            updated_at = CURRENT_TIMESTAMP
    """, [teacher_id,
          data.get("institution_name", ""),
          data.get("teacher_name", ""),
          data.get("avatar_filename", "") or "",
          data.get("teaching_years", ""),
          data.get("specialty", ""),
          data.get("philosophy", ""),
          data.get("contact_info", ""),
    ])
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════
# Auth / Admin Users
# ═══════════════════════════════════════════════════

def create_admin_user(username: str, password_hash: str, role: str = "teacher",
                      subject: str = None, db_path: str = DB_PATH) -> int:
    """Create a new admin/teacher user. Returns user id."""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO admin_users (username, password_hash, role, subject) VALUES (?, ?, ?, ?)",
            [username, password_hash, role, subject or '英语'],
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_admin_user(username: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Get admin user by username. Returns dict with id, username, password_hash, role."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT id, username, password_hash, role, created_at FROM admin_users WHERE username = ?",
        [username],
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_admin_users(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """List all admin/teacher users (without password_hash)."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT id, username, role, created_at FROM admin_users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_admin_user(user_id: int, db_path: str = DB_PATH) -> bool:
    """Delete an admin user by id. Returns True if deleted."""
    conn = get_connection(db_path)
    cur = conn.execute("DELETE FROM admin_users WHERE id = ?", [user_id])
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


# ═══════════════════════════════════════════════════
# Flask g-based helpers (兼容原 app.py 模式)
# ═══════════════════════════════════════════════════

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ═══════════════════════════════════════════════════
# Mistake Book Operations (兼容 data_manager.py API)
# ═══════════════════════════════════════════════════

def add_mistake(
    student_id: int,
    source_exam: str = "",
    question: str = "",
    question_type: str = "",
    correct_answer: str = "",
    user_answer: str = "",
    explanation: str = "",
    knowledge_points: List[str] = None,
    difficulty: int = 2,
    error_cause: str = "",
    cause_evidence: str = "",
    passage: str = "",
    source_task_id: int = None,
    db_path: str = DB_PATH,
) -> int:
    """Add a new mistake. Returns the integer mistake ID.

    source_task_id：由流水线 analyze 节点写入，断点续跑重放时用于
    定位并清理本任务上一次尝试的残留（幂等）。
    """
    conn = get_connection(db_path)
    now = _now_iso()
    cur = conn.execute("""
        INSERT INTO mistakes (student_id, source_exam, question, question_type,
            correct_answer, user_answer, explanation, knowledge_points, difficulty,
            error_cause, cause_evidence, passage, source_task_id,
            next_review_at, review_interval_hours, review_stage, last_reviewed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        student_id, source_exam, question, question_type,
        correct_answer, user_answer, explanation,
        json.dumps(knowledge_points or [], ensure_ascii=False), difficulty,
        error_cause, cause_evidence, passage, source_task_id,
        now, 1.0, 0, now
    ])
    conn.commit()
    conn.close()
    return cur.lastrowid


def purge_task_mistakes(task_id: int, db_path: str = DB_PATH) -> int:
    """删除某次任务写入的全部错题及其从属数据（练习记录/题库引用/场次）。

    analyze 节点重放（僵尸任务断点续跑）前调用，保证幂等：
    崩溃窗口 [错题已入库, advance_cycle 未落] 内复活不会造成错题翻倍。
    返回删除的错题数。
    """
    conn = get_connection(db_path)
    try:
        conn.execute("""
            UPDATE questions SET source_mistake_id = NULL
            WHERE source_mistake_id IN (
                SELECT id FROM mistakes WHERE source_task_id = ?)
        """, [task_id])
        conn.execute("""
            DELETE FROM practice_records WHERE mistake_id IN (
                SELECT id FROM mistakes WHERE source_task_id = ?)
        """, [task_id])
        cur = conn.execute(
            "DELETE FROM mistakes WHERE source_task_id = ?", [task_id])
        conn.execute(
            "DELETE FROM practice_sessions WHERE source_task_id = ?", [task_id])
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_mistake(mistake_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM mistakes WHERE id = ?", [mistake_id]).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
    return d


def save_cause_profile(student_id: int, profile: Dict[str, Any],
                       db_path: str = DB_PATH) -> None:
    """Upsert a student's error-cause profile (错因因果链画像)."""
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO cause_profiles (student_id, primary_cause, primary_evidence,
            cause_chain, secondary_causes, priority_kps, plain_language, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id) DO UPDATE SET
            primary_cause=excluded.primary_cause,
            primary_evidence=excluded.primary_evidence,
            cause_chain=excluded.cause_chain,
            secondary_causes=excluded.secondary_causes,
            priority_kps=excluded.priority_kps,
            plain_language=excluded.plain_language,
            updated_at=excluded.updated_at
    """, [
        student_id,
        profile.get("primary_cause") or "",
        profile.get("primary_evidence") or "",
        json.dumps(profile.get("cause_chain") or [], ensure_ascii=False),
        json.dumps(profile.get("secondary_causes") or [], ensure_ascii=False),
        json.dumps(profile.get("priority_kps") or [], ensure_ascii=False),
        profile.get("plain_language") or "",
        _now_iso(),
    ])
    conn.commit()
    conn.close()


def get_cause_profile(student_id: int,
                      db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Read a student's error-cause profile; JSON fields decoded."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM cause_profiles WHERE student_id = ?", [student_id]).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    for k in ("cause_chain", "secondary_causes", "priority_kps"):
        try:
            d[k] = json.loads(d[k] or "[]")
        except Exception:
            d[k] = []
    return d


def save_cause_profile_history(student_id: int, week_start: str, profile: Dict[str, Any],
                               cause_counts: Dict[str, int] = None,
                               db_path: str = DB_PATH) -> None:
    """Upsert a student's per-week error-cause snapshot (跨周对比数据源)。"""
    counts = cause_counts or {}
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO cause_profile_history (student_id, week_start, primary_cause,
            cause_counts, total_count, profile_snapshot, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id, week_start) DO UPDATE SET
            primary_cause=excluded.primary_cause,
            cause_counts=excluded.cause_counts,
            total_count=excluded.total_count,
            profile_snapshot=excluded.profile_snapshot
    """, [
        student_id, week_start, profile.get("primary_cause") or "",
        json.dumps(counts, ensure_ascii=False), sum(counts.values()),
        json.dumps(profile, ensure_ascii=False), _now_iso(),
    ])
    conn.commit()
    conn.close()


def get_cause_profile_history(student_id: int, week_start: str = None,
                              before: str = None,
                              db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """取错因画像历史：
    - week_start 指定 → 该周记录
    - before 指定 → 早于该周的最新一条（上周对比用）
    - 都未指定 → 最近一条
    JSON 字段解码后返回。
    """
    conn = get_connection(db_path)
    if week_start:
        row = conn.execute(
            "SELECT * FROM cause_profile_history WHERE student_id = ? AND week_start = ?",
            [student_id, week_start]).fetchone()
    elif before:
        row = conn.execute(
            "SELECT * FROM cause_profile_history WHERE student_id = ? AND week_start < ?"
            " ORDER BY week_start DESC LIMIT 1",
            [student_id, before]).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM cause_profile_history WHERE student_id = ?"
            " ORDER BY week_start DESC LIMIT 1",
            [student_id]).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    for k in ("cause_counts", "profile_snapshot"):
        try:
            d[k] = json.loads(d[k] or "{}")
        except Exception:
            d[k] = {}
    return d


def record_unmapped_kps(labels: List[str], db_path: str = DB_PATH) -> None:
    """记录未识别知识点标签（受控词表归一化未命中），按标签累加频次。
    用于定期查看高频未识别词，补充词表 aliases 或新增条目。"""
    labels = [l for l in (labels or []) if isinstance(l, str) and l.strip()]
    if not labels:
        return
    conn = get_connection(db_path)
    now = _now_iso()
    for label in labels:
        conn.execute("""
            INSERT INTO unmapped_kps (label, count, first_seen, last_seen)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(label) DO UPDATE SET
                count = count + 1, last_seen = excluded.last_seen
        """, [label.strip(), now, now])
    conn.commit()
    conn.close()


def get_unmapped_kps(top_n: int = 50, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """取未识别知识点池（按频次降序），供词表补充决策。"""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT label, count, first_seen, last_seen FROM unmapped_kps"
        " ORDER BY count DESC LIMIT ?", [top_n]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_mistake(mistake_id: int, updates: Dict[str, Any], db_path: str = DB_PATH) -> bool:
    if not updates:
        return False
    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM mistakes WHERE id = ?", [mistake_id]).fetchone()
    if not row:
        conn.close()
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    conn.execute(f"UPDATE mistakes SET {set_clause}, last_reviewed_at = ? WHERE id = ?",
                 values + [_now_iso(), mistake_id])
    conn.commit()
    conn.close()
    return True


# ═══════════════════════════════════════════════════
# Spaced Repetition (Ebbinghaus intervals)
# ═══════════════════════════════════════════════════

_EBBINGHAUS_INTERVALS = [
    1.0,     # Stage 0: 1 hour
    24.0,    # Stage 1: 1 day
    48.0,    # Stage 2: 2 days
    96.0,    # Stage 3: 4 days
    168.0,   # Stage 4: 7 days
    360.0,   # Stage 5: 15 days
    720.0,   # Stage 6: 30 days
    1440.0,  # Stage 7: 60 days
]
_MAX_REVIEW_STAGE = len(_EBBINGHAUS_INTERVALS) - 1


def _next_review_at(stage: int, from_time: datetime = None) -> str:
    """Calculate the next review timestamp for a given stage."""
    if stage > _MAX_REVIEW_STAGE:
        stage = _MAX_REVIEW_STAGE
    interval_hours = _EBBINGHAUS_INTERVALS[stage]
    base = from_time or datetime.now()
    return (base + timedelta(hours=interval_hours)).isoformat(timespec="seconds")


def record_practice(mistake_id: int, user_answer: str, is_correct: bool,
                    feedback: str = "", db_path: str = DB_PATH) -> bool:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM mistakes WHERE id = ?", [mistake_id]).fetchone()
    if not row:
        conn.close()
        return False

    now = _now_iso()

    # 插入练习记录
    conn.execute("""
        INSERT INTO practice_records (mistake_id, user_answer, is_correct, feedback)
        VALUES (?, ?, ?, ?)
    """, [mistake_id, user_answer, int(is_correct), feedback])

    # Ebbinghaus scheduling
    cur_stage = row["review_stage"] or 0
    new_review_count = (row["review_count"] or 0) + 1

    if is_correct:
        new_consecutive = (row["consecutive_correct"] or 0) + 1
        # Advance to next stage
        new_stage = min(_MAX_REVIEW_STAGE, cur_stage + 1)
        # Mastery: blend stage progress and consecutive streak
        new_mastery = min(100, int(new_stage / _MAX_REVIEW_STAGE * 70 + new_consecutive * 10))
    else:
        new_consecutive = 0
        # Reset to stage 1 (1 day) on error — partial reset, not back to zero
        new_stage = 1
        new_mastery = max(0, int(cur_stage / _MAX_REVIEW_STAGE * 50))

    new_interval = _EBBINGHAUS_INTERVALS[new_stage]
    next_review = _next_review_at(new_stage)

    conn.execute("""
        UPDATE mistakes SET
            review_count = ?, consecutive_correct = ?, mastery_level = ?,
            last_reviewed_at = ?, next_review_at = ?,
            review_interval_hours = ?, review_stage = ?
        WHERE id = ?
    """, [new_review_count, new_consecutive, new_mastery,
          now, next_review, new_interval, new_stage, mistake_id])
    conn.commit()
    conn.close()
    return True


def get_due_reviews(student_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get mistakes due for review now (next_review_at <= now) for a student."""
    conn = get_connection(db_path)
    now = _now_iso()
    rows = conn.execute("""
        SELECT * FROM mistakes
        WHERE student_id = ? AND consecutive_correct < 2
          AND next_review_at IS NOT NULL AND next_review_at <= ?
        ORDER BY next_review_at ASC
    """, [student_id, now]).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
        d["is_mastered"] = d.get("consecutive_correct", 0) >= 2
        results.append(d)
    return results


def get_review_stats(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get spaced repetition review stats for a student."""
    conn = get_connection(db_path)
    now = _now_iso()
    due_count = conn.execute("""
        SELECT COUNT(*) FROM mistakes
        WHERE student_id = ? AND consecutive_correct < 2
          AND next_review_at IS NOT NULL AND next_review_at <= ?
    """, [student_id, now]).fetchone()[0]

    # Upcoming reviews in next 3 days
    cutoff = (datetime.now() + timedelta(days=3)).isoformat(timespec="seconds")
    upcoming = conn.execute("""
        SELECT COUNT(*) FROM mistakes
        WHERE student_id = ? AND consecutive_correct < 2
          AND next_review_at IS NOT NULL AND next_review_at > ? AND next_review_at <= ?
    """, [student_id, now, cutoff]).fetchone()[0]

    # Stage distribution
    stage_rows = conn.execute("""
        SELECT review_stage, COUNT(*) as cnt FROM mistakes
        WHERE student_id = ? AND consecutive_correct < 2
        GROUP BY review_stage
    """, [student_id]).fetchall()
    conn.close()

    stage_dist = {r["review_stage"]: r["cnt"] for r in stage_rows}

    return {
        "due_now": due_count,
        "upcoming_3d": upcoming,
        "stage_distribution": stage_dist,
        "total_active": sum(stage_dist.values()),
    }


def is_mastered(mistake_id: int, db_path: str = DB_PATH) -> bool:
    conn = get_connection(db_path)
    row = conn.execute("SELECT consecutive_correct FROM mistakes WHERE id = ?",
                       [mistake_id]).fetchone()
    conn.close()
    if row is None:
        return False
    return row["consecutive_correct"] >= 2


def get_unmastered_mistakes(student_id: int = None, knowledge_point: str = None,
                            db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    query = "SELECT * FROM mistakes WHERE consecutive_correct < 2"
    params = []
    if student_id is not None:
        query += " AND student_id = ?"
        params.append(student_id)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
        if knowledge_point and knowledge_point not in d["knowledge_points"]:
            continue
        results.append(d)
    return results


def get_weak_knowledge_points(student_id: int = None, top_n: int = 5,
                              db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    query = "SELECT knowledge_points, consecutive_correct FROM mistakes"
    params = []
    if student_id is not None:
        query += " WHERE student_id = ?"
        params.append(student_id)
    rows = conn.execute(query, params).fetchall()
    conn.close()

    kp_stats: Dict[str, Dict[str, int]] = {}
    for r in rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "mastered": 0, "unmastered": 0}
            kp_stats[kp]["total"] += 1
            if r["consecutive_correct"] >= 2:
                kp_stats[kp]["mastered"] += 1
            else:
                kp_stats[kp]["unmastered"] += 1

    sorted_kp = sorted(
        kp_stats.items(),
        key=lambda x: (-x[1]["unmastered"], x[1]["mastered"] / max(x[1]["total"], 1)),
    )
    return [
        {
            "knowledge_point": kp,
            "total_mistakes": s["total"],
            "unmastered": s["unmastered"],
            "mastery_rate": round(s["mastered"] / s["total"] * 100, 1),
        }
        for kp, s in sorted_kp[:top_n]
    ]


# ═══════════════════════════════════════════════════
# Session Operations
# ═══════════════════════════════════════════════════

def create_session(student_id: int, exam_name: str = "",
                   source_task_id: int = None,
                   db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO practice_sessions (student_id, exam_name, status, source_task_id)
        VALUES (?, ?, 'analyzing', ?)
    """, [student_id, exam_name, source_task_id])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_session(session_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM practice_sessions WHERE id = ?",
                       [session_id]).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["mistake_ids"] = json.loads(d.get("mistake_ids", "[]"))
    return d


def update_session(session_id: int, updates: Dict[str, Any],
                   db_path: str = DB_PATH) -> bool:
    if not updates:
        return False
    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM practice_sessions WHERE id = ?",
                       [session_id]).fetchone()
    if not row:
        conn.close()
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    conn.execute(f"UPDATE practice_sessions SET {set_clause}, updated_at = ? WHERE id = ?",
                 values + [_now_iso(), session_id])
    conn.commit()
    conn.close()
    return True


def add_mistake_to_session(session_id: int, mistake_id: int,
                           db_path: str = DB_PATH) -> bool:
    conn = get_connection(db_path)
    row = conn.execute("SELECT mistake_ids FROM practice_sessions WHERE id = ?",
                       [session_id]).fetchone()
    if not row:
        conn.close()
        return False
    ids = json.loads(row["mistake_ids"] or "[]")
    if mistake_id not in ids:
        ids.append(mistake_id)
    conn.execute("UPDATE practice_sessions SET mistake_ids = ?, updated_at = ? WHERE id = ?",
                 [json.dumps(ids), _now_iso(), session_id])
    conn.commit()
    conn.close()
    return True


def list_sessions(student_id: int = None, status: str = None,
                  db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    query = "SELECT * FROM practice_sessions WHERE 1=1"
    params = []
    if student_id is not None:
        query += " AND student_id = ?"
        params.append(student_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY updated_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_next_practice_target(session_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    session = get_session(session_id, db_path)
    if not session:
        return None
    for mid in session.get("mistake_ids", []):
        if not is_mastered(mid, db_path):
            return get_mistake(mid, db_path)
    return None


def is_session_completed(session_id: int, db_path: str = DB_PATH) -> bool:
    session = get_session(session_id, db_path)
    if not session:
        return False
    for mid in session.get("mistake_ids", []):
        if not is_mastered(mid, db_path):
            return False
    return True


# ═══════════════════════════════════════════════════
# Weekly Report Operations
# ═══════════════════════════════════════════════════

def get_current_week_range() -> tuple:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return (monday.isoformat(), sunday.isoformat())


def get_week_start() -> str:
    """Return Monday of current week in ISO format."""
    return (date.today() - timedelta(days=date.today().weekday())).isoformat()


def get_weekly_stats(student_id: int, week_start: str, week_end: str = None,
                     db_path: str = DB_PATH) -> Dict[str, Any]:
    conn = get_connection(db_path)
    if week_end is None:
        week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()

    new_mistakes = conn.execute("""
        SELECT COUNT(*) FROM mistakes
        WHERE student_id = ? AND date(created_at) BETWEEN ? AND ?
    """, [student_id, week_start, week_end]).fetchone()[0]

    # 统计本周掌握的错题（last_reviewed_at 在本周且已达到 mastery）
    mastered = conn.execute("""
        SELECT COUNT(*) FROM mistakes
        WHERE student_id = ? AND consecutive_correct >= 2
        AND date(last_reviewed_at) BETWEEN ? AND ?
    """, [student_id, week_start, week_end]).fetchone()[0]

    conn.close()
    return {
        "new_mistakes_count": new_mistakes,
        "mastered_count": mastered,
        "weak_areas": get_weak_knowledge_points(student_id, top_n=5, db_path=db_path),
    }


def get_weekly_comparison(student_id: int, week_start: str, weeks: int = 4,
                          db_path: str = DB_PATH) -> Dict[str, Any]:
    """Return multi-week hard metrics for the parent weekly report.

    Returns a dict with:
      - weeks: list of week_start strings (oldest -> current)
      - new_mistakes: list of int counts per week
      - mastered_count: list of int counts per week
      - accuracy: list of score_history accuracy values per week (None if missing)
      - knowledge_point_trends: {kp: [count, ...]} for current top 5 weak areas
      - onboarding_accuracy: first weekly_test score ever recorded (or None)
      - current_accuracy: most recent weekly_test score (or None)
    """
    conn = get_connection(db_path)
    base = date.fromisoformat(week_start)
    week_starts = [(base - timedelta(days=7 * i)).isoformat() for i in range(weeks - 1, -1, -1)]

    # New mistakes per week
    new_mistakes = []
    mastered_count = []
    for ws in week_starts:
        we = (date.fromisoformat(ws) + timedelta(days=6)).isoformat()
        new_mistakes.append(conn.execute("""
            SELECT COUNT(*) FROM mistakes
            WHERE student_id = ? AND date(created_at) BETWEEN ? AND ?
        """, [student_id, ws, we]).fetchone()[0])
        mastered_count.append(conn.execute("""
            SELECT COUNT(*) FROM mistakes
            WHERE student_id = ? AND consecutive_correct >= 2
            AND date(last_reviewed_at) BETWEEN ? AND ?
        """, [student_id, ws, we]).fetchone()[0])

    # Accuracy per week from score_history (weekly_test only)
    accuracy = []
    for ws in week_starts:
        row = conn.execute("""
            SELECT score FROM score_history
            WHERE student_id = ? AND score_type = 'weekly_test' AND week_start = ?
            ORDER BY created_at DESC LIMIT 1
        """, [student_id, ws]).fetchone()
        accuracy.append(row["score"] if row else None)

    # Knowledge point trends for current top 5 weak areas
    weak_areas = get_weak_knowledge_points(student_id, top_n=5, db_path=db_path)
    kp_trends: Dict[str, List[int]] = {}
    for wa in weak_areas:
        kp = wa["knowledge_point"]
        kp_trends[kp] = []
        for ws in week_starts:
            we = (date.fromisoformat(ws) + timedelta(days=6)).isoformat()
            cnt = conn.execute("""
                SELECT COUNT(*) FROM mistakes
                WHERE student_id = ? AND date(created_at) BETWEEN ? AND ?
                AND knowledge_points LIKE ?
            """, [student_id, ws, we, f'%"{kp}"%']).fetchone()[0]
            kp_trends[kp].append(cnt)

    # Knowledge point mastery rate trends for current top 5 weak areas
    kp_mastery_trends = get_knowledge_point_mastery_trends(
        student_id, week_start, weeks, weak_areas=weak_areas, db_path=db_path
    )

    # Onboarding vs current accuracy
    first_score = conn.execute("""
        SELECT score FROM score_history
        WHERE student_id = ? AND score_type = 'weekly_test'
        ORDER BY created_at ASC LIMIT 1
    """, [student_id]).fetchone()
    last_score = conn.execute("""
        SELECT score FROM score_history
        WHERE student_id = ? AND score_type = 'weekly_test'
        ORDER BY created_at DESC LIMIT 1
    """, [student_id]).fetchone()

    conn.close()
    return {
        "weeks": week_starts,
        "new_mistakes": new_mistakes,
        "mastered_count": mastered_count,
        "accuracy": accuracy,
        "knowledge_point_trends": kp_trends,
        "knowledge_point_mastery_trends": kp_mastery_trends,
        "onboarding_accuracy": first_score["score"] if first_score else None,
        "current_accuracy": last_score["score"] if last_score else None,
    }


def get_knowledge_point_mastery_trends(
    student_id: int,
    week_start: str,
    weeks: int = 4,
    weak_areas: List[Dict[str, Any]] = None,
    db_path: str = DB_PATH,
) -> Dict[str, List[float]]:
    """Return weekly mastery rate (0-100) for each top weak knowledge point.

    Mastery rate = percentage of mistakes tagged with this knowledge point that
    had consecutive_correct >= 2 as of the end of each week. Mistakes created
    after a given week are excluded from that week's denominator.

    Returns: {kp_name: [rate_week1, rate_week2, ..., rate_week_current]}
    """
    if weak_areas is None:
        weak_areas = get_weak_knowledge_points(student_id, top_n=5, db_path=db_path)

    kp_names = [wa["knowledge_point"] for wa in weak_areas]
    if not kp_names:
        return {}

    base = date.fromisoformat(week_start)
    week_ends = [
        (base - timedelta(days=7 * i) + timedelta(days=6)).isoformat()
        for i in range(weeks - 1, -1, -1)
    ]

    conn = get_connection(db_path)

    # Map each KP -> mistake ids created on or before each week end.
    kp_mistake_ids: Dict[str, List[int]] = {kp: [] for kp in kp_names}
    all_mistake_ids: set = set()
    for kp in kp_names:
        rows = conn.execute(
            "SELECT id, created_at FROM mistakes WHERE student_id = ? AND knowledge_points LIKE ?",
            [student_id, f'%"{kp}"%'],
        ).fetchall()
        for r in rows:
            mid = r["id"]
            kp_mistake_ids[kp].append((mid, r["created_at"][:10]))
            all_mistake_ids.add(mid)

    if not all_mistake_ids:
        conn.close()
        return {kp: [0.0] * weeks for kp in kp_names}

    # Fetch all practice records for the relevant mistakes.
    placeholders = ",".join("?" for _ in all_mistake_ids)
    pr_rows = conn.execute(
        f"""
        SELECT mistake_id, is_correct, created_at
        FROM practice_records
        WHERE mistake_id IN ({placeholders})
        ORDER BY created_at ASC
        """,
        list(all_mistake_ids),
    ).fetchall()

    pr_by_mistake: Dict[int, List[Dict[str, Any]]] = {}
    for pr in pr_rows:
        mid = pr["mistake_id"]
        pr_by_mistake.setdefault(mid, []).append({
            "is_correct": bool(pr["is_correct"]),
            "created_at": pr["created_at"][:10],
        })

    conn.close()

    result: Dict[str, List[float]] = {}
    for kp in kp_names:
        mistakes = kp_mistake_ids[kp]
        rates: List[float] = []
        for week_end in week_ends:
            # Only count mistakes that existed by the end of this week.
            active_mistakes = [mid for mid, created in mistakes if created <= week_end]
            total = len(active_mistakes)
            if total == 0:
                rates.append(0.0)
                continue

            mastered = 0
            for mid in active_mistakes:
                consecutive = 0
                for p in pr_by_mistake.get(mid, []):
                    if p["created_at"] > week_end:
                        break
                    if p["is_correct"]:
                        consecutive += 1
                    else:
                        consecutive = 0
                if consecutive >= 2:
                    mastered += 1
            rates.append(round(mastered / total * 100, 1))
        result[kp] = rates

    return result


# ═══════════════════════════════════════════════════
# AI Task Operations
# ═══════════════════════════════════════════════════

def create_task(student_id: int, task_type: str, input_data: Dict = None,
                week_start: str = None, total_steps: int = 7,
                db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO ai_tasks (student_id, task_type, input_data, week_start, total_steps, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    """, [student_id, task_type, json.dumps(input_data or {}, ensure_ascii=False),
          week_start or get_week_start(), total_steps])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_task(task_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM ai_tasks WHERE id = ?", [task_id]).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["input_data"] = json.loads(d.get("input_data", "{}"))
    d["output_data"] = json.loads(d.get("output_data", "{}")) if d.get("output_data") else None
    return d


def update_task(task_id: int, updates: Dict[str, Any], db_path: str = DB_PATH) -> bool:
    if not updates:
        return False
    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM ai_tasks WHERE id = ?", [task_id]).fetchone()
    if not row:
        conn.close()
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    conn.execute(f"UPDATE ai_tasks SET {set_clause} WHERE id = ?", values + [task_id])
    conn.commit()
    conn.close()
    return True


def mark_task_done(task_id: int, output_data: Dict = None,
                   db_path: str = DB_PATH) -> None:
    # P3-13：审核闸门移除，needs_review 恒 0（列保留以兼容历史数据）
    conn = get_connection(db_path)
    conn.execute("""
        UPDATE ai_tasks SET status = 'done', output_data = ?, needs_review = 0,
        progress = 100, completed_at = ?
        WHERE id = ?
    """, [json.dumps(output_data or {}, ensure_ascii=False), _now_iso(), task_id])
    conn.commit()
    conn.close()


def mark_task_failed(task_id: int, error_message: str, db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("""
        UPDATE ai_tasks SET status = 'failed', error_message = ?, completed_at = ?
        WHERE id = ?
    """, [error_message, _now_iso(), task_id])
    conn.commit()
    conn.close()


def update_task_progress(task_id: int, current_step: str, progress: int,
                         db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("""
        UPDATE ai_tasks SET status = 'processing', current_step = ?, progress = ?
        WHERE id = ?
    """, [current_step, progress, task_id])
    conn.commit()
    conn.close()


def get_pending_tasks(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM ai_tasks WHERE status = 'pending' ORDER BY created_at ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════
# File Operations
# ═══════════════════════════════════════════════════

def add_file(student_id: int, uploader_role: str, file_type: str,
             filename: str, original_filename: str, week_start: str = None,
             file_size: int = 0, mime_type: str = "",
             db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO files (student_id, uploader_role, file_type, filename,
            original_filename, week_start, file_size, mime_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [student_id, uploader_role, file_type, filename, original_filename,
          week_start or get_week_start(), file_size, mime_type])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_file(file_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM files WHERE id = ?", [file_id]).fetchone()
    conn.close()
    return dict(row) if row else None


def get_student_files(student_id: int, file_type: str = None,
                      db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    query = "SELECT * FROM files WHERE student_id = ?"
    params = [student_id]
    if file_type:
        query += " AND file_type = ?"
        params.append(file_type)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════
# Weekly Records Operations
# ═══════════════════════════════════════════════════

def get_or_create_weekly_record(student_id: int, week_start: str = None,
                                kind: str = "weekly",
                                db_path: str = DB_PATH) -> Dict[str, Any]:
    """获取或创建 Cycle 记录（weekly_records 表，kind: weekly|diagnostic）。"""
    if week_start is None:
        week_start = get_week_start()
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT * FROM weekly_records
        WHERE student_id = ? AND week_start = ? AND kind = ?
    """, [student_id, week_start, kind]).fetchone()
    if not row:
        conn.execute("""
            INSERT OR IGNORE INTO weekly_records (student_id, week_start, kind)
            VALUES (?, ?, ?)
        """, [student_id, week_start, kind])
        conn.commit()
        row = conn.execute("""
            SELECT * FROM weekly_records
            WHERE student_id = ? AND week_start = ? AND kind = ?
        """, [student_id, week_start, kind]).fetchone()
    conn.close()
    return dict(row)


def update_weekly_record(student_id: int, week_start: str = None,
                         kind: str = "weekly", db_path: str = DB_PATH,
                         **fields) -> bool:
    if week_start is None:
        week_start = get_week_start()
    # ensure record exists
    get_or_create_weekly_record(student_id, week_start, kind, db_path)
    conn = get_connection(db_path)
    fields["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values())
    conn.execute(f"""
        UPDATE weekly_records SET {set_clause}
        WHERE student_id = ? AND week_start = ? AND kind = ?
    """, values + [student_id, week_start, kind])
    conn.commit()
    conn.close()
    return True


# ═══════════════════════════════════════════════════
# Learning Plan Operations
# ═══════════════════════════════════════════════════

def save_learning_plan(student_id: int, plan_data: Dict, weak_point_matrix: List = None,
                       db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("""
        INSERT OR REPLACE INTO learning_plans (student_id, plan_data, weak_point_matrix, updated_at)
        VALUES (?, ?, ?, ?)
    """, [student_id, json.dumps(plan_data, ensure_ascii=False),
          json.dumps(weak_point_matrix or [], ensure_ascii=False), _now_iso()])
    conn.commit()
    conn.close()


def get_learning_plan(student_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM learning_plans WHERE student_id = ?",
                       [student_id]).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["plan_data"] = json.loads(d.get("plan_data", "{}"))
    d["weak_point_matrix"] = json.loads(d.get("weak_point_matrix", "[]"))
    return d


def add_plan_update(student_id: int, week_start: str, change_summary: Dict,
                    ai_clinic_content: str = "", db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO plan_updates (student_id, week_start, change_summary, ai_clinic_content)
        VALUES (?, ?, ?, ?)
    """, [student_id, week_start, json.dumps(change_summary, ensure_ascii=False),
          ai_clinic_content])
    conn.commit()
    conn.close()
    return cur.lastrowid


# ═══════════════════════════════════════════════════
# Score History & Learning Analytics
# ═══════════════════════════════════════════════════

def record_score(student_id: int, score: float, score_type: str = "weekly_test",
                 source_task_id: int = None, week_start: str = None,
                 note: str = "", db_path: str = DB_PATH) -> int:
    """Record a score for a student. Returns score_history id."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO score_history (student_id, score, score_type, source_task_id, week_start, note)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [student_id, score, score_type, source_task_id,
          week_start or get_week_start(), note])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_score_history(student_id: int, limit: int = 20, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get score history for a student."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM score_history
        WHERE student_id = ?
        ORDER BY created_at ASC
        LIMIT ?
    """, [student_id, limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_student_learning_stats(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get comprehensive learning stats for a single student."""
    conn = get_connection(db_path)

    student = get_student(student_id, db_path)

    # Score history
    scores = get_score_history(student_id, limit=50, db_path=db_path)

    # Mistake stats
    mistake_stats = conn.execute("""
        SELECT
            COUNT(*) as total_mistakes,
            SUM(CASE WHEN consecutive_correct >= 2 THEN 1 ELSE 0 END) as mastered_mistakes,
            SUM(review_count) as total_reviews
        FROM mistakes
        WHERE student_id = ?
    """, [student_id]).fetchone()

    # Knowledge points mastery
    kp_rows = conn.execute("""
        SELECT knowledge_points, consecutive_correct
        FROM mistakes
        WHERE student_id = ?
    """, [student_id]).fetchall()

    kp_stats: Dict[str, Dict[str, int]] = {}
    for r in kp_rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "mastered": 0}
            kp_stats[kp]["total"] += 1
            if r["consecutive_correct"] >= 2:
                kp_stats[kp]["mastered"] += 1

    # Sort by total mistakes descending
    kp_list = sorted(
        [{"knowledge_point": kp, **s,
          "mastery_rate": round(s["mastered"] / s["total"] * 100, 1)}
         for kp, s in kp_stats.items()],
        key=lambda x: (-x["total"], -x["mastery_rate"])
    )

    # Weekly activity (last 8 weeks)
    weekly_rows = conn.execute("""
        SELECT week_start, paper_submitted, paper_analyzed, exercises_sent,
               exercises_completed, exercises_graded, report_sent
        FROM weekly_records
        WHERE student_id = ?
        ORDER BY week_start DESC
        LIMIT 8
    """, [student_id]).fetchall()

    # Practice accuracy (recent 30 records)
    practice_rows = conn.execute("""
        SELECT pr.is_correct
        FROM practice_records pr
        JOIN mistakes m ON m.id = pr.mistake_id
        WHERE m.student_id = ?
        ORDER BY pr.created_at DESC
        LIMIT 30
    """, [student_id]).fetchall()

    # Recent check-ins (last 14 days) for streak achievement
    since = (date.today() - timedelta(days=14)).isoformat()
    check_in_rows = conn.execute("""
        SELECT DISTINCT check_in_date FROM check_ins
        WHERE student_id = ? AND check_in_date >= ?
        ORDER BY check_in_date DESC
    """, [student_id, since]).fetchall()

    conn.close()

    total_practice = len(practice_rows)
    correct_practice = sum(1 for r in practice_rows if r["is_correct"])
    practice_accuracy = round(correct_practice / total_practice * 100, 1) if total_practice > 0 else 0

    # Generate data-driven achievement cards
    achievements = []
    mastered_kps = [kp for kp in kp_list if kp.get("mastery_rate", 0) >= 80]
    if mastered_kps:
        top_kps = ", ".join(kp["knowledge_point"] for kp in mastered_kps[:5])
        more = f"等 {len(mastered_kps)} 个" if len(mastered_kps) > 5 else ""
        achievements.append({
            "title": "🎯 知识点突破",
            "content": f"已掌握 {len(mastered_kps)} 个知识点：{top_kps}{more}。把这些本领刻进长期记忆！",
            "source": "mistake_book",
        })

    mastered_count = mistake_stats["mastered_mistakes"] or 0
    if mastered_count > 0:
        achievements.append({
            "title": "✅ 错题攻克",
            "content": f"累计 {mastered_count} 道错题已被你拿下，连续答对 2 次，正式移出薄弱清单。",
            "source": "mistake_book",
        })

    if practice_accuracy >= 70 and total_practice >= 5:
        achievements.append({
            "title": "📈 稳定发挥",
            "content": f"近期 {total_practice} 次练习正确率达到 {practice_accuracy}%，状态在线，继续保持！",
            "source": "practice",
        })
    elif practice_accuracy >= 50 and total_practice >= 5:
        achievements.append({
            "title": "🚧 稳步提升",
            "content": f"近期练习正确率 {practice_accuracy}%，错题正在变成你的台阶。",
            "source": "practice",
        })

    # Check-in streak
    if check_in_rows:
        today = date.today().isoformat()
        streak = 0
        for i, r in enumerate(check_in_rows):
            expected = (date.today() - timedelta(days=i)).isoformat()
            if r["check_in_date"] == expected:
                streak += 1
            else:
                break
        if streak >= 1:
            achievements.append({
                "title": "🔥 连续打卡",
                "content": f"已连续打卡 {streak} 天。习惯的力量，比天赋更可靠。",
                "source": "check_in",
            })

    # Spaced repetition stats
    review_stats = get_review_stats(student_id, db_path=db_path)

    return {
        "student": student,
        "target_score": student.get("target_score") if student else None,
        "current_score": student.get("english_score") if student else None,
        "scores": scores,
        "score_trend": [s["score"] for s in scores],
        "mistakes": {
            "total": mistake_stats["total_mistakes"] or 0,
            "mastered": mastered_count,
            "in_progress": (mistake_stats["total_mistakes"] or 0) - (mistake_stats["mastered_mistakes"] or 0),
            "total_reviews": mistake_stats["total_reviews"] or 0,
            "due_now": review_stats["due_now"],
            "upcoming_3d": review_stats["upcoming_3d"],
        },
        "knowledge_points": kp_list,
        "weekly_activity": [dict(r) for r in weekly_rows],
        "practice_accuracy": practice_accuracy,
        "practice_count_recent": total_practice,
        "achievements": achievements,
        "earned_achievements": check_and_award_achievements(student_id, db_path=db_path),
    }


# ═══════════════════════════════════════════════════
# Achievement Wall — 成就墙
# ═══════════════════════════════════════════════════

# Achievement definitions: (key, title_template, description_template, icon, tiers)
# Each tier is (suffix, threshold, label) — e.g. ("_5", 5, "5道")
ACHIEVEMENT_DEFS = [
    # ── 错题攻克 ──
    {
        "key": "mistake_slayer",
        "title": "错题克星",
        "icon": "⚔️",
        "description": "累计攻克 {threshold} 道错题",
        "tiers": [
            ("_5", 5, "5道"), ("_10", 10, "10道"), ("_25", 25, "25道"), ("_50", 50, "50道"),
        ],
        "check": lambda stats: stats.get("mastered_mistakes", 0),
    },
    # ── 知识点突破 ──
    {
        "key": "kp_master",
        "title": "学识渊博",
        "icon": "📚",
        "description": "掌握 {threshold} 个知识点（掌握率≥80%）",
        "tiers": [
            ("_3", 3, "3个"), ("_5", 5, "5个"), ("_10", 10, "10个"), ("_20", 20, "20个"),
        ],
        "check": lambda stats: stats.get("mastered_kp_count", 0),
    },
    # ── 连续打卡 ──
    {
        "key": "streak",
        "title": "打卡先锋",
        "icon": "🔥",
        "description": "连续打卡 {threshold} 天",
        "tiers": [
            ("_3", 3, "3天"), ("_7", 7, "7天"), ("_14", 14, "14天"), ("_30", 30, "30天"),
        ],
        "check": lambda stats: stats.get("check_in_streak", 0),
    },
    # ── 练习正确率 ──
    {
        "key": "accuracy",
        "title": "精准练习",
        "icon": "🎯",
        "description": "近期练习正确率达到 {threshold}%（至少20次）",
        "tiers": [
            ("_70", 70, "70%"), ("_80", 80, "80%"), ("_90", 90, "90%"),
        ],
        "check": lambda stats: stats.get("practice_accuracy", 0) if stats.get("practice_count_recent", 0) >= 20 else 0,
    },
    # ── 活跃周数 ──
    {
        "key": "active_weeks",
        "title": "持之以恒",
        "icon": "📅",
        "description": "累计活跃 {threshold} 周",
        "tiers": [
            ("_4", 4, "4周"), ("_8", 8, "8周"), ("_16", 16, "16周"),
        ],
        "check": lambda stats: stats.get("active_weeks", 0),
    },
    # ── 分数跃升 ──
    {
        "key": "score_jump",
        "title": "飞跃进步",
        "icon": "🚀",
        "description": "英语成绩提升 {threshold} 分",
        "tiers": [
            ("_5", 5, "5分"), ("_10", 10, "10分"), ("_20", 20, "20分"),
        ],
        "check": lambda stats: stats.get("score_improvement", 0),
    },
    # ── 艾宾浩斯毕业 ──
    {
        "key": "ebbinghaus_master",
        "title": "记忆大师",
        "icon": "🧠",
        "description": "有 {threshold} 道错题完成全部8阶艾宾浩斯复习",
        "tiers": [
            ("_1", 1, "1道"), ("_5", 5, "5道"), ("_10", 10, "10道"),
        ],
        "check": lambda stats: stats.get("ebbinghaus_graduated", 0),
    },
    # ── 全勤周 ──
    {
        "key": "perfect_week",
        "title": "完美一周",
        "icon": "🌟",
        "description": "一周内打卡满 {threshold} 天",
        "tiers": [
            ("_5", 5, "5天"), ("_7", 7, "7天"),
        ],
        "check": lambda stats: stats.get("max_weekly_checkins", 0),
    },
    # ── 首次突破 ──
    {
        "key": "first_blood",
        "title": "初露锋芒",
        "icon": "💡",
        "description": "首次攻克错题，迈出第一步",
        "tiers": [
            ("", 1, "首次"),
        ],
        "check": lambda stats: 1 if stats.get("mastered_mistakes", 0) >= 1 else 0,
    },
    # ── 全面掌握 ──
    {
        "key": "full_mastery",
        "title": "学霸认证",
        "icon": "👑",
        "description": "本学期所有知识点掌握率达到100%",
        "tiers": [
            ("", 1, "达成"),
        ],
        "check": lambda stats: 1 if stats.get("all_kps_mastered", False) else 0,
    },
]


def _gather_achievement_stats(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Collect all stats needed for achievement checking."""
    conn = get_connection(db_path)

    # Mastered mistake count
    mastered_mistakes = conn.execute(
        "SELECT COUNT(*) FROM mistakes WHERE student_id = ? AND consecutive_correct >= 2",
        [student_id],
    ).fetchone()[0]

    # Knowledge points with >= 80% mastery rate
    kp_rows = conn.execute(
        "SELECT knowledge_points, consecutive_correct FROM mistakes WHERE student_id = ?",
        [student_id],
    ).fetchall()
    kp_stats: Dict[str, Dict[str, int]] = {}
    for r in kp_rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "mastered": 0}
            kp_stats[kp]["total"] += 1
            if r["consecutive_correct"] >= 2:
                kp_stats[kp]["mastered"] += 1
    mastered_kp_count = sum(
        1 for s in kp_stats.values()
        if s["total"] > 0 and s["mastered"] / s["total"] >= 0.8
    )
    all_kps_mastered = len(kp_stats) > 0 and all(
        s["total"] > 0 and s["mastered"] / s["total"] >= 0.8
        for s in kp_stats.values()
    )

    # Check-in streak (consecutive days ending today)
    today = date.today()
    check_in_rows = conn.execute(
        "SELECT DISTINCT check_in_date FROM check_ins WHERE student_id = ? ORDER BY check_in_date DESC LIMIT 60",
        [student_id],
    ).fetchall()
    streak = 0
    for i, r in enumerate(check_in_rows):
        expected = (today - timedelta(days=i)).isoformat()
        if r["check_in_date"] == expected:
            streak += 1
        else:
            break

    # Max weekly check-ins (best week ever)
    max_weekly = 0
    if check_in_rows:
        week_counts: Dict[str, int] = {}
        for r in check_in_rows:
            d = date.fromisoformat(r["check_in_date"])
            week_start = (d - timedelta(days=d.weekday())).isoformat()
            week_counts[week_start] = week_counts.get(week_start, 0) + 1
        max_weekly = max(week_counts.values()) if week_counts else 0

    # Practice accuracy (recent 30)
    practice_rows = conn.execute(
        "SELECT pr.is_correct FROM practice_records pr "
        "JOIN mistakes m ON m.id = pr.mistake_id WHERE m.student_id = ? "
        "ORDER BY pr.created_at DESC LIMIT 30",
        [student_id],
    ).fetchall()
    total_practice = len(practice_rows)
    correct_practice = sum(1 for r in practice_rows if r["is_correct"])
    practice_accuracy = round(correct_practice / total_practice * 100, 1) if total_practice > 0 else 0

    # Score improvement
    score_rows = conn.execute(
        "SELECT score FROM score_history WHERE student_id = ? ORDER BY created_at ASC",
        [student_id],
    ).fetchall()
    score_improvement = 0
    if len(score_rows) >= 2:
        first_score = score_rows[0]["score"] or 0
        latest_score = score_rows[-1]["score"] or 0
        score_improvement = max(0, round(latest_score - first_score, 1))

    # Active weeks (weeks with any record)
    active_weeks = conn.execute(
        "SELECT COUNT(DISTINCT week_start) FROM weekly_records WHERE student_id = ?",
        [student_id],
    ).fetchone()[0]

    # Ebbinghaus graduates (review_stage >= 7)
    ebbinghaus_graduated = conn.execute(
        "SELECT COUNT(*) FROM mistakes WHERE student_id = ? AND review_stage >= 7 AND consecutive_correct >= 2",
        [student_id],
    ).fetchone()[0]

    conn.close()

    return {
        "mastered_mistakes": mastered_mistakes,
        "mastered_kp_count": mastered_kp_count,
        "all_kps_mastered": all_kps_mastered,
        "check_in_streak": streak,
        "max_weekly_checkins": max_weekly,
        "practice_accuracy": practice_accuracy,
        "practice_count_recent": total_practice,
        "score_improvement": score_improvement,
        "active_weeks": active_weeks,
        "ebbinghaus_graduated": ebbinghaus_graduated,
    }


def check_and_award_achievements(student_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Check all achievement conditions and award any newly earned ones.
    Returns list of newly awarded achievements."""
    stats = _gather_achievement_stats(student_id, db_path)
    conn = get_connection(db_path)

    # Get already-earned achievement keys
    existing = set(
        r[0] for r in conn.execute(
            "SELECT achievement_key FROM achievements WHERE student_id = ?",
            [student_id],
        ).fetchall()
    )

    newly_awarded = []
    now = _now_iso()

    for adef in ACHIEVEMENT_DEFS:
        base_key = adef["key"]
        current_value = adef["check"](stats)
        for suffix, threshold, label in adef["tiers"]:
            ach_key = f"{base_key}{suffix}"
            if ach_key in existing:
                continue
            if current_value >= threshold:
                try:
                    conn.execute(
                        "INSERT INTO achievements (student_id, achievement_key, title, description, icon, tier, earned_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [
                            student_id, ach_key,
                            adef["title"] + " " + label,
                            adef["description"].format(threshold=label),
                            adef["icon"],
                            adef["tiers"].index((suffix, threshold, label)) + 1,
                            now,
                        ],
                    )
                    conn.commit()
                    newly_awarded.append({
                        "achievement_key": ach_key,
                        "title": adef["title"] + " " + label,
                        "description": adef["description"].format(threshold=label),
                        "icon": adef["icon"],
                        "tier": adef["tiers"].index((suffix, threshold, label)) + 1,
                        "earned_at": now,
                    })
                    existing.add(ach_key)
                except sqlite3.IntegrityError:
                    pass  # Race condition, already exists

    conn.close()
    return newly_awarded


def get_student_achievements(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get all earned achievements and progress toward locked ones."""
    conn = get_connection(db_path)
    earned_rows = conn.execute(
        "SELECT * FROM achievements WHERE student_id = ? ORDER BY earned_at DESC",
        [student_id],
    ).fetchall()
    conn.close()

    earned = [dict(r) for r in earned_rows]
    earned_keys = {r["achievement_key"] for r in earned}

    # Build progress list: all achievements with locked/unlocked status
    stats = _gather_achievement_stats(student_id, db_path)
    all_achievements = []
    for adef in ACHIEVEMENT_DEFS:
        current_value = adef["check"](stats)
        for suffix, threshold, label in adef["tiers"]:
            ach_key = f"{adef['key']}{suffix}"
            is_earned = ach_key in earned_keys
            # Find the earned record if it exists
            earned_record = next((e for e in earned if e["achievement_key"] == ach_key), None)
            all_achievements.append({
                "achievement_key": ach_key,
                "title": adef["title"] + " " + label,
                "description": adef["description"].format(threshold=label),
                "icon": adef["icon"],
                "tier": adef["tiers"].index((suffix, threshold, label)) + 1,
                "threshold": threshold,
                "current": min(current_value, threshold),
                "progress_pct": round(min(current_value / max(threshold, 1), 1.0) * 100),
                "earned": is_earned,
                "earned_at": earned_record["earned_at"] if earned_record else None,
            })

    return {
        "earned": earned,
        "earned_count": len(earned),
        "total_count": len(all_achievements),
        "all": all_achievements,
    }


# ═══════════════════════════════════════════════════
# Learning Path Timeline — 学习路径时间轴
# ═══════════════════════════════════════════════════

def get_student_timeline(student_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Generate a chronological learning path timeline for a student.
    Returns a list of milestone dicts sorted by date ascending."""
    conn = get_connection(db_path)
    milestones = []

    # 1. 入学诊断 — first learning plan
    plan_row = conn.execute(
        "SELECT generated_at FROM learning_plans WHERE student_id = ? ORDER BY generated_at ASC LIMIT 1",
        [student_id],
    ).fetchone()
    if plan_row and plan_row["generated_at"]:
        milestones.append({
            "date": plan_row["generated_at"][:10],
            "icon": "🎓",
            "title": "入学诊断",
            "description": "AI 生成首份个性化学习方案，学习之旅正式启航",
            "type": "enrollment",
        })

    # 2. 首次攻克错题
    first_mastered = conn.execute(
        "SELECT created_at, question FROM mistakes WHERE student_id = ? AND consecutive_correct >= 2 ORDER BY last_reviewed_at ASC LIMIT 1",
        [student_id],
    ).fetchone()
    if first_mastered and first_mastered["created_at"]:
        q_preview = (first_mastered["question"] or "")[:30]
        milestones.append({
            "date": first_mastered["created_at"][:10],
            "icon": "✅",
            "title": "首次攻克错题",
            "description": f"「{q_preview}...」连续答对，移出错题本",
            "type": "first_mastery",
        })

    # 3. 首次分数进步
    score_rows = conn.execute(
        "SELECT created_at, score FROM score_history WHERE student_id = ? ORDER BY created_at ASC",
        [student_id],
    ).fetchall()
    if len(score_rows) >= 2:
        first_score = score_rows[0]["score"] or 0
        for r in score_rows[1:]:
            if (r["score"] or 0) > first_score:
                improvement = round((r["score"] or 0) - first_score, 1)
                milestones.append({
                    "date": r["created_at"][:10],
                    "icon": "📈",
                    "title": "首次进步",
                    "description": f"英语成绩从 {first_score} 提升到 {r['score']}（+{improvement}分）",
                    "type": "first_score_up",
                })
                break

    # 4 & 5. 连续打卡里程碑
    check_in_rows = conn.execute(
        "SELECT DISTINCT check_in_date FROM check_ins WHERE student_id = ? ORDER BY check_in_date ASC",
        [student_id],
    ).fetchall()
    if check_in_rows:
        # Find the first date when streak hit 3, 7, 14, 30
        targets = [3, 7, 14, 30]
        streak = 0
        prev_date = None
        hit_targets = set()
        for r in check_in_rows:
            d = date.fromisoformat(r["check_in_date"])
            if prev_date and (d - prev_date).days == 1:
                streak += 1
            else:
                streak = 1
            prev_date = d
            for t in targets:
                if streak >= t and t not in hit_targets:
                    hit_targets.add(t)
                    label = f"{t}天" if t <= 7 else f"{t//7}周" if t % 7 == 0 else f"{t}天"
                    milestones.append({
                        "date": d.isoformat(),
                        "icon": "🔥",
                        "title": f"连续打卡{label}",
                        "description": f"连续坚持 {t} 天，习惯正在养成",
                        "type": f"streak_{t}",
                    })

    # 6. 连续3周达标 (completion rate >= 80%)
    weekly_rows = conn.execute(
        "SELECT week_start, paper_submitted, exercises_completed, exercises_sent "
        "FROM weekly_records WHERE student_id = ? ORDER BY week_start ASC",
        [student_id],
    ).fetchall()
    consecutive_good = 0
    for wr in weekly_rows:
        sent = wr["exercises_sent"] or 0
        done = wr["exercises_completed"] or 0
        rate = done / max(sent, 1)
        if wr["paper_submitted"] and rate >= 0.8:
            consecutive_good += 1
        else:
            consecutive_good = 0
        if consecutive_good >= 3:
            milestones.append({
                "date": wr["week_start"],
                "icon": "🌟",
                "title": "连续达标",
                "description": "连续 3 周完成率 ≥ 80%，进入稳定上升通道",
                "type": "consistent_3w",
            })
            break

    # 7. 掌握过半知识点
    kp_rows = conn.execute(
        "SELECT knowledge_points, consecutive_correct, created_at FROM mistakes WHERE student_id = ? ORDER BY created_at ASC",
        [student_id],
    ).fetchall()
    kp_best: Dict[str, Dict[str, Any]] = {}
    for r in kp_rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            if kp not in kp_best:
                kp_best[kp] = {"mastered": False, "first_date": r["created_at"]}
            if r["consecutive_correct"] >= 2:
                kp_best[kp]["mastered"] = True
    total_kp = len(kp_best)
    if total_kp > 0:
        # Walk through time to find when mastery crossed 50%
        mastered_so_far = 0
        kp_mastered_at: Dict[str, str] = {}
        for r in kp_rows:
            for kp in json.loads(r["knowledge_points"] or "[]"):
                if kp not in kp_mastered_at and r["consecutive_correct"] >= 2:
                    kp_mastered_at[kp] = r["created_at"]
                    mastered_so_far += 1
                    if mastered_so_far >= total_kp / 2 and not any(
                        m["type"] == "half_mastered" for m in milestones
                    ):
                        milestones.append({
                            "date": r["created_at"][:10],
                            "icon": "🏆",
                            "title": "掌握过半",
                            "description": f"已掌握 {total_kp} 个知识点中的过半（{mastered_so_far}个），稳步推进",
                            "type": "half_mastered",
                        })
        # All mastered?
        if mastered_so_far >= total_kp:
            milestones.append({
                "date": max(kp_mastered_at.values())[:10] if kp_mastered_at else "",
                "icon": "👑",
                "title": "全科掌握",
                "description": f"全部 {total_kp} 个知识点已掌握",
                "type": "all_mastered",
            })

    # 8. 达成目标分数
    student = conn.execute(
        "SELECT target_score FROM students WHERE id = ?", [student_id]
    ).fetchone()
    target = student["target_score"] if student else None
    if target and score_rows:
        for r in score_rows:
            if (r["score"] or 0) >= target:
                milestones.append({
                    "date": r["created_at"][:10],
                    "icon": "🎯",
                    "title": "达成目标",
                    "description": f"英语成绩达到 {r['score']} 分，达成目标 {target} 分！",
                    "type": "target_reached",
                })
                break

    # 9. 艾宾浩斯毕业
    first_ebb_graduate = conn.execute(
        "SELECT created_at, question FROM mistakes WHERE student_id = ? AND review_stage >= 7 AND consecutive_correct >= 2 ORDER BY last_reviewed_at ASC LIMIT 1",
        [student_id],
    ).fetchone()
    if first_ebb_graduate:
        q_preview = (first_ebb_graduate["question"] or "")[:30]
        milestones.append({
            "date": first_ebb_graduate["created_at"][:10],
            "icon": "🧠",
            "title": "记忆大师",
            "description": f"首道错题完成全部 8 阶艾宾浩斯复习：{q_preview}...",
            "type": "ebbinghaus_grad",
        })

    # 10. 错题攻克 10 道
    mastered_count = conn.execute(
        "SELECT COUNT(*) FROM mistakes WHERE student_id = ? AND consecutive_correct >= 2",
        [student_id],
    ).fetchone()[0]
    if mastered_count >= 10:
        # Find the date of the 10th mastered mistake
        tenth = conn.execute(
            "SELECT last_reviewed_at FROM mistakes WHERE student_id = ? AND consecutive_correct >= 2 ORDER BY last_reviewed_at ASC LIMIT 1 OFFSET 9",
            [student_id],
        ).fetchone()
        if tenth:
            milestones.append({
                "date": tenth["last_reviewed_at"][:10],
                "icon": "⚔️",
                "title": "错题克星·10道",
                "description": f"累计攻克 10 道错题，稳步消灭薄弱点",
                "type": "mistake_10",
            })

    # 11. 练习 50 次
    practice_count = conn.execute(
        "SELECT COUNT(*) FROM practice_records pr JOIN mistakes m ON m.id = pr.mistake_id WHERE m.student_id = ?",
        [student_id],
    ).fetchone()[0]
    if practice_count >= 50:
        fiftieth = conn.execute(
            "SELECT pr.created_at FROM practice_records pr JOIN mistakes m ON m.id = pr.mistake_id WHERE m.student_id = ? ORDER BY pr.created_at ASC LIMIT 1 OFFSET 49",
            [student_id],
        ).fetchone()
        if fiftieth:
            milestones.append({
                "date": fiftieth["created_at"][:10],
                "icon": "💪",
                "title": "练习达人",
                "description": "累计完成 50 次练习，量变引起质变",
                "type": "practice_50",
            })

    # 12. 首次满分
    if score_rows:
        for r in score_rows:
            if (r["score"] or 0) >= 100:
                milestones.append({
                    "date": r["created_at"][:10],
                    "icon": "💯",
                    "title": "满分突破",
                    "description": "首次取得满分成绩！",
                    "type": "perfect_score",
                })
                break

    conn.close()

    # Sort by date
    milestones.sort(key=lambda m: m["date"])
    return milestones


# ═══════════════════════════════════════════════════
# Metacognitive Review — 元认知复盘表
# ═══════════════════════════════════════════════════

def get_week_start(d: date = None) -> str:
    """Get ISO week start (Monday) for a given date."""
    d = d or date.today()
    return (d - timedelta(days=d.weekday())).isoformat()


def get_or_create_metacognitive_review(student_id: int, week_start: str = None,
                                        db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get existing review for a week, or create a new one from the AI template."""
    if week_start is None:
        week_start = get_week_start()
    conn = get_connection(db_path)

    # Check existing
    row = conn.execute(
        "SELECT * FROM metacognitive_reviews WHERE student_id = ? AND week_start = ?",
        [student_id, week_start],
    ).fetchone()

    if row:
        d = dict(row)
        for field in ["template_questions", "child_answers", "parent_answers"]:
            try:
                d[field] = json.loads(d.get(field) or "{}")
            except Exception:
                d[field] = {}
        conn.close()
        return d

    # Create new from AI template in learning_plan
    plan = get_learning_plan(student_id, db_path=db_path)
    plan_data = plan.get("plan_data", {}) if plan else {}
    if isinstance(plan_data, str):
        try:
            plan_data = json.loads(plan_data)
        except Exception:
            plan_data = {}
    meta_review = plan_data.get("metacognitive_review", {})
    if isinstance(meta_review, str):
        try:
            meta_review = json.loads(meta_review)
        except Exception:
            meta_review = {}

    template = {
        "child_reflection": meta_review.get("child_reflection", [
            "这周学习中最有成就感的一件事是什么？",
            "哪个知识点让你觉得最难？你是怎么应对的？",
            "下周你想在哪方面做得更好？",
        ]),
        "parent_observation": meta_review.get("parent_observation", [
            "这周孩子在学习上有什么让你惊喜的表现？",
            "你观察到孩子在学习习惯上有什么变化？",
        ]),
    }

    try:
        conn.execute(
            "INSERT INTO metacognitive_reviews (student_id, week_start, template_questions, status) VALUES (?, ?, ?, 'draft')",
            [student_id, week_start, json.dumps(template, ensure_ascii=False)],
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Race condition

    conn.close()
    return {
        "student_id": student_id,
        "week_start": week_start,
        "template_questions": template,
        "child_answers": {},
        "parent_answers": {},
        "child_mood": None,
        "parent_mood": None,
        "child_note": None,
        "parent_note": None,
        "status": "draft",
    }


def submit_metacognitive_review(student_id: int, week_start: str,
                                 child_answers: Dict = None,
                                 parent_answers: Dict = None,
                                 child_mood: int = None,
                                 parent_mood: int = None,
                                 child_note: str = None,
                                 parent_note: str = None,
                                 db_path: str = DB_PATH) -> bool:
    """Save a metacognitive review (draft or submit)."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT id FROM metacognitive_reviews WHERE student_id = ? AND week_start = ?",
        [student_id, week_start],
    ).fetchone()
    if not row:
        conn.close()
        # Auto-create
        get_or_create_metacognitive_review(student_id, week_start, db_path)
        conn = get_connection(db_path)
        row = conn.execute(
            "SELECT id FROM metacognitive_reviews WHERE student_id = ? AND week_start = ?",
            [student_id, week_start],
        ).fetchone()
        if not row:
            conn.close()
            return False

    conn.execute(
        """UPDATE metacognitive_reviews SET
            child_answers = ?, parent_answers = ?,
            child_mood = ?, parent_mood = ?,
            child_note = ?, parent_note = ?,
            status = 'submitted', submitted_at = ?
        WHERE id = ?""",
        [
            json.dumps(child_answers or {}, ensure_ascii=False),
            json.dumps(parent_answers or {}, ensure_ascii=False),
            child_mood, parent_mood,
            child_note, parent_note,
            _now_iso(), row["id"],
        ],
    )
    conn.commit()
    conn.close()
    return True


def get_metacognitive_reviews(student_id: int, limit: int = 10,
                               db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get all metacognitive reviews for a student, newest first."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM metacognitive_reviews WHERE student_id = ? ORDER BY week_start DESC LIMIT ?",
        [student_id, limit],
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        for field in ["template_questions", "child_answers", "parent_answers"]:
            try:
                d[field] = json.loads(d.get(field) or "{}")
            except Exception:
                d[field] = {}
        results.append(d)
    return results


def get_class_learning_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get class-wide learning stats."""
    conn = get_connection(db_path)

    # Active students count
    total_students = conn.execute(
        "SELECT COUNT(*) FROM students WHERE status='active'"
    ).fetchone()[0]

    # Average current score
    avg_score = conn.execute("""
        SELECT AVG(english_score) FROM students
        WHERE status='active' AND english_score IS NOT NULL
    """).fetchone()[0]

    # Students with target score
    target_rows = conn.execute("""
        SELECT name, english_score, target_score
        FROM students
        WHERE status='active' AND english_score IS NOT NULL AND target_score IS NOT NULL
    """).fetchall()

    # Class weak knowledge points
    kp_rows = conn.execute("""
        SELECT knowledge_points, consecutive_correct
        FROM mistakes m
        JOIN students s ON s.id = m.student_id
        WHERE s.status = 'active'
    """).fetchall()

    kp_stats: Dict[str, Dict[str, int]] = {}
    for r in kp_rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "mastered": 0}
            kp_stats[kp]["total"] += 1
            if r["consecutive_correct"] >= 2:
                kp_stats[kp]["mastered"] += 1

    weak_kp = sorted(
        [{"knowledge_point": kp, **s,
          "mastery_rate": round(s["mastered"] / s["total"] * 100, 1) if s["total"] > 0 else 0}
         for kp, s in kp_stats.items()],
        key=lambda x: (x["mastery_rate"], -x["total"])
    )[:10]

    # Recent score trends (average per week)
    score_trend_rows = conn.execute("""
        SELECT week_start, AVG(score) as avg_score, COUNT(*) as count
        FROM score_history
        WHERE week_start IS NOT NULL
        GROUP BY week_start
        ORDER BY week_start ASC
        LIMIT 12
    """).fetchall()

    conn.close()

    # Progress toward target
    progress_list = []
    for r in target_rows:
        gap = r["target_score"] - r["english_score"]
        progress_list.append({
            "name": r["name"],
            "current": r["english_score"],
            "target": r["target_score"],
            "gap": round(gap, 1),
        })
    progress_list.sort(key=lambda x: x["gap"], reverse=True)

    return {
        "total_students": total_students,
        "average_score": round(avg_score, 1) if avg_score else None,
        "weak_knowledge_points": weak_kp,
        "score_trend": [dict(r) for r in score_trend_rows],
        "students_progress": progress_list,
    }


# ═══════════════════════════════════════════════════
# Student Learning Loop (Check-ins + Mistake Book)
# ═══════════════════════════════════════════════════

def record_check_in(student_id: int, check_in_date: str = None, content: str = "",
                    duration_minutes: int = 0, source: str = "manual",
                    db_path: str = DB_PATH) -> int:
    """Record a student check-in. Returns check_in id."""
    conn = get_connection(db_path)
    date_str = check_in_date or date.today().isoformat()
    cur = conn.execute("""
        INSERT OR REPLACE INTO check_ins (student_id, check_in_date, content, duration_minutes, source)
        VALUES (?, ?, ?, ?, ?)
    """, [student_id, date_str, content, duration_minutes, source])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_check_ins(student_id: int, limit: int = 30, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get recent check-ins for a student."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM check_ins
        WHERE student_id = ?
        ORDER BY check_in_date DESC
        LIMIT ?
    """, [student_id, limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_check_in_calendar(student_id: int, days: int = 30, db_path: str = DB_PATH) -> List[str]:
    """Get list of dates with check-ins in last N days."""
    conn = get_connection(db_path)
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT DISTINCT check_in_date FROM check_ins
        WHERE student_id = ? AND check_in_date >= ?
        ORDER BY check_in_date DESC
    """, [student_id, since]).fetchall()
    conn.close()
    return [r["check_in_date"] for r in rows]


def get_weekly_completion_rate(student_id: int, week_start: str,
                               db_path: str = DB_PATH) -> float:
    """
    Calculate weekly completion rate based on check-ins, weekly exercise status,
    and parent task completion. Returns a float between 0 and 1.
    """
    from datetime import timedelta as _timedelta
    conn = get_connection(db_path)

    # Count check-ins in the week
    week_start_dt = date.fromisoformat(week_start)
    week_end_dt = week_start_dt + _timedelta(days=6)
    week_end = week_end_dt.isoformat()

    check_in_rows = conn.execute("""
        SELECT COUNT(DISTINCT check_in_date) AS cnt FROM check_ins
        WHERE student_id = ? AND check_in_date >= ? AND check_in_date <= ?
    """, [student_id, week_start, week_end]).fetchall()
    check_in_days = check_in_rows[0]["cnt"] if check_in_rows else 0

    # Weekly exercise completion status
    weekly_row = conn.execute("""
        SELECT exercises_completed FROM weekly_records
        WHERE student_id = ? AND week_start = ?
    """, [student_id, week_start]).fetchone()
    exercise_completed = bool(weekly_row and weekly_row["exercises_completed"])

    # Parent task completion rate
    parent_task_rate = 0.0
    profile = get_student_profile(student_id, db_path=db_path)
    if profile:
        ptp = profile.get("parent_task_progress", {})
        if isinstance(ptp, dict) and ptp:
            total_tasks = len(ptp)
            completed_tasks = sum(1 for v in ptp.values() if v)
            parent_task_rate = completed_tasks / total_tasks if total_tasks > 0 else 0.0

    conn.close()

    # Base rate from check-ins (expect at least 4 days out of 7)
    check_in_rate = min(1.0, check_in_days / 4.0) if check_in_days > 0 else 0.0
    # If weekly exercise completed, ensure at least 70%
    if exercise_completed:
        check_in_rate = max(check_in_rate, 0.7)

    # Blend: 60% student activity + 40% parent engagement
    blended_rate = check_in_rate * 0.6 + parent_task_rate * 0.4
    return round(min(1.0, max(0.0, blended_rate)), 2)


def get_student_mistake_book(student_id: int, mastered: bool = False,
                             db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get mistake book for a student. By default returns unmastered mistakes."""
    conn = get_connection(db_path)
    query = "SELECT * FROM mistakes WHERE student_id = ?"
    params = [student_id]
    if not mastered:
        query += " AND consecutive_correct < 2"
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
        d["is_mastered"] = d.get("consecutive_correct", 0) >= 2
        results.append(d)
    return results


def mark_mistake_mastered(mistake_id: int, db_path: str = DB_PATH) -> bool:
    """Mark a mistake as mastered by setting consecutive_correct to 2."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM mistakes WHERE id = ?", [mistake_id]).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("""
        UPDATE mistakes SET consecutive_correct = 2, mastery_level = 100, last_reviewed_at = ?
        WHERE id = ?
    """, [_now_iso(), mistake_id])
    conn.commit()
    conn.close()
    return True


def get_student_public_summary(code: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Get public summary for student page by access_code.

    字段白名单：公开页严禁返回整行 students（曾 SELECT * 泄漏
    phone/password_hash/家长微信等，安全审查 P0）。
    """
    conn = get_connection(db_path)
    student = conn.execute(
        "SELECT id, name, grade, school_type, english_score, target_score, "
        "gender, textbook_version, semester, status, created_at "
        "FROM students WHERE access_code = ? AND status = 'active'", [code]
    ).fetchone()
    if not student:
        conn.close()
        return None

    student_id = student["id"]

    # Mistakes
    mistakes = get_student_mistake_book(student_id, mastered=False, db_path=db_path)
    mastered_mistakes = get_student_mistake_book(student_id, mastered=True, db_path=db_path)

    # Scores
    scores = get_score_history(student_id, limit=12, db_path=db_path)

    # Check-ins
    check_ins = get_check_in_calendar(student_id, days=800, db_path=db_path)

    # Weekly activity
    weekly_rows = conn.execute("""
        SELECT week_start, paper_submitted, exercises_sent, exercises_graded, report_sent
        FROM weekly_records
        WHERE student_id = ?
        ORDER BY week_start DESC
        LIMIT 8
    """, [student_id]).fetchall()

    # Learning plan
    plan = get_learning_plan(student_id, db_path=db_path)

    # Weak points
    weak_points = get_weak_knowledge_points(student_id, top_n=8, db_path=db_path)

    # Spaced repetition review stats
    review_stats = get_review_stats(student_id, db_path=db_path)
    due_reviews = get_due_reviews(student_id, db_path=db_path)

    # Student profile (for learning style radar chart)
    profile = get_student_profile(student_id, db_path=db_path)
    learning_style = None
    if profile:
        ls_detail = profile.get("learning_style_detail", {})
        if isinstance(ls_detail, dict) and any(
            ls_detail.get(k) for k in ["visual", "auditory", "kinesthetic", "read_write"]
        ):
            learning_style = ls_detail

    conn.close()

    return {
        "student": dict(student),
        "mistakes": mistakes,
        "mistakes_count": len(mistakes),
        "mastered_count": len(mastered_mistakes),
        "due_reviews": due_reviews,
        "due_review_count": len(due_reviews),
        "review_stats": review_stats,
        "learning_style": learning_style,
        "scores": scores,
        "check_ins": check_ins,
        "weekly_activity": [dict(r) for r in weekly_rows],
        "learning_plan": plan,
        "weak_points": weak_points,
    }


# ═══════════════════════════════════════════════════
# Referral / Viral Growth
# ═══════════════════════════════════════════════════

def _generate_referral_code(conn: sqlite3.Connection) -> str:
    """Generate a unique 8-character referral code."""
    import random
    import string
    for _ in range(100):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        existing = conn.execute("SELECT id FROM referrals WHERE invite_code = ?", [code]).fetchone()
        if not existing:
            return code
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


def get_or_create_referral_code(student_id: int, db_path: str = DB_PATH) -> str:
    """Get or create an invite code for a student. Returns invite_code."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT invite_code FROM referrals WHERE referrer_student_id = ? LIMIT 1",
        [student_id]
    ).fetchone()
    if row:
        conn.close()
        return row["invite_code"]

    code = _generate_referral_code(conn)
    conn.execute("""
        INSERT INTO referrals (referrer_student_id, invite_code, status)
        VALUES (?, ?, 'active')
    """, [student_id, code])
    conn.commit()
    conn.close()
    return code


def record_referral(invite_code: str, referred_student_id: int,
                    db_path: str = DB_PATH) -> bool:
    """Record that a new student was referred by invite_code."""
    conn = get_connection(db_path)
    ref = conn.execute(
        "SELECT * FROM referrals WHERE invite_code = ?",
        [invite_code]
    ).fetchone()
    if not ref:
        conn.close()
        return False
    if ref["referrer_student_id"] == referred_student_id:
        conn.close()
        return False  # cannot refer self
    if ref["referred_student_id"] is not None:
        # Code already used; create a new referral record for the same referrer
        pass

    reward_weeks = int(get_setting("referral_reward_weeks", db_path) or "1")
    if ref["referred_student_id"] is None:
        conn.execute("""
            UPDATE referrals
            SET referred_student_id = ?, reward_weeks = ?, status = 'converted'
            WHERE id = ?
        """, [referred_student_id, reward_weeks, ref["id"]])
    else:
        conn.execute("""
            INSERT INTO referrals (referrer_student_id, referred_student_id, invite_code, reward_weeks, status)
            VALUES (?, ?, ?, ?, 'converted')
        """, [ref["referrer_student_id"], referred_student_id, invite_code, reward_weeks])
    conn.commit()
    conn.close()
    return True


def get_student_referrals(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get referral info for a student."""
    conn = get_connection(db_path)
    invite_code = conn.execute(
        "SELECT invite_code FROM referrals WHERE referrer_student_id = ? LIMIT 1",
        [student_id]
    ).fetchone()

    rows = conn.execute("""
        SELECT r.*, s.name as referred_name
        FROM referrals r
        LEFT JOIN students s ON s.id = r.referred_student_id
        WHERE r.referrer_student_id = ? AND r.referred_student_id IS NOT NULL
        ORDER BY r.created_at DESC
    """, [student_id]).fetchall()

    conn.close()
    return {
        "invite_code": invite_code["invite_code"] if invite_code else None,
        "referrals": [dict(r) for r in rows],
        "converted_count": len(rows),
        "total_reward_weeks": sum(r["reward_weeks"] or 0 for r in rows),
    }


def get_referral_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get overall referral stats."""
    conn = get_connection(db_path)
    total_invites = conn.execute("SELECT COUNT(DISTINCT invite_code) FROM referrals").fetchone()[0]
    total_converted = conn.execute(
        "SELECT COUNT(*) FROM referrals WHERE referred_student_id IS NOT NULL"
    ).fetchone()[0]
    total_reward_weeks = conn.execute(
        "SELECT COALESCE(SUM(reward_weeks), 0) FROM referrals WHERE referred_student_id IS NOT NULL"
    ).fetchone()[0]

    top_referrers = conn.execute("""
        SELECT s.name, COUNT(*) as count, SUM(r.reward_weeks) as weeks
        FROM referrals r
        JOIN students s ON s.id = r.referrer_student_id
        WHERE r.referred_student_id IS NOT NULL
        GROUP BY r.referrer_student_id
        ORDER BY count DESC
        LIMIT 10
    """).fetchall()

    conn.close()
    return {
        "total_invites": total_invites,
        "total_converted": total_converted,
        "conversion_rate": round(total_converted / max(total_invites, 1) * 100, 1),
        "total_reward_weeks": total_reward_weeks,
        "top_referrers": [dict(r) for r in top_referrers],
    }


def lookup_referrer_by_code(invite_code: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Find the referrer student by invite code."""
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT s.* FROM referrals r
        JOIN students s ON s.id = r.referrer_student_id
        WHERE r.invite_code = ?
        LIMIT 1
    """, [invite_code]).fetchone()
    conn.close()
    return dict(row) if row else None


# ═══════════════════════════════════════════════════
# Compliance & Operations
# ═══════════════════════════════════════════════════

def record_parent_consent(student_id: int, consented_by: str, contact: str = "",
                            ip_address: str = "", notes: str = "",
                            consent_version: str = "v1",
                            db_path: str = DB_PATH) -> int:
    """Record parent consent for student data processing.

    consent_version：同意书版本号，政策变更后新记录携带新版本，
    便于审计「该学生同意的是哪一版条款」。
    """
    conn = get_connection(db_path)
    try:
        cur = conn.execute("""
            INSERT INTO parent_consents
                (student_id, consented_by, contact, ip_address, notes, consent_version)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [student_id, consented_by, contact, ip_address, notes, consent_version])
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def has_parent_consent(student_id: int, db_path: str = DB_PATH) -> bool:
    """Check if parent consent exists for a student（已撤回的同意不算数）。"""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM parent_consents "
            "WHERE student_id = ? AND withdrawn_at IS NULL LIMIT 1",
            [student_id]
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_students_without_consent(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get active students without parent consent."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT s.* FROM students s
        WHERE s.status = 'active'
          AND NOT EXISTS (
              SELECT 1 FROM parent_consents pc WHERE pc.student_id = s.id
          )
        ORDER BY s.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def request_data_deletion(student_id: int, requested_by: str, reason: str = "",
                          db_path: str = DB_PATH) -> int:
    """Create a data deletion request."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO deletion_requests (student_id, requested_by, reason)
        VALUES (?, ?, ?)
    """, [student_id, requested_by, reason])
    conn.commit()
    conn.close()
    return cur.lastrowid


def process_data_deletion(request_id: int, db_path: str = DB_PATH) -> bool:
    """处理删除请求：硬删全部个人数据（PIPL），仅保留两类记录。

    保留：
    - payments：金额/日期/套餐留档（财务/税务要求），经匿名学生存根关联
    - deletion_requests：本行标记 completed 作审计轨迹
    其余从属数据（错题/任务/文件/画像/订阅等）连同磁盘上传目录一并删除；
    students 行保留无 PII 的匿名存根（status='deleted'）供对账外键不悬空。
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT student_id FROM deletion_requests WHERE id = ?", [request_id]
        ).fetchone()
        if not row:
            return False
        student_id = row["student_id"]

        # 匿名化前先取手机号（sms_codes 按手机号关联，学生行稍后清空 PII）
        stu = conn.execute(
            "SELECT phone, parent_phone FROM students WHERE id = ?",
            [student_id]).fetchone()
        phones = {stu["phone"], stu["parent_phone"]} - {None, ""} if stu else set()

        # 题库题保留（可跨学生复用），仅切断对已删错题的引用
        conn.execute("""
            UPDATE questions SET source_mistake_id = NULL
            WHERE source_mistake_id IN (SELECT id FROM mistakes WHERE student_id = ?)
        """, [student_id])
        # 练习记录挂在错题下，先删
        conn.execute("""
            DELETE FROM practice_records WHERE mistake_id IN (
                SELECT id FROM mistakes WHERE student_id = ?)
        """, [student_id])
        # 任务从属表键在 task_id，先于 ai_tasks 删除（子查询依赖其行存在）
        conn.execute("""
            DELETE FROM llm_usage_log WHERE task_id IN (
                SELECT id FROM ai_tasks WHERE student_id = ?)
        """, [student_id])
        conn.execute("""
            DELETE FROM aigc_safety_checks WHERE task_id IN (
                SELECT id FROM ai_tasks WHERE student_id = ?)
        """, [student_id])
        # 其余按 FK 依赖顺序硬删（键均为 student_id）
        for table in (
            "mistakes", "practice_sessions",
            "ai_corrections", "ai_tasks",
            "files", "learning_plans", "plan_updates", "weekly_records",
            "score_history", "check_ins", "achievements",
            "metacognitive_reviews", "parent_consents",
            "subscriptions", "student_profiles",
            "cause_profiles", "cause_profile_history",
        ):
            conn.execute(f"DELETE FROM {table} WHERE student_id = ?", [student_id])
        # referrals 键为 referrer/referred 双向；sms_codes 按手机号关联
        conn.execute(
            "DELETE FROM referrals WHERE referrer_student_id = ? OR referred_student_id = ?",
            [student_id, student_id])
        for ph in phones:
            conn.execute("DELETE FROM sms_codes WHERE phone = ?", [ph])
        # 审计日志无 student_id 列：按 actor/target 关联清除含该学生的行
        conn.execute(
            "DELETE FROM audit_logs WHERE actor_id = ? OR target_id = ?",
            [str(student_id), str(student_id)])

        # 学生行 → 无 PII 匿名存根（保留 id 供 payments 外键与对账）
        conn.execute("""
            UPDATE students SET
                name = '已注销学生', grade = '', school_type = '',
                english_score = NULL, target_score = NULL,
                parent_name = NULL, parent_wechat = NULL, parent_phone = NULL,
                notes = NULL, phone = NULL, password_hash = NULL,
                gender = NULL, textbook_version = NULL, semester = NULL,
                school_id = NULL, class_id = NULL,
                status = 'deleted', access_code = NULL, parent_access_code = NULL
            WHERE id = ?
        """, [student_id])

        conn.execute(
            "UPDATE deletion_requests SET status = 'completed', processed_at = ? WHERE id = ?",
            [_now_iso(), request_id],
        )
        conn.commit()
    finally:
        conn.close()

    # 磁盘上传目录在 DB 提交后删除（尽力而为，失败不回滚）。
    # 与 web.shared.UPLOAD_DIR 同源：项目根/uploads（按 db.py 自身位置定位，
    # 不依赖 db_path —— 测试库在临时目录时路径仍指向真实 uploads）。
    upload_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "uploads", str(student_id))
    shutil.rmtree(upload_dir, ignore_errors=True)
    return True


def withdraw_parent_consent(student_id: int, withdrawn_by: str, reason: str = "",
                            db_path: str = DB_PATH) -> bool:
    """撤回监护人同意：所有有效同意记录标记 withdrawn_at（保留历史轨迹）。"""
    conn = get_connection(db_path)
    try:
        cur = conn.execute("""
            UPDATE parent_consents SET withdrawn_at = ?
            WHERE student_id = ? AND withdrawn_at IS NULL
        """, [_now_iso(), student_id])
        if reason:
            conn.execute("""
                UPDATE parent_consents SET notes = COALESCE(notes, '') || ?
                WHERE student_id = ? AND withdrawn_at IS NOT NULL
            """, [f"\n[撤回] {withdrawn_by}: {reason}", student_id])
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_pending_deletion_requests(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get pending data deletion requests."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT dr.*, s.name as student_name
        FROM deletion_requests dr
        JOIN students s ON s.id = dr.student_id
        WHERE dr.status = 'pending'
        ORDER BY dr.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_safety_check(task_id: int, content_type: str,
                        content_snapshot: str = "",
                        db_path: str = DB_PATH) -> int:
    """Create an AIGC safety check record."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO aigc_safety_checks (task_id, content_type, content_snapshot)
        VALUES (?, ?, ?)
    """, [task_id, content_type, content_snapshot])
    conn.commit()
    conn.close()
    return cur.lastrowid


def review_safety_check(check_id: int, safety_status: str, issue_flags: List[str],
                        reviewed_by: str, db_path: str = DB_PATH) -> bool:
    """Review a safety check record."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT id FROM aigc_safety_checks WHERE id = ?", [check_id]
    ).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("""
        UPDATE aigc_safety_checks
        SET safety_status = ?, issue_flags = ?, reviewed_by = ?, reviewed_at = ?
        WHERE id = ?
    """, [safety_status, json.dumps(issue_flags, ensure_ascii=False),
          reviewed_by, _now_iso(), check_id])
    conn.commit()
    conn.close()
    return True


def get_pending_safety_checks(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get pending AIGC safety checks."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT sc.*, s.name as student_name, t.task_type
        FROM aigc_safety_checks sc
        JOIN ai_tasks t ON t.id = sc.task_id
        JOIN students s ON s.id = t.student_id
        WHERE sc.safety_status = 'pending'
        ORDER BY sc.created_at DESC
        LIMIT 50
    """).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["issue_flags"] = json.loads(d.get("issue_flags", "[]"))
        results.append(d)
    return results


def get_safety_check_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get AIGC safety check statistics."""
    conn = get_connection(db_path)
    total = conn.execute("SELECT COUNT(*) FROM aigc_safety_checks").fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM aigc_safety_checks WHERE safety_status = 'pending'"
    ).fetchone()[0]
    flagged = conn.execute(
        "SELECT COUNT(*) FROM aigc_safety_checks WHERE safety_status = 'flagged'"
    ).fetchone()[0]
    clean = conn.execute(
        "SELECT COUNT(*) FROM aigc_safety_checks WHERE safety_status = 'clean'"
    ).fetchone()[0]
    conn.close()
    return {
        "total_checks": total,
        "pending": pending,
        "flagged": flagged,
        "clean": clean,
    }


# ═══════════════════════════════════════════════════
# AI Correction Operations
# ═══════════════════════════════════════════════════

def create_correction(
    task_id: int,
    student_id: int,
    content_type: str,
    target_field: str,
    corrected_value: Any,
    target_id: int = None,
    original_value: Any = None,
    reason: str = "",
    reviewed_by: str = "",
    apply: bool = True,
    db_path: str = DB_PATH,
) -> int:
    """Create an AI correction record and optionally apply it to the target table.

    Supported content_type / target_field combinations:
      - mistake: question, correct_answer, explanation, knowledge_points, difficulty, question_type
      - grading: is_correct, feedback
      - question: question_text, correct_answer, explanation, knowledge_points, difficulty, question_type
    """
    # Normalize values for storage
    if isinstance(corrected_value, (list, dict)):
        corrected_value = json.dumps(corrected_value, ensure_ascii=False)
    if original_value is not None and isinstance(original_value, (list, dict)):
        original_value = json.dumps(original_value, ensure_ascii=False)

    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO ai_corrections
            (task_id, student_id, content_type, target_id, target_field,
             original_value, corrected_value, reason, reviewed_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        task_id, student_id, content_type, target_id, target_field,
        original_value, corrected_value, reason, reviewed_by,
    ])
    correction_id = cur.lastrowid
    conn.commit()
    conn.close()

    if apply:
        _apply_correction_to_target(
            correction_id=correction_id,
            content_type=content_type,
            target_id=target_id,
            target_field=target_field,
            corrected_value=corrected_value,
            db_path=db_path,
        )
        record_feedback_pattern(
            content_type=content_type,
            target_field=target_field,
            corrected_value=corrected_value,
            target_id=target_id,
            db_path=db_path,
        )
    return correction_id


def _apply_correction_to_target(
    correction_id: int,
    content_type: str,
    target_id: int,
    target_field: str,
    corrected_value: Any,
    db_path: str = DB_PATH,
) -> bool:
    """Apply a correction to its target record."""
    if not target_id:
        return False

    conn = get_connection(db_path)
    applied = False
    try:
        if content_type == "mistake":
            row = conn.execute(
                "SELECT * FROM mistakes WHERE id = ?", [target_id]
            ).fetchone()
            if row:
                updates = _build_correction_updates(
                    target_field=target_field,
                    corrected_value=corrected_value,
                    current_value=row[target_field] if target_field in row.keys() else None,
                )
                if updates:
                    set_clause = ", ".join(f"{k} = ?" for k in updates)
                    conn.execute(
                        f"UPDATE mistakes SET {set_clause}, last_reviewed_at = ? WHERE id = ?",
                        list(updates.values()) + [_now_iso(), target_id],
                    )
                    applied = True

        elif content_type == "question":
            # Map correction field names to question table column names
            field_map = {
                "question": "question_text",
                "question_text": "question_text",
                "correct_answer": "correct_answer",
                "explanation": "explanation",
                "knowledge_points": "knowledge_points",
                "difficulty": "difficulty",
                "question_type": "question_type",
            }
            col = field_map.get(target_field)
            if col:
                updates = _build_correction_updates(
                    target_field=target_field,
                    corrected_value=corrected_value,
                )
                if updates:
                    set_clause = ", ".join(f"{col} = ?" for col in updates.values())
                    # Actually build updates with mapped column names
                    mapped_updates = {}
                    for k, v in updates.items():
                        mapped_updates[field_map.get(k, k)] = v
                    set_clause = ", ".join(f"{k} = ?" for k in mapped_updates)
                    conn.execute(
                        f"UPDATE questions SET {set_clause} WHERE id = ?",
                        list(mapped_updates.values()) + [target_id],
                    )
                    applied = True

        elif content_type == "grading":
            pr = conn.execute(
                "SELECT * FROM practice_records WHERE id = ?", [target_id]
            ).fetchone()
            if pr:
                updates = {}
                if target_field == "is_correct":
                    updates["is_correct"] = 1 if str(corrected_value).lower() in ("1", "true", "yes", "对") else 0
                elif target_field == "feedback":
                    updates["feedback"] = corrected_value
                if updates:
                    set_clause = ", ".join(f"{k} = ?" for k in updates)
                    conn.execute(
                        f"UPDATE practice_records SET {set_clause} WHERE id = ?",
                        list(updates.values()) + [target_id],
                    )
                    # Recalculate mistake mastery based on full practice history
                    _recalculate_mistake_stats(pr["mistake_id"], conn)
                    applied = True

        if applied:
            conn.execute(
                "UPDATE ai_corrections SET status = 'applied' WHERE id = ?",
                [correction_id],
            )
        conn.commit()
    finally:
        conn.close()
    return applied


def _build_correction_updates(target_field: str, corrected_value: Any,
                              current_value: Any = None) -> Dict[str, Any]:
    """Convert correction field/value into a dict of column updates."""
    updates = {}
    if target_field in ("question", "question_text"):
        updates["question"] = corrected_value
    elif target_field == "correct_answer":
        updates["correct_answer"] = corrected_value
    elif target_field == "explanation":
        updates["explanation"] = corrected_value
    elif target_field == "knowledge_points":
        if isinstance(corrected_value, str):
            try:
                corrected_value = json.loads(corrected_value)
            except Exception:
                corrected_value = [v.strip() for v in corrected_value.split(",") if v.strip()]
        updates["knowledge_points"] = json.dumps(corrected_value or [], ensure_ascii=False)
    elif target_field == "difficulty":
        try:
            updates["difficulty"] = int(corrected_value)
        except Exception:
            updates["difficulty"] = current_value if current_value is not None else 2
    elif target_field == "question_type":
        updates["question_type"] = corrected_value
    return updates


def _recalculate_mistake_stats(mistake_id: int, conn: sqlite3.Connection) -> None:
    """Recalculate review_count, consecutive_correct and mastery_level
    for a mistake from its practice history.
    """
    rows = conn.execute(
        "SELECT is_correct FROM practice_records WHERE mistake_id = ? ORDER BY created_at ASC",
        [mistake_id],
    ).fetchall()
    review_count = len(rows)
    consecutive_correct = 0
    for r in rows:
        if r["is_correct"]:
            consecutive_correct += 1
        else:
            consecutive_correct = 0
    mastery_level = min(100, consecutive_correct * 34 + review_count * 5)
    conn.execute("""
        UPDATE mistakes
        SET review_count = ?, consecutive_correct = ?, mastery_level = ?, last_reviewed_at = ?
        WHERE id = ?
    """, [review_count, consecutive_correct, mastery_level, _now_iso(), mistake_id])


def get_correction(correction_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM ai_corrections WHERE id = ?", [correction_id]).fetchone()
    conn.close()
    if row is None:
        return None
    return _parse_correction_row(row)


def get_task_corrections(task_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM ai_corrections WHERE task_id = ? ORDER BY created_at DESC",
        [task_id],
    ).fetchall()
    conn.close()
    return [_parse_correction_row(r) for r in rows]


def get_student_corrections(student_id: int, limit: int = 50, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute(
        """SELECT c.*, s.name as student_name
           FROM ai_corrections c
           JOIN students s ON s.id = c.student_id
           WHERE c.student_id = ?
           ORDER BY c.created_at DESC LIMIT ?""",
        [student_id, limit],
    ).fetchall()
    conn.close()
    return [_parse_correction_row(r) for r in rows]


def _parse_correction_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    if d.get("target_field") == "knowledge_points" and isinstance(d.get("corrected_value"), str):
        try:
            d["corrected_value"] = json.loads(d["corrected_value"])
        except Exception:
            pass
    if d.get("target_field") == "knowledge_points" and isinstance(d.get("original_value"), str):
        try:
            d["original_value"] = json.loads(d["original_value"])
        except Exception:
            pass
    return d


def revert_correction(correction_id: int, db_path: str = DB_PATH) -> bool:
    """Revert a correction. Only mistakes/questions support value rollback;
    grading corrections require a new correction record instead of revert."""
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM ai_corrections WHERE id = ? AND status = 'applied'",
        [correction_id],
    ).fetchone()
    if not row:
        conn.close()
        return False

    content_type = row["content_type"]
    target_id = row["target_id"]
    target_field = row["target_field"]
    original_value = row["original_value"]

    try:
        if content_type in ("mistake", "question") and original_value is not None:
            updates = _build_correction_updates(target_field, original_value)
            if updates:
                if content_type == "mistake":
                    table = "mistakes"
                    pk = "id"
                else:
                    table = "questions"
                    pk = "id"
                    mapped_updates = {}
                    field_map = {
                        "question": "question_text",
                        "question_text": "question_text",
                        "correct_answer": "correct_answer",
                        "explanation": "explanation",
                        "knowledge_points": "knowledge_points",
                        "difficulty": "difficulty",
                        "question_type": "question_type",
                    }
                    for k, v in updates.items():
                        mapped_updates[field_map.get(k, k)] = v
                    updates = mapped_updates
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE {table} SET {set_clause} WHERE {pk} = ?",
                    list(updates.values()) + [target_id],
                )
        elif content_type == "grading" and target_id:
            # For grading, revert is not safe without original value snapshot;
            # mark as reverted but leave practice_records to be fixed by a new correction.
            pass

        conn.execute(
            "UPDATE ai_corrections SET status = 'reverted' WHERE id = ?",
            [correction_id],
        )
        conn.commit()
    finally:
        conn.close()
    return True


def record_feedback_pattern(
    content_type: str,
    target_field: str,
    corrected_value: Any,
    target_id: int = None,
    db_path: str = DB_PATH,
) -> None:
    """Aggregate a correction into the feedback pattern table for prompt enhancement."""
    issue_type_map = {
        "correct_answer": "wrong_answer",
        "is_correct": "wrong_grading",
        "explanation": "wrong_explanation",
        "knowledge_points": "wrong_knowledge_point",
        "question": "wrong_question",
        "question_text": "wrong_question",
        "question_type": "wrong_question",
        "difficulty": "wrong_difficulty",
    }
    issue_type = issue_type_map.get(target_field, "other")

    knowledge_point = ""
    if target_id and content_type == "mistake":
        m = get_mistake(target_id, db_path)
        if m:
            kps = m.get("knowledge_points", [])
            if isinstance(kps, str):
                try:
                    kps = json.loads(kps)
                except Exception:
                    kps = []
            knowledge_point = kps[0] if kps else ""

    if isinstance(corrected_value, (list, dict)):
        corrected_value = json.dumps(corrected_value, ensure_ascii=False)

    conn = get_connection(db_path)
    existing = conn.execute(
        """SELECT id, occurrence_count FROM ai_feedback_patterns
           WHERE knowledge_point = ? AND content_type = ? AND issue_type = ?
             AND corrected_value = ?""",
        [knowledge_point, content_type, issue_type, corrected_value],
    ).fetchone()

    now = _now_iso()
    if existing:
        conn.execute(
            """UPDATE ai_feedback_patterns
               SET occurrence_count = occurrence_count + 1, last_seen_at = ?
               WHERE id = ?""",
            [now, existing["id"]],
        )
    else:
        conn.execute("""
            INSERT INTO ai_feedback_patterns
                (knowledge_point, content_type, issue_type, corrected_value, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
        """, [knowledge_point, content_type, issue_type, corrected_value, now])
    conn.commit()
    conn.close()


def get_recent_correction_hints(
    knowledge_points: List[str],
    content_type: str,
    days: int = 30,
    limit: int = 5,
    db_path: str = DB_PATH,
) -> str:
    """Return a human-readable hint string of recent corrections relevant to the given
    knowledge points and content type. Empty string if none.
    """
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    conn = get_connection(db_path)
    if knowledge_points:
        placeholders = ",".join("?" for _ in knowledge_points)
        rows = conn.execute(f"""
            SELECT knowledge_point, issue_type, corrected_value, occurrence_count
            FROM ai_feedback_patterns
            WHERE knowledge_point IN ({placeholders})
              AND content_type = ?
              AND last_seen_at >= ?
            ORDER BY occurrence_count DESC, last_seen_at DESC
            LIMIT ?
        """, list(knowledge_points) + [content_type, since, limit]).fetchall()
    else:
        rows = conn.execute("""
            SELECT knowledge_point, issue_type, corrected_value, occurrence_count
            FROM ai_feedback_patterns
            WHERE content_type = ?
              AND last_seen_at >= ?
            ORDER BY occurrence_count DESC, last_seen_at DESC
            LIMIT ?
        """, [content_type, since, limit]).fetchall()
    conn.close()

    if not rows:
        return ""

    lines = ["【近期老师纠错参考，请特别注意避免同类问题】"]
    issue_labels = {
        "wrong_answer": "答案错误",
        "wrong_explanation": "解析错误",
        "wrong_knowledge_point": "知识点归类错误",
        "wrong_grading": "批改判定错误",
        "wrong_question": "题干错误",
        "wrong_difficulty": "难度不当",
        "other": "其他",
    }
    for r in rows:
        label = issue_labels.get(r["issue_type"], r["issue_type"])
        lines.append(
            f"- 知识点「{r['knowledge_point'] or '通用'}」{label}，"
            f"共出现 {r['occurrence_count']} 次；正确参考：{r['corrected_value']}"
        )
    return "\n".join(lines)


def get_correction_stats(days: int = 7, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Return correction statistics for dashboard trend card."""
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    conn = get_connection(db_path)
    total = conn.execute(
        "SELECT COUNT(*) FROM ai_corrections WHERE created_at >= ?", [since]
    ).fetchone()[0]
    reverted = conn.execute(
        "SELECT COUNT(*) FROM ai_corrections WHERE created_at >= ? AND status = 'reverted'",
        [since],
    ).fetchone()[0]
    top_points = conn.execute("""
        SELECT m.knowledge_points, COUNT(*) as cnt
        FROM ai_corrections c
        LEFT JOIN mistakes m ON m.id = c.target_id AND c.content_type = 'mistake'
        WHERE c.created_at >= ?
        GROUP BY m.knowledge_points
        ORDER BY cnt DESC
        LIMIT 3
    """, [since]).fetchall()
    conn.close()

    # knowledge_points is JSON string; flatten first-level array
    point_counts: Dict[str, int] = {}
    for r in top_points:
        kps = r["knowledge_points"] or "[]"
        try:
            kps = json.loads(kps)
        except Exception:
            kps = []
        if kps and isinstance(kps, list):
            for p in kps:
                point_counts[p] = point_counts.get(p, 0) + r["cnt"]
    sorted_points = sorted(point_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "total": total,
        "reverted": reverted,
        "effective": total - reverted,
        "repeat_ratio": round((total - reverted) / total, 2) if total else 0.0,
        "top_knowledge_points": [{"point": p, "count": c} for p, c in sorted_points],
    }


def log_audit(actor_type: str, action: str, actor_id: str = None,
              target_type: str = None, target_id: str = None,
              details: Dict = None, ip_address: str = "",
              db_path: str = DB_PATH) -> int:
    """Write an audit log entry."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO audit_logs (actor_type, actor_id, action, target_type, target_id, details, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [actor_type, actor_id, action, target_type, target_id,
          json.dumps(details or {}, ensure_ascii=False), ip_address])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_audit_logs(limit: int = 100, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get recent audit logs."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM audit_logs
        ORDER BY created_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d.get("details", "{}"))
        except Exception:
            d["details"] = {}
        results.append(d)
    return results


def get_operations_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get overall operations stats for compliance dashboard."""
    conn = get_connection(db_path)

    total_tasks = conn.execute("SELECT COUNT(*) FROM ai_tasks").fetchone()[0]
    failed_tasks = conn.execute(
        "SELECT COUNT(*) FROM ai_tasks WHERE status = 'failed'"
    ).fetchone()[0]

    students_without_consent = conn.execute("""
        SELECT COUNT(*) FROM students s
        WHERE s.status = 'active'
          AND NOT EXISTS (SELECT 1 FROM parent_consents pc WHERE pc.student_id = s.id)
    """).fetchone()[0]

    pending_deletions = conn.execute(
        "SELECT COUNT(*) FROM deletion_requests WHERE status = 'pending'"
    ).fetchone()[0]

    pending_safety = conn.execute(
        "SELECT COUNT(*) FROM aigc_safety_checks WHERE safety_status = 'pending'"
    ).fetchone()[0]

    conn.close()

    return {
        "total_tasks": total_tasks,
        "failed_tasks": failed_tasks,
        "failure_rate": round(failed_tasks / max(total_tasks, 1) * 100, 1),
        "students_without_consent": students_without_consent,
        "pending_deletions": pending_deletions,
        "pending_safety_checks": pending_safety,
    }


# ═══════════════════════════════════════════════════
# Observability: Task Failure Monitoring
# ═══════════════════════════════════════════════════

def get_task_failure_stats(days: int = 7, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Return task failure/rejection statistics for the last N days."""
    conn = get_connection(db_path)
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")

    total = conn.execute(
        "SELECT COUNT(*) FROM ai_tasks WHERE created_at >= ?",
        [since]
    ).fetchone()[0]
    failed = conn.execute(
        "SELECT COUNT(*) FROM ai_tasks WHERE status = 'failed' AND created_at >= ?",
        [since]
    ).fetchone()[0]
    rejected = conn.execute(
        "SELECT COUNT(*) FROM ai_tasks WHERE status = 'rejected' AND created_at >= ?",
        [since]
    ).fetchone()[0]

    # Daily breakdown
    rows = conn.execute("""
        SELECT date(created_at) as day,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
               SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
        FROM ai_tasks
        WHERE created_at >= ?
        GROUP BY date(created_at)
        ORDER BY day DESC
    """, [since]).fetchall()
    daily = [dict(r) for r in rows]

    # By task type
    type_rows = conn.execute("""
        SELECT task_type,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
               SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
        FROM ai_tasks
        WHERE created_at >= ?
        GROUP BY task_type
    """, [since]).fetchall()
    by_type = [dict(r) for r in type_rows]

    conn.close()
    return {
        "days": days,
        "total": total,
        "failed": failed,
        "rejected": rejected,
        "failure_rate": round(failed / max(total, 1) * 100, 1),
        "daily_breakdown": daily,
        "by_type": by_type,
    }


def get_recent_failed_tasks(limit: int = 20, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return recent failed tasks with student name and error message."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT t.id, t.student_id, t.task_type, t.status, t.error_message,
               t.created_at, t.completed_at, s.name as student_name
        FROM ai_tasks t
        JOIN students s ON s.id = t.student_id
        WHERE t.status IN ('failed', 'rejected')
        ORDER BY t.completed_at DESC NULLS LAST, t.created_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════
# Observability: Audit Logs
# ═══════════════════════════════════════════════════

def get_audit_logs_filtered(
    limit: int = 100,
    offset: int = 0,
    actor_type: str = None,
    action: str = None,
    target_type: str = None,
    since: str = None,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """Get audit logs with optional filters."""
    conn = get_connection(db_path)
    where = ["1=1"]
    params = []
    if actor_type:
        where.append("actor_type = ?")
        params.append(actor_type)
    if action:
        where.append("action = ?")
        params.append(action)
    if target_type:
        where.append("target_type = ?")
        params.append(target_type)
    if since:
        where.append("created_at >= ?")
        params.append(since)

    sql = f"""
        SELECT * FROM audit_logs
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(sql, params + [limit, offset]).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d.get("details", "{}"))
        except Exception:
            d["details"] = {}
        results.append(d)
    return results


def get_audit_log_actions(db_path: str = DB_PATH) -> List[str]:
    """Return distinct actions in audit_logs for filter dropdown."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT DISTINCT action FROM audit_logs WHERE action IS NOT NULL ORDER BY action"
    ).fetchall()
    conn.close()
    return [r["action"] for r in rows]


# ═══════════════════════════════════════════════════
# Observability: Alerts
# ═══════════════════════════════════════════════════

def create_alert(
    alert_type: str,
    level: str,
    message: str,
    related_id: str = None,
    details: Dict = None,
    db_path: str = DB_PATH,
) -> int:
    """Create a new alert if an equivalent active one does not already exist."""
    conn = get_connection(db_path)
    existing = conn.execute("""
        SELECT id FROM alerts
        WHERE alert_type = ? AND level = ? AND related_id = ? AND dismissed = 0
    """, [alert_type, level, related_id or ""]).fetchone()
    if existing:
        conn.close()
        return existing["id"]

    cur = conn.execute("""
        INSERT INTO alerts (alert_type, level, message, related_id, details)
        VALUES (?, ?, ?, ?, ?)
    """, [alert_type, level, message, related_id or "",
          json.dumps(details or {}, ensure_ascii=False)])
    conn.commit()
    conn.close()
    return cur.lastrowid


def dismiss_alert(alert_id: int, db_path: str = DB_PATH) -> bool:
    """Dismiss an active alert."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM alerts WHERE id = ? AND dismissed = 0", [alert_id]).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute(
        "UPDATE alerts SET dismissed = 1, dismissed_at = ? WHERE id = ?",
        [_now_iso(), alert_id],
    )
    conn.commit()
    conn.close()
    return True


def get_active_alerts(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return all active (non-dismissed) alerts."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM alerts
        WHERE dismissed = 0
        ORDER BY created_at DESC
        LIMIT 50
    """).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d.get("details", "{}"))
        except Exception:
            d["details"] = {}
        results.append(d)
    return results


def get_cost_alert_status(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Check cost budgets and return active/would-be alert status."""
    budgets = get_budgets(db_path)
    monthly_total_budget = budgets.get("monthly_total_budget", 100.0)
    monthly_student_budget = budgets.get("monthly_student_budget", 20.0)

    threshold_setting = get_setting("cost_alert_threshold_pct", db_path)
    threshold_pct = float(threshold_setting) if threshold_setting else 80.0
    threshold = threshold_pct / 100.0

    month_cost = get_llm_cost_this_month(db_path)
    alerts = []

    month_pct = round(month_cost / max(monthly_total_budget, 0.01) * 100, 1)
    if month_cost >= monthly_total_budget:
        alerts.append({
            "type": "cost_total",
            "level": "critical",
            "message": f"月度总成本 ${month_cost:.4f} 已超过预算 ${monthly_total_budget:.2f}",
            "current": month_cost,
            "threshold": monthly_total_budget,
            "pct": month_pct,
        })
    elif month_cost >= monthly_total_budget * threshold:
        alerts.append({
            "type": "cost_total",
            "level": "warning",
            "message": f"月度总成本已达预算的 {month_pct}% (${month_cost:.4f} / ${monthly_total_budget:.2f})",
            "current": month_cost,
            "threshold": monthly_total_budget,
            "pct": month_pct,
        })

    # Per-student checks (llm_usage_log has task_id, join ai_tasks for student_id)
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT t.student_id, SUM(l.estimated_cost) as cost
        FROM llm_usage_log l
        JOIN ai_tasks t ON t.id = l.task_id
        WHERE l.cached = 0
          AND strftime('%Y-%m', l.created_at) = strftime('%Y-%m', 'now')
        GROUP BY t.student_id
        HAVING cost >= ?
    """, [monthly_student_budget * threshold]).fetchall()
    conn.close()

    for r in rows:
        sid = r["student_id"]
        cost = r["cost"]
        pct = round(cost / max(monthly_student_budget, 0.01) * 100, 1)
        student = get_student(sid, db_path)
        student_name = student["name"] if student else f"学生{sid}"
        if cost >= monthly_student_budget:
            alerts.append({
                "type": "cost_student",
                "level": "critical",
                "related_id": str(sid),
                "message": f"{student_name} 本月成本 ${cost:.4f} 已超过单人预算 ${monthly_student_budget:.2f}",
                "current": cost,
                "threshold": monthly_student_budget,
                "pct": pct,
            })
        else:
            alerts.append({
                "type": "cost_student",
                "level": "warning",
                "related_id": str(sid),
                "message": f"{student_name} 本月成本已达单人预算的 {pct}% (${cost:.4f} / ${monthly_student_budget:.2f})",
                "current": cost,
                "threshold": monthly_student_budget,
                "pct": pct,
            })

    return {
        "alerts": alerts,
        "monthly_pct": month_pct,
        "threshold_pct": threshold_pct,
        "any_alert": len(alerts) > 0,
        "month_cost": month_cost,
        "monthly_budget": monthly_total_budget,
    }


# ═══════════════════════════════════════════════════
# Observability: Backups
# ═══════════════════════════════════════════════════

def record_backup(backup_path: str, backup_type: str, file_size: int,
                  db_path: str = DB_PATH) -> int:
    """Record a backup in the backups table."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO backups (backup_path, backup_type, file_size)
        VALUES (?, ?, ?)
    """, [backup_path, backup_type, file_size])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_backups(limit: int = 50, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return backup history."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT * FROM backups
        ORDER BY created_at DESC
        LIMIT ?
    """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cleanup_old_backups(daily_keep: int = 7, weekly_keep: int = 4,
                        db_path: str = DB_PATH) -> Dict[str, Any]:
    """Remove old backup files and records according to retention policy."""
    import os
    conn = get_connection(db_path)
    deleted = []

    for backup_type, keep in [("daily", daily_keep), ("weekly", weekly_keep)]:
        rows = conn.execute("""
            SELECT id, backup_path FROM backups
            WHERE backup_type = ?
            ORDER BY created_at DESC
        """, [backup_type]).fetchall()
        for row in rows[keep:]:
            path = row["backup_path"]
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
            conn.execute("DELETE FROM backups WHERE id = ?", [row["id"]])
            deleted.append(path)

    conn.commit()
    conn.close()
    return {"deleted_count": len(deleted), "deleted_paths": deleted}


# ═══════════════════════════════════════════════════
# Teacher Workload / Efficiency
# ═══════════════════════════════════════════════════

def get_teacher_workload_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get stats for teacher efficiency dashboard.

    P3-13：审核闸门已移除，删除 pending_review / reviewed_* / recent_rejected
    等审核口径统计；保留「本周待上传试卷」这一仍有意义的运营提醒。
    """
    conn = get_connection(db_path)
    week_start = get_week_start()

    # Students needing paper upload this week
    pending_paper = conn.execute("""
        SELECT s.id, s.name, s.grade
        FROM students s
        LEFT JOIN weekly_records wr
               ON wr.student_id = s.id AND wr.week_start = ? AND wr.kind = 'weekly'
        WHERE s.status = 'active'
          AND (wr.paper_submitted IS NULL OR wr.paper_submitted = 0)
        ORDER BY s.name
    """, [week_start]).fetchall()

    conn.close()

    return {
        "pending_paper_uploads": [dict(r) for r in pending_paper],
    }


# ═══════════════════════════════════════════════════
# Question Bank
# ═══════════════════════════════════════════════════

def save_question(question_data: Dict[str, Any], db_path: str = DB_PATH) -> int:
    """Save a question to the question bank. Returns question id."""
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO questions (question_text, question_type, correct_answer, explanation,
            knowledge_points, difficulty, source, source_mistake_id, usage_count, enabled)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
    """, [
        question_data.get("question_text", ""),
        question_data.get("question_type", ""),
        question_data.get("correct_answer", ""),
        question_data.get("explanation", ""),
        json.dumps(question_data.get("knowledge_points", []), ensure_ascii=False),
        question_data.get("difficulty", 2),
        question_data.get("source", "llm"),
        question_data.get("source_mistake_id"),
    ])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_question(question_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM questions WHERE id = ?", [question_id]).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
    return d


def get_questions(knowledge_point: str = None, question_type: str = None,
                  enabled_only: bool = True, limit: int = 100,
                  db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get questions from bank with optional filters."""
    conn = get_connection(db_path)
    query = "SELECT * FROM questions WHERE 1=1"
    params = []
    if enabled_only:
        query += " AND enabled = 1"
    if question_type:
        query += " AND question_type = ?"
        params.append(question_type)
    if knowledge_point:
        query += " AND knowledge_points LIKE ?"
        params.append(f"%{knowledge_point}%")
    query += " ORDER BY usage_count DESC, created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
        results.append(d)
    return results


def find_similar_questions(knowledge_points: List[str], question_type: str = None,
                           difficulty: int = None, limit: int = 5,
                           db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Find questions matching any of the given knowledge points."""
    if not knowledge_points:
        return []
    conn = get_connection(db_path)

    # Build LIKE conditions for each knowledge point
    conditions = []
    params = []
    for kp in knowledge_points:
        conditions.append("knowledge_points LIKE ?")
        params.append(f"%{kp}%")

    query = f"SELECT * FROM questions WHERE enabled = 1 AND ({' OR '.join(conditions)})"
    if question_type:
        query += " AND question_type = ?"
        params.append(question_type)
    if difficulty is not None:
        query += " AND difficulty = ?"
        params.append(difficulty)
    query += " ORDER BY usage_count ASC, created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["knowledge_points"] = json.loads(d.get("knowledge_points", "[]"))
        results.append(d)
    return results


def increment_question_usage(question_ids: List[int], db_path: str = DB_PATH) -> None:
    """Increment usage_count for used questions."""
    if not question_ids:
        return
    conn = get_connection(db_path)
    placeholders = ",".join("?" * len(question_ids))
    conn.execute(f"""
        UPDATE questions SET usage_count = usage_count + 1
        WHERE id IN ({placeholders})
    """, question_ids)
    conn.commit()
    conn.close()


def update_question(question_id: int, updates: Dict[str, Any],
                    db_path: str = DB_PATH) -> bool:
    """Update a question in the bank."""
    if not updates:
        return False
    allowed = {"question_text", "question_type", "correct_answer", "explanation",
               "knowledge_points", "difficulty", "enabled"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return False

    if "knowledge_points" in filtered and isinstance(filtered["knowledge_points"], list):
        filtered["knowledge_points"] = json.dumps(filtered["knowledge_points"], ensure_ascii=False)

    conn = get_connection(db_path)
    row = conn.execute("SELECT id FROM questions WHERE id = ?", [question_id]).fetchone()
    if not row:
        conn.close()
        return False
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    conn.execute(f"UPDATE questions SET {set_clause} WHERE id = ?",
                 list(filtered.values()) + [question_id])
    conn.commit()
    conn.close()
    return True


def get_question_bank_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Get question bank statistics."""
    conn = get_connection(db_path)
    total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    enabled = conn.execute("SELECT COUNT(*) FROM questions WHERE enabled = 1").fetchone()[0]
    used = conn.execute("SELECT COUNT(*) FROM questions WHERE usage_count > 0").fetchone()[0]
    total_usage = conn.execute("SELECT COALESCE(SUM(usage_count), 0) FROM questions").fetchone()[0]

    # Top knowledge points
    rows = conn.execute("SELECT knowledge_points FROM questions WHERE enabled = 1").fetchall()
    kp_counts: Dict[str, int] = {}
    for r in rows:
        for kp in json.loads(r["knowledge_points"] or "[]"):
            kp_counts[kp] = kp_counts.get(kp, 0) + 1
    top_kp = sorted(kp_counts.items(), key=lambda x: -x[1])[:10]

    conn.close()
    return {
        "total_questions": total,
        "enabled_questions": enabled,
        "used_questions": used,
        "total_usage": total_usage,
        "reuse_rate": round(used / max(total, 1) * 100, 1),
        "top_knowledge_points": [{"knowledge_point": kp, "count": c} for kp, c in top_kp],
    }


# ═══════════════════════════════════════════════════
# LLM Usage Logging
# ═══════════════════════════════════════════════════

def log_llm_usage(task_id: int = None, call_type: str = "", model: str = "",
                  prompt_tokens: int = 0, output_tokens: int = 0,
                  estimated_cost: float = 0.0, duration_ms: int = 0,
                  retry_count: int = 0, cached: int = 0,
                  db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO llm_usage_log (task_id, call_type, model, prompt_tokens,
            output_tokens, estimated_cost, duration_ms, retry_count, cached)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [task_id, call_type, model, prompt_tokens, output_tokens,
          estimated_cost, duration_ms, retry_count, cached])
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_llm_cost_today(db_path: str = DB_PATH) -> float:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT COALESCE(SUM(estimated_cost), 0) FROM llm_usage_log
        WHERE date(created_at) = date('now') AND cached = 0
    """).fetchone()
    conn.close()
    return row[0]


def get_llm_cost_this_month(db_path: str = DB_PATH) -> float:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT COALESCE(SUM(estimated_cost), 0) FROM llm_usage_log
        WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now') AND cached = 0
    """).fetchone()
    conn.close()
    return row[0]


# ═══════════════════════════════════════════════════
# Cost Guard & Budgeting
# ═══════════════════════════════════════════════════

DEFAULT_BUDGETS = {
    "monthly_total_budget": "100.0",    # USD
    "monthly_student_budget": "20.0",   # USD per student
    # weekly_question_target 已于 2026-08-04 移除：练习题数量策略改为每错题 2 题、不设总量上限
}

FEATURE_FLAGS = {
    "feature_school_enabled": "false",
    "feature_teacher_enabled": "false",
}


def is_feature_enabled(key: str, db_path: str = DB_PATH) -> bool:
    val = get_setting(key, db_path)
    if val is None:
        val = FEATURE_FLAGS.get(key, "false")
    return str(val).lower() in ("true", "1", "yes")


def get_setting(key: str, db_path: str = DB_PATH) -> Optional[str]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT value FROM settings WHERE key = ?", [key]).fetchone()
    conn.close()
    return row["value"] if row else DEFAULT_BUDGETS.get(key)


def set_setting(key: str, value: str, db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("""
        INSERT OR REPLACE INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
    """, [key, value, _now_iso()])
    conn.commit()
    conn.close()


def get_budgets(db_path: str = DB_PATH) -> Dict[str, float]:
    """Return current budget settings."""
    return {
        "monthly_total_budget": float(get_setting("monthly_total_budget", db_path) or "100.0"),
        "monthly_student_budget": float(get_setting("monthly_student_budget", db_path) or "20.0"),
    }


def get_student_llm_cost(student_id: int, period: str = "month", db_path: str = DB_PATH) -> float:
    """Get LLM cost for a specific student. period: 'month' | 'today' | 'total'."""
    conn = get_connection(db_path)
    if period == "today":
        row = conn.execute("""
            SELECT COALESCE(SUM(l.estimated_cost), 0)
            FROM llm_usage_log l
            JOIN ai_tasks t ON t.id = l.task_id
            WHERE t.student_id = ? AND date(l.created_at) = date('now') AND l.cached = 0
        """, [student_id]).fetchone()
    elif period == "month":
        row = conn.execute("""
            SELECT COALESCE(SUM(l.estimated_cost), 0)
            FROM llm_usage_log l
            JOIN ai_tasks t ON t.id = l.task_id
            WHERE t.student_id = ? AND strftime('%Y-%m', l.created_at) = strftime('%Y-%m', 'now') AND l.cached = 0
        """, [student_id]).fetchone()
    else:  # total
        row = conn.execute("""
            SELECT COALESCE(SUM(l.estimated_cost), 0)
            FROM llm_usage_log l
            JOIN ai_tasks t ON t.id = l.task_id
            WHERE t.student_id = ? AND l.cached = 0
        """, [student_id]).fetchone()
    conn.close()
    return row[0]


def get_llm_cost_breakdown(period: str = "month", db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get cost grouped by student."""
    conn = get_connection(db_path)
    if period == "today":
        date_filter = "date(l.created_at) = date('now')"
    elif period == "month":
        date_filter = "strftime('%Y-%m', l.created_at) = strftime('%Y-%m', 'now')"
    else:
        date_filter = "1=1"

    rows = conn.execute(f"""
        SELECT s.id, s.name, s.grade,
               COALESCE(SUM(l.estimated_cost), 0) as cost,
               COUNT(l.id) as calls
        FROM students s
        LEFT JOIN ai_tasks t ON t.student_id = s.id
        LEFT JOIN llm_usage_log l ON l.task_id = t.id AND l.cached = 0 AND {date_filter}
        WHERE s.status = 'active'
        GROUP BY s.id
        ORDER BY cost DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_cost_budget(student_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Check if a new task would exceed budget. Returns dict with allowed and reasons."""
    budgets = get_budgets(db_path)
    total_month = get_llm_cost_this_month(db_path)
    student_month = get_student_llm_cost(student_id, "month", db_path)

    allowed = True
    reasons = []

    if total_month >= budgets["monthly_total_budget"]:
        allowed = False
        reasons.append(
            f"月度总成本 ${total_month:.4f} 已达到预算 ${budgets['monthly_total_budget']:.2f}"
        )

    if student_month >= budgets["monthly_student_budget"]:
        allowed = False
        reasons.append(
            f"该学生本月成本 ${student_month:.4f} 已达到单人预算 ${budgets['monthly_student_budget']:.2f}"
        )

    return {
        "allowed": allowed,
        "reasons": reasons,
        "total_month": round(total_month, 6),
        "student_month": round(student_month, 6),
        "monthly_total_budget": budgets["monthly_total_budget"],
        "monthly_student_budget": budgets["monthly_student_budget"],
    }


# ═══════════════════════════════════════════════════
# Student Operations (保留原 app.py CRUD)
# ═══════════════════════════════════════════════════

def get_all_students(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT s.*, sub.plan, sub.status as sub_status, sub.end_date as sub_end_date,
               COALESCE(sub.plan, 'trial') as plan_label,
               COALESCE(stu_cost.cost, 0) as month_cost
        FROM students s
        LEFT JOIN subscriptions sub ON sub.student_id = s.id
        LEFT JOIN (
            SELECT t.student_id, SUM(l.estimated_cost) as cost
            FROM llm_usage_log l
            JOIN ai_tasks t ON t.id = l.task_id
            WHERE strftime('%Y-%m', l.created_at) = strftime('%Y-%m', 'now') AND l.cached = 0
            GROUP BY t.student_id
        ) stu_cost ON stu_cost.student_id = s.id
        WHERE s.status = 'active'
        ORDER BY s.name
    """).fetchall()
    conn.close()
    plan_labels = {p: info["label"] for p, info in PRICING.items()}
    results = []
    for r in rows:
        d = dict(r)
        plan = d.get("plan") or "trial"
        d["plan_label"] = plan_labels.get(plan, plan)
        # Auto-correct status based on date
        d["sub_status"] = _subscription_status(d.get("sub_end_date")) if d.get("sub_status") else "active"
        # Compute days remaining for easier frontend display
        end_date_str = d.get("sub_end_date")
        d["days_remaining"] = None
        if end_date_str:
            try:
                d["days_remaining"] = (date.fromisoformat(end_date_str) - date.today()).days
            except (ValueError, TypeError):
                pass
        results.append(d)
    return results


def get_student(student_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT s.*, sub.plan, sub.status as sub_status
        FROM students s
        LEFT JOIN subscriptions sub ON sub.student_id = s.id
        WHERE s.id = ?
    """, [student_id]).fetchone()
    conn.close()
    return dict(row) if row else None


def create_student(data: Dict[str, Any], db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO students (name, grade, school_type, english_score, target_score,
            parent_name, parent_wechat, parent_phone, notes, access_code, parent_access_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        data["name"], data.get("grade", "高二"), data.get("school_type", "住校"),
        data.get("english_score"), data.get("target_score"),
        data.get("parent_name"), data.get("parent_wechat"), data.get("parent_phone"),
        data.get("notes"),
        data.get("access_code") or _generate_access_code(conn, "students", "access_code"),
        data.get("parent_access_code") or _generate_access_code(conn, "students", "parent_access_code"),
    ])
    student_id = cur.lastrowid

    # Auto-create subscription（按 PRICING 填充额度，避免运行时建号额度为 0）
    plan = data.get("plan", "trial")
    if plan not in PRICING:
        plan = "trial"
    plan_info = PRICING[plan]
    # 付费套餐建号即计时；trial/unlimited 为一次性池，不设有效期
    end_date = None
    if plan in ("monthly", "yearly"):
        end_date = (date.today() + timedelta(days=30 if plan == "monthly" else 365)).isoformat()
    try:
        conn.execute("""
            INSERT INTO subscriptions
                (student_id, plan, monthly_quota, reset_month, start_date, end_date, status)
            VALUES (?, ?, ?, ?, date('now'), ?, 'active')
        """, [student_id, plan, plan_info["monthly_quota"],
              date.today().strftime("%Y-%m"), end_date])
        conn.commit()
    finally:
        conn.close()
    return student_id


def update_student(student_id: int, data: Dict[str, Any], db_path: str = DB_PATH) -> bool:
    conn = get_connection(db_path)
    try:
        conn.execute("""
            UPDATE students SET name=?, grade=?, school_type=?, english_score=?,
                target_score=?, parent_name=?, parent_wechat=?, parent_phone=?, notes=?
            WHERE id=?
        """, [
            data["name"], data.get("grade"), data.get("school_type"),
            data.get("english_score"), data.get("target_score"),
            data.get("parent_name"), data.get("parent_wechat"), data.get("parent_phone"),
            data.get("notes"), student_id
        ])
        plan = data.get("plan")
        if plan:
            if plan not in PRICING:
                plan = "trial"
            # UPSERT：只更新套餐与额度，保留 used_count/end_date/price/start_date，
            # 避免"改套餐 = 清空当月用量/变成永久有效"的老问题
            conn.execute("""
                INSERT INTO subscriptions
                    (student_id, plan, monthly_quota, reset_month, start_date, status)
                VALUES (?, ?, ?, ?,
                        COALESCE((SELECT start_date FROM subscriptions WHERE student_id=?), date('now')),
                        'active')
                ON CONFLICT(student_id) DO UPDATE SET
                    plan = excluded.plan,
                    monthly_quota = excluded.monthly_quota
            """, [student_id, plan, PRICING[plan]["monthly_quota"],
                  date.today().strftime("%Y-%m"), student_id])
        conn.commit()
    finally:
        conn.close()
    return True


def _generate_access_code(conn: sqlite3.Connection, table: str, column: str) -> str:
    """Generate a unique access code.

    加密随机 token_urlsafe(8)（约 11 位）：6 位数字仅 90 万空间且非加密随机，
    公开接口凭码即可读学生数据，可被暴力枚举（安全审查 P0）。存量 6 位码
    继续有效（仅影响新生成）。
    """
    import secrets
    for _ in range(100):
        code = secrets.token_urlsafe(8)
        existing = conn.execute(
            f"SELECT id FROM {table} WHERE {column} = ?", [code]
        ).fetchone()
        if not existing:
            return code
    raise RuntimeError("无法生成唯一 access_code")


# ═══════════════════════════════════════════════════
# Student Profile Operations (参考 chat.md 六大部分)
# ═══════════════════════════════════════════════════

def get_student_profile(student_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Get student profile (1:1 with students). Returns None if not created yet."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM student_profiles WHERE student_id = ?", [student_id]).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    json_fields = {
        "time_map", "assessments", "plan_choices", "recent_scores",
        "weak_question_types", "peak_energy_slots", "learning_style_detail",
    }
    for field in json_fields:
        try:
            d[field] = json.loads(d.get(field) or "{}")
        except Exception:
            d[field] = {}
    return d


def save_student_profile(student_id: int, data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    """Create or update student profile."""
    conn = get_connection(db_path)

    json_fields = {
        "time_map", "assessments", "plan_choices", "recent_scores",
        "weak_question_types", "peak_energy_slots", "parent_task_progress",
        "learning_style_detail",
    }
    profile_fields = [
        "gender", "semester", "academic_goal", "subject_choice", "textbook_version",
        "time_map", "weekly_available_hours", "peak_energy_slots", "committed_english_minutes",
        "recent_scores", "weak_areas", "weak_question_types", "score_loss_reason",
        "confused_grammar", "existing_resources", "vocab_direction",
        "learning_style", "learning_style_detail", "learning_medium", "vocab_habit", "attention_weakness",
        "effective_methods", "ineffective_methods", "english_identity",
        "assessments",
        "target_timeline", "one_month_goal", "parent_availability",
        "supervision_needed", "study_environment",
        "least_favorite_task", "preferred_intensity", "aspirational_use",
        "plan_choices", "plan_name", "plan_code_name", "parent_task_progress",
    ]

    values = []
    for field in profile_fields:
        val = data.get(field)
        if field in json_fields and val is not None:
            if isinstance(val, str):
                val = val.strip()
                if not val:
                    val = None
                else:
                    try:
                        val = json.loads(val)
                    except Exception:
                        # For free-text fields that are meant to be JSON objects,
                        # wrap plain text so it round-trips.
                        if field == "time_map":
                            val = {"description": val}
            if val is not None:
                val = json.dumps(val, ensure_ascii=False)
        values.append(val)

    placeholders = ", ".join("?" for _ in profile_fields)
    columns = ", ".join(profile_fields)
    conn.execute(f"""
        INSERT INTO student_profiles (student_id, {columns}, updated_at)
        VALUES (?, {placeholders}, ?)
        ON CONFLICT(student_id) DO UPDATE SET
            {", ".join(f"{f} = excluded.{f}" for f in profile_fields)},
            updated_at = excluded.updated_at
    """, [student_id] + values + [_now_iso()])
    conn.commit()
    conn.close()


def has_student_profile(student_id: int, db_path: str = DB_PATH) -> bool:
    """Check if a student has a profile."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT 1 FROM student_profiles WHERE student_id = ?", [student_id]).fetchone()
    conn.close()
    return row is not None


# ═══════════════════════════════════════════════════
# Dashboard Operations
# ═══════════════════════════════════════════════════

def get_dashboard_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    conn = get_connection(db_path)
    monday = get_week_start()

    total = conn.execute("SELECT COUNT(*) FROM students WHERE status='active'").fetchone()[0]
    active_subs = conn.execute(
        "SELECT COUNT(*) FROM subscriptions WHERE status='active'"
    ).fetchone()[0]
    trial_count = conn.execute(
        "SELECT COUNT(*) FROM subscriptions WHERE plan='trial' AND status='active'"
    ).fetchone()[0]

    pending_rows = conn.execute("""
        SELECT s.id, s.name, s.grade, sub.plan,
               wr.paper_submitted, wr.paper_analyzed, wr.exercises_sent,
               wr.exercises_completed, wr.exercises_graded, wr.report_sent,
               wr.week_start, wr.stage, wr.updated_at
        FROM students s
        LEFT JOIN subscriptions sub ON sub.student_id = s.id
        LEFT JOIN weekly_records wr
               ON wr.student_id = s.id AND wr.week_start = ? AND wr.kind = 'weekly'
        WHERE s.status = 'active'
        ORDER BY s.name
    """, [monday]).fetchall()

    plan_labels = {p: info["label"] for p, info in PRICING.items()}
    pending_this_week = 0
    pending_list = []

    from domain import cycle as cycle_mod
    for row in pending_rows:
        plan = row["plan"] or "trial"
        rec = dict(row)
        rec["plan_label"] = plan_labels.get(plan, plan)
        # P2-11：链路视角 —— 周期状态机当前态 + 卡住标记
        rec["stage_label"] = cycle_mod.stage_label(rec.get("stage"))
        rec["stuck"] = cycle_mod.is_stuck(rec)
        pending_list.append(rec)
        if not row["exercises_sent"]:
            pending_this_week += 1

    # P3-13：审核队列已删除（D1 决策：审核闸门移除，质量靠抽检+纠错回路）

    # 订阅到期/续费提醒
    expiring = get_expiring_subscriptions(days=7, db_path=db_path)

    # 题库统计
    qb_stats = get_question_bank_stats(db_path=db_path)

    # 老师工作台统计
    teacher_stats = get_teacher_workload_stats(db_path=db_path)

    # 合规统计
    students_without_consent = conn.execute("""
        SELECT COUNT(*) FROM students s
        WHERE s.status = 'active'
          AND NOT EXISTS (SELECT 1 FROM parent_consents pc WHERE pc.student_id = s.id)
    """).fetchone()[0]
    pending_deletions = conn.execute(
        "SELECT COUNT(*) FROM deletion_requests WHERE status = 'pending'"
    ).fetchone()[0]

    conn.close()
    return {
        "total_students": total,
        "active_subscriptions": active_subs,
        "trial_count": trial_count,
        "pending_this_week": pending_this_week,
        "week_start": monday,
        "pending": pending_list,
        "expiring_subscriptions": expiring,
        "question_bank": qb_stats,
        "teacher_workload": teacher_stats,
        "students_without_consent": students_without_consent,
        "pending_deletions": pending_deletions,
    }


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


# ═══════════════════════════════════════════════════
# Schools & Classes
# ═══════════════════════════════════════════════════

def create_school(name: str, aliases: List[str] = None, region: str = None,
                  db_path: str = DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.execute(
        "INSERT INTO schools (name, aliases, region) VALUES (?, ?, ?)",
        [name, json.dumps(aliases or [], ensure_ascii=False), region],
    )
    conn.commit()
    school_id = cur.lastrowid
    conn.close()
    return school_id


def get_school(school_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM schools WHERE id = ?", [school_id]).fetchone()
    conn.close()
    if row:
        d = dict(row)
        try:
            d["aliases"] = json.loads(d.get("aliases") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["aliases"] = []
        return d
    return None


def search_schools(keyword: str, limit: int = 10, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Fuzzy search schools by name or aliases."""
    if not keyword or not keyword.strip():
        return []
    conn = get_connection(db_path)
    like = f"%{keyword.strip()}%"
    rows = conn.execute(
        "SELECT * FROM schools WHERE name LIKE ? OR aliases LIKE ? ORDER BY name LIMIT ?",
        [like, like, limit],
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["aliases"] = json.loads(d.get("aliases") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["aliases"] = []
        results.append(d)
    return results


def get_all_schools(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM schools ORDER BY name").fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["aliases"] = json.loads(d.get("aliases") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["aliases"] = []
        results.append(d)
    return results


def update_school(school_id: int, data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    fields = []
    values = []
    for key in ("name", "region"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "aliases" in data:
        fields.append("aliases = ?")
        values.append(json.dumps(data["aliases"], ensure_ascii=False))
    if fields:
        values.append(school_id)
        conn.execute(f"UPDATE schools SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    conn.close()


def delete_school(school_id: int, db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("DELETE FROM schools WHERE id = ?", [school_id])
    conn.commit()
    conn.close()


def _generate_class_code(conn) -> str:
    """Generate a unique 6-digit class code."""
    import random
    for _ in range(100):
        code = f"{random.randint(100000, 999999)}"
        exists = conn.execute("SELECT 1 FROM classes WHERE class_code = ?", [code]).fetchone()
        if not exists:
            return code
    raise RuntimeError("Cannot generate unique class code")


def create_class(school_id: int, name: str, grade: str = None,
                 teacher_id: int = None, db_path: str = DB_PATH) -> Dict[str, Any]:
    conn = get_connection(db_path)
    class_code = _generate_class_code(conn)
    cur = conn.execute(
        "INSERT INTO classes (school_id, name, grade, teacher_id, class_code) VALUES (?, ?, ?, ?, ?)",
        [school_id, name, grade, teacher_id, class_code],
    )
    conn.commit()
    class_id = cur.lastrowid
    row = conn.execute("SELECT * FROM classes WHERE id = ?", [class_id]).fetchone()
    conn.close()
    return dict(row)


def get_class(class_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT c.*, s.name as school_name
        FROM classes c
        JOIN schools s ON s.id = c.school_id
        WHERE c.id = ?
    """, [class_id]).fetchone()
    conn.close()
    return dict(row) if row else None


def get_class_by_code(class_code: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT c.*, s.name as school_name
        FROM classes c
        JOIN schools s ON s.id = c.school_id
        WHERE c.class_code = ?
    """, [class_code]).fetchone()
    conn.close()
    return dict(row) if row else None


def get_classes_by_school(school_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT c.*, au.username as teacher_name
        FROM classes c
        LEFT JOIN admin_users au ON au.id = c.teacher_id
        WHERE c.school_id = ?
        ORDER BY c.name
    """, [school_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_classes_by_teacher(teacher_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT c.*, s.name as school_name
        FROM classes c
        JOIN schools s ON s.id = c.school_id
        WHERE c.teacher_id = ?
        ORDER BY s.name, c.name
    """, [teacher_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_class(class_id: int, data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    fields = []
    values = []
    for key in ("name", "grade", "teacher_id"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if fields:
        values.append(class_id)
        conn.execute(f"UPDATE classes SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    conn.close()


def delete_class(class_id: int, db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("UPDATE students SET class_id = NULL WHERE class_id = ?", [class_id])
    conn.execute("DELETE FROM classes WHERE id = ?", [class_id])
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════
# Student Registration & Auth
# ═══════════════════════════════════════════════════

def register_student(phone: str, password_hash: str, name: str,
                     school_id: int, class_id: int,
                     grade: str = None, textbook_version: str = None,
                     db_path: str = DB_PATH) -> int:
    """Register a new student account with phone login."""
    conn = get_connection(db_path)
    existing = conn.execute("SELECT id FROM students WHERE phone = ?", [phone]).fetchone()
    if existing:
        conn.close()
        raise ValueError("该手机号已注册")
    access_code = _generate_access_code(conn, "students", "access_code")
    parent_access_code = _generate_access_code(conn, "students", "parent_access_code")
    cur = conn.execute("""
        INSERT INTO students (name, grade, phone, password_hash, school_id, class_id,
                              access_code, parent_access_code, textbook_version, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
    """, [name, grade or "高二", phone, password_hash, school_id, class_id,
          access_code, parent_access_code, textbook_version])
    student_id = cur.lastrowid
    conn.execute(
        "INSERT INTO subscriptions (student_id, plan, start_date) VALUES (?, 'trial', ?)",
        [student_id, date.today().isoformat()],
    )
    conn.commit()
    conn.close()
    return student_id


def get_student_by_phone(phone: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT s.*, sc.name as school_name, cl.name as class_name
        FROM students s
        LEFT JOIN schools sc ON sc.id = s.school_id
        LEFT JOIN classes cl ON cl.id = s.class_id
        WHERE s.phone = ? AND s.status = 'active'
    """, [phone]).fetchone()
    conn.close()
    return dict(row) if row else None


def get_students_by_class(class_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT s.id, s.name, s.grade, s.phone, s.english_score, s.target_score,
               s.access_code, s.created_at, s.status
        FROM students s
        WHERE s.class_id = ? AND s.status = 'active'
        ORDER BY s.name
    """, [class_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_students_by_teacher(teacher_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Get all students in classes assigned to a teacher.
    In C-end mode (no class), fall back to all active students."""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT s.id, s.name, s.grade, s.phone, s.english_score, s.target_score,
               s.access_code, s.created_at, s.status,
               cl.name as class_name, sc.name as school_name
        FROM students s
        LEFT JOIN classes cl ON cl.id = s.class_id
        LEFT JOIN schools sc ON sc.id = cl.school_id
        WHERE (cl.teacher_id = ? OR s.class_id IS NULL) AND s.status = 'active'
        ORDER BY s.name
    """, [teacher_id]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_class_stats(class_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Aggregate statistics for a class."""
    conn = get_connection(db_path)

    student_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM students WHERE class_id = ? AND status = 'active'",
        [class_id],
    ).fetchone()["cnt"]

    week_start = get_week_start()
    active_this_week = conn.execute("""
        SELECT COUNT(DISTINCT s.id) as cnt
        FROM students s
        JOIN ai_tasks t ON t.student_id = s.id
        WHERE s.class_id = ? AND s.status = 'active'
          AND t.created_at >= ?
    """, [class_id, week_start]).fetchone()["cnt"]

    mastery_rows = conn.execute("""
        SELECT m.knowledge_points, m.mastery_level
        FROM mistakes m
        JOIN students s ON s.id = m.student_id
        WHERE s.class_id = ? AND s.status = 'active'
    """, [class_id]).fetchall()

    kp_stats: Dict[str, Dict[str, int]] = {}
    for row in mastery_rows:
        try:
            kps = json.loads(row["knowledge_points"] or "[]")
        except (json.JSONDecodeError, TypeError):
            kps = []
        for kp in kps:
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "mastered": 0}
            kp_stats[kp]["total"] += 1
            if row["mastery_level"] >= 2:
                kp_stats[kp]["mastered"] += 1

    weak_points = []
    for kp, stats in kp_stats.items():
        if stats["total"] >= 2:
            error_rate = 1.0 - (stats["mastered"] / stats["total"])
            weak_points.append({"knowledge_point": kp, "error_rate": round(error_rate, 2),
                                "total": stats["total"], "mastered": stats["mastered"]})
    weak_points.sort(key=lambda x: -x["error_rate"])

    total_mistakes = len(mastery_rows)
    mastered_count = sum(1 for r in mastery_rows if r["mastery_level"] >= 2)
    avg_mastery = round(mastered_count / max(total_mistakes, 1) * 100, 1)

    conn.close()
    return {
        "class_id": class_id,
        "student_count": student_count,
        "active_this_week": active_this_week,
        "avg_mastery_rate": avg_mastery,
        "total_mistakes": total_mistakes,
        "mastered_count": mastered_count,
        "weak_points_top5": weak_points[:5],
    }


# ═══════════════════════════════════════════════════
# Auto-init
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
    print(f"DB path: {DB_PATH}")
    print(f"Today cost: ${get_llm_cost_today():.4f}")
    print(f"Month cost: ${get_llm_cost_this_month():.4f}")
