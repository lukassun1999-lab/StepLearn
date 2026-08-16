# -*- coding: utf-8 -*-
"""判分归一化 + 练习防刷 + 一键掌握移除 回归测试（第 2 周提交 1）。

覆盖：
- normalize_answer：全角/多选乱序/分隔符/首尾标点/空白
- is_answer_correct：空答案判错、大小写无关
- 提交端点防刷：当日二次提交不计分、30 秒冷却
- /api/mistakes/<id>/master 学生码 403、staff 可用
- 家庭端页面不再渲染「已掌握」按钮
"""

from domain.grading import is_answer_correct, normalize_answer


# ── 归一化函数 ──────────────────────────────────────

def test_normalize_fullwidth_letters():
    assert normalize_answer("Ａ") == "A"
    assert normalize_answer("ｂ") == "B"
    assert is_answer_correct("Ａ", "a")


def test_normalize_multiselect_order_insensitive():
    # 含分隔符的 A-F 字母组合：集合比较，顺序无关
    assert normalize_answer("A,B") == normalize_answer("AB")
    assert normalize_answer("a、b") == normalize_answer("B，A")
    assert is_answer_correct("C,A", "AC")
    # 无分隔符且无题型标志：按字面比较（防 DAB/BAD 类单词误判）
    assert not is_answer_correct("BA", "AB")


def test_normalize_separators():
    assert normalize_answer("A, B") == normalize_answer("AB")
    assert normalize_answer("A；B") == normalize_answer("A,B")


def test_normalize_word_answer_punctuation_and_space():
    # 单词/短语答案：内部空格折叠、首尾标点去除、弯撇号统一；
    # 单词（含 A-F 外字母）不排序，避免变位词误判
    assert normalize_answer(" went .") == "WENT"
    assert normalize_answer("New York") == "NEW YORK"
    assert normalize_answer("new  york") == "NEW YORK"
    assert is_answer_correct("Tom's", "TOM’S")
    assert not is_answer_correct("NWET", "went")  # 变位词不误判
    assert not is_answer_correct("DAB", "bad")    # A-F 内单词也不排序


def test_multiselect_explicit_flag():
    # 题型显式多选：任意字母组合顺序无关（可超 A-F 范围）
    assert is_answer_correct("ba", "AB", multiselect=True)
    assert is_answer_correct("G,A", "ag", multiselect=True)
    assert not is_answer_correct("AB", "AC", multiselect=True)


def test_normalize_edge_quotes():
    # 首尾引号去除（中文引号 NFKC 不变，靠 _EDGE_PUNCT）
    assert normalize_answer("“hello”") == "HELLO"
    assert is_answer_correct("‘went’", "went")


def test_normalize_empty():
    assert normalize_answer(None) == ""
    assert normalize_answer("") == ""
    assert not is_answer_correct("", "A")
    assert not is_answer_correct("A", "")
    assert not is_answer_correct(None, None)


def test_single_letter_not_sorted_wrongly():
    assert normalize_answer("a") == "A"
    assert is_answer_correct("b", "B")


def test_numeric_answers():
    # 数字/日期类答案：全角数字、空格
    assert is_answer_correct("１９９８", "1998")
    assert is_answer_correct("June 5", "june  5")


# ── 提交端点防刷 ────────────────────────────────────

def _make_practice_question(test_db_path, student_id):
    import db
    mid = db.add_mistake(
        student_id, question="Choose the correct form: He ___ (go) home.",
        user_answer="go", correct_answer="went",
        question_type="单项选择", db_path=test_db_path)
    conn = db.get_connection(test_db_path)
    conn.execute(
        "INSERT INTO questions (question_text, question_type, correct_answer, "
        "explanation, knowledge_points, difficulty, enabled, source_mistake_id) "
        "VALUES ('Choose the correct form: He ___ (go) home.', '单项选择', 'went', "
        "'过去式', '[]', 2, 1, ?)", [mid])
    qid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return mid, qid


def test_submit_counts_only_first_per_day(client, sample_student, test_db_path):
    import db
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    mid, qid = _make_practice_question(test_db_path, sample_student)

    # 第一次提交（答错）→ 计分
    r = client.post(f"/api/public/{code}/practice/submit",
                    json={"question_id": qid, "answer": "go"})
    assert r.status_code == 200
    assert r.get_json()["is_correct"] is False

    # 马上用正确答案重交 → 反馈正确但不得计入（连对应仍为 0）
    r = client.post(f"/api/public/{code}/practice/submit",
                    json={"question_id": qid, "answer": "went"})
    body = r.get_json()
    assert body["is_correct"] is True  # 判分归一化正确判定
    m = db.get_mistake(mid, db_path=test_db_path)
    assert m["consecutive_correct"] == 0  # 防刷：二次提交未计分

    # 全天只有一条练习记录
    conn = db.get_connection(test_db_path)
    n = conn.execute("SELECT COUNT(*) FROM practice_records WHERE mistake_id = ?",
                     [mid]).fetchone()[0]
    conn.close()
    assert n == 1


def test_submit_cooldown_blocks_rapid_fire(client, sample_student, test_db_path):
    import db
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    mid, qid = _make_practice_question(test_db_path, sample_student)

    # 30 秒内连交两次（第一次计分后第二次被冷却拦截，不新增记录）
    client.post(f"/api/public/{code}/practice/submit",
                json={"question_id": qid, "answer": "went"})
    client.post(f"/api/public/{code}/practice/submit",
                json={"question_id": qid, "answer": "went"})
    conn = db.get_connection(test_db_path)
    n = conn.execute("SELECT COUNT(*) FROM practice_records WHERE mistake_id = ?",
                     [mid]).fetchone()[0]
    conn.close()
    assert n == 1


def test_submit_fullwidth_answer_graded_correct(client, sample_student, test_db_path):
    import db
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    mid, qid = _make_practice_question(test_db_path, sample_student)
    # 全角字母 + 引号包裹，仍应判对
    r = client.post(f"/api/public/{code}/practice/submit",
                    json={"question_id": qid, "answer": "ＷＥＮＴ"})
    assert r.get_json()["is_correct"] is True


# ── 一键掌握移除 ────────────────────────────────────

def test_master_endpoint_rejects_access_code(client, sample_student, test_db_path):
    import db
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    mid = db.add_mistake(sample_student, question="q", correct_answer="A",
                         db_path=test_db_path)
    # 学生码（原家庭端路径）不再放行：匿名 → 401
    r = client.post(f"/api/mistakes/{mid}/master",
                    json={"access_code": code})
    assert r.status_code == 401
    # 学生登录态 → 403（staff_required）
    with client.session_transaction() as sess:
        sess["user_id"] = sample_student
        sess["user_role"] = "student"
        sess["user_name"] = "s"
    r = client.post(f"/api/mistakes/{mid}/master")
    assert r.status_code == 403
    # 掌握度未变
    m = db.get_mistake(mid, db_path=test_db_path)
    assert m["consecutive_correct"] == 0


def test_master_endpoint_staff_still_works(client, sample_student, teacher_user,
                                           test_db_path):
    import db
    mid = db.add_mistake(sample_student, question="q", correct_answer="A",
                         db_path=test_db_path)
    with client.session_transaction() as sess:
        sess["user_id"] = teacher_user
        sess["user_role"] = "teacher"
        sess["user_name"] = "t"
    r = client.post(f"/api/mistakes/{mid}/master")
    assert r.status_code == 200
    m = db.get_mistake(mid, db_path=test_db_path)
    assert m["consecutive_correct"] == 2


def test_family_page_no_master_button(client, sample_student, test_db_path):
    import db
    code = db.get_student(sample_student, db_path=test_db_path)["access_code"]
    r = client.get(f"/s/{code}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "已掌握</button>" not in html
    assert "masterMistake" not in html
    assert "去练习" in html  # 练习入口保留
