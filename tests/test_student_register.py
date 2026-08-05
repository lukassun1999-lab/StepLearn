"""学生注册流程测试：年级 + 教材版本选择。"""


def _register_payload(**overrides):
    payload = {
        "name": "测试注册",
        "phone": "13800138000",
        "password": "secret123",
        "grade": "初二",
        "textbook_version": "人教版",
    }
    payload.update(overrides)
    return payload


# ── db 层 ──────────────────────────────────────────

def test_register_student_saves_grade_and_textbook(test_db_path):
    import db

    sid = db.register_student(
        phone="13800138001",
        password_hash="hash",
        name="张三",
        school_id=None,
        class_id=None,
        grade="初三",
        textbook_version="外研社版",
        db_path=test_db_path,
    )
    row = db.get_student(sid)
    assert row["grade"] == "初三"
    assert row["textbook_version"] == "外研社版"


def test_register_student_defaults_grade_when_missing(test_db_path):
    import db

    sid = db.register_student(
        phone="13800138002",
        password_hash="hash",
        name="李四",
        school_id=None,
        class_id=None,
        db_path=test_db_path,
    )
    row = db.get_student(sid)
    assert row["grade"] == "高二"
    assert row["textbook_version"] is None


# ── API 层 ─────────────────────────────────────────

def test_api_register_with_grade_and_textbook(client, test_db_path):
    import db

    r = client.post("/api/register", json=_register_payload())
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True

    row = db.get_student(d["student_id"])
    assert row["grade"] == "初二"
    assert row["textbook_version"] == "人教版"
    assert row["access_code"]  # 注册后 redirect 到 /s/<access_code>
    assert "/s/" in d["redirect"]


def test_api_register_requires_grade(client):
    r = client.post("/api/register", json=_register_payload(grade=""))
    assert r.status_code == 400
    assert "年级" in r.get_json()["error"]


def test_api_register_requires_valid_textbook(client):
    r = client.post("/api/register", json=_register_payload(textbook_version="外研版"))
    assert r.status_code == 400
    assert "教材版本" in r.get_json()["error"]


def test_api_register_class_grade_overrides_form(client, test_db_path):
    import db

    school_id = db.create_school("测试中学", db_path=test_db_path)
    cls = db.create_class(school_id, "初二3班", grade="初二", db_path=test_db_path)
    class_code = cls["class_code"]

    r = client.post("/api/register", json=_register_payload(
        phone="13800138003",
        class_code=class_code,
        grade="高一",  # 表单选了高一，但班级是初二，应以班级为准
        textbook_version="北师大版",
    ))
    assert r.status_code == 200
    d = r.get_json()
    row = db.get_student(d["student_id"])
    assert row["grade"] == "初二"
    assert row["textbook_version"] == "北师大版"
    assert row["class_id"] == cls["id"]


def test_api_register_duplicate_phone(client):
    client.post("/api/register", json=_register_payload())
    r = client.post("/api/register", json=_register_payload(phone="13800138000"))
    assert r.status_code == 409
