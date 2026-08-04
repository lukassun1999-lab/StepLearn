import os
import sys

# Make project root importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pytest
from PIL import Image, ImageDraw, ImageFont


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Create a single temporary SQLite database for the whole test session."""
    db_dir = tmp_path_factory.mktemp("weekend_english_tests")
    db_path = str(db_dir / "test_data.db")
    os.environ["WEEKEND_ENGLISH_DB"] = db_path

    # Import db AFTER setting the env var so DB_PATH points to the temp database
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
