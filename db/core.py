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

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("WEEKEND_ENGLISH_DB", os.path.join(PROJECT_ROOT, "data.db"))
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
    # Add ease_factor to mistakes (SM-2 个人难度系数，复习间隔随之伸缩)
    if "ease_factor" not in mistake_col_names:
        conn.execute("ALTER TABLE mistakes ADD COLUMN ease_factor REAL DEFAULT 2.5")
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
            ease_factor REAL DEFAULT 2.5,
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

        -- ── L3 学生长期记忆（跨月画像：月度总结刷新，方案生成消费）──
        -- 三层记忆的 L3 层：L1=批改原始记录(practice_records/mistakes)，
        -- L2=周/月报告(analysis_report/weekly_report)，L3=跨月沉淀的
        -- "什么类型的学习者、哪类错因反复出现、哪种讲法有效"。
        CREATE TABLE IF NOT EXISTS student_memory (
            student_id INTEGER PRIMARY KEY,
            memory_summary TEXT DEFAULT '',
            learner_type TEXT DEFAULT '',
            recurring_causes TEXT DEFAULT '[]',
            effective_methods TEXT DEFAULT '[]',
            source_month TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
# Flask g-based helpers (兼容原 app.py 模式)
# ═══════════════════════════════════════════════════

# ── 时区约定（2026-08 统一，勿破坏）─────────────────
# 1. SQL DEFAULT CURRENT_TIMESTAMP 列（各表 created_at 等）存 UTC。
# 2. _now_iso() 写入的列（last_reviewed_at / next_reviewed_at /
#    withdrawn_at 等）存本地时间。
# 3. 业务日/周/月边界（错题归周、月度归集、"今天"成本、防刷每日闸门）
#    一律按本地时间比较：UTC 列必须加 'localtime' 修饰符，如
#    date(created_at, 'localtime') = date('now', 'localtime')；
#    本地列（_now_iso 写入）不得再加，否则双重偏移。
# 4. 调度器/备份新鲜度窗口为 UTC 自洽（datetime.now(timezone.utc) 对
#    backups/ai_tasks.created_at），按第 3 条无关的独立体系。
# 服务器须设 Asia/Shanghai 时区（DEPLOY.md）。

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_current_week_range() -> tuple:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return (monday.isoformat(), sunday.isoformat())


def get_week_start() -> str:
    """Return Monday of current week in ISO format."""
    return (date.today() - timedelta(days=date.today().weekday())).isoformat()

