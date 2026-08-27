import os
import sys
import tempfile

# Make project root importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 关键：必须在任何测试模块 import db 之前设置环境变量。
# pytest 收集阶段会执行各测试文件顶部的 import db —— 那时 fixture 尚未运行，
# 若此刻未设置 WEEKEND_ENGLISH_DB，db.DB_PATH 会绑定到真实 data.db，
# 测试期间所有不带显式 db_path 的内部调用将读写生产库（历史踩坑：真实库
# 曾因此混入上百条"测试学生"）。conftest 的加载先于测试模块收集，在此收口。
_TEST_DB_PATH = os.path.join(
    tempfile.mkdtemp(prefix="steplearn_tests_"), "test_data.db")
os.environ["WEEKEND_ENGLISH_DB"] = _TEST_DB_PATH

import pytest
from PIL import Image, ImageDraw, ImageFont


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Create a single temporary SQLite database for the whole test session."""
    db_path = os.environ["WEEKEND_ENGLISH_DB"]

    import db

    db.init_db(db_path)
    return db_path


@pytest.fixture
def client(test_db_path):
    """Flask test client using the temporary database."""
    import app

    with app.app.test_client() as c:
        yield c


@pytest.fixture
def sample_student(test_db_path):
    """Create a sample active student."""
    import db

    sid = db.create_student({
        "name": "测试学生",
        "grade": "高二",
        "school_type": "住校",
        "english_score": 100,
        "target_score": 130,
        "plan": "trial",
    })
    return sid


@pytest.fixture(scope="session")
def admin_user(test_db_path):
    """Create a sample admin user."""
    import db

    db.create_admin_user("admin", "password", "admin", db_path=test_db_path)
    user = db.get_admin_user("admin", db_path=test_db_path)
    return user["id"]


@pytest.fixture(scope="session")
def teacher_user(test_db_path):
    """Create a sample teacher user."""
    import db

    db.create_admin_user("teacher1", "password", "teacher", db_path=test_db_path)
    user = db.get_admin_user("teacher1", db_path=test_db_path)
    return user["id"]


@pytest.fixture
def demo_mode(monkeypatch):
    """Force the LLM layer into demo mode (no real API calls)."""
    import llm

    monkeypatch.setattr(llm, "HAS_API_KEY", False)
    monkeypatch.setattr(llm, "BACKEND", "demo")
    monkeypatch.setattr(llm, "CACHE_ENABLED", False)
    monkeypatch.setattr(llm, "VISION_MODEL", "kimi-k2.6")


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """每个测试前复位 web.shared 里的进程内全局计数（限流器等），
    防止跨测试的状态污染导致偶发失败。"""
    import web.shared as ws
    ws._reset_code_rate_limit()
    yield
    ws._reset_code_rate_limit()


@pytest.fixture
def frozen_past_saturday():
    """冻结 Python 侧时间到过去的周六（2000-01-01），调度器周六窗口逻辑全周可测。

    背景：_saturday_start_utc 在周一~周五会算出"本周六（未来）"，测试直调
    _trigger_weekly_reports 时窗口去重失效 → 任务重复创建、断言随星期数漂移。
    冻结到过去周六后：since 窗口恒在过去，而 SQLite 的 CURRENT_TIMESTAMP
    是真实时钟（恒晚于 2000 年），"窗口内已建任务命中去重"天然成立。
    只冻结 datetime.now/today，不影响数据库时间戳。
    """
    from freezegun import freeze_time

    with freeze_time("2000-01-01 09:00:00"):  # 2000-01-01 是周六
        yield


@pytest.fixture
def disable_cache(monkeypatch):
    """Disable the LLM response cache."""
    import llm

    monkeypatch.setattr(llm, "CACHE_ENABLED", False)


@pytest.fixture
def test_image(tmp_path):
    """Create a small test image with English text."""
    image_path = tmp_path / "test_image.png"
    img = Image.new("RGB", (600, 120), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except Exception:
        font = ImageFont.load_default()
    draw.text(
        (20, 40),
        "1. What is the capital of France? A. Paris",
        fill="black",
        font=font,
    )
    img.save(image_path)
    return str(image_path)
