import pytest


def test_run_ocr_vision_demo_returns_vision_backend(
    monkeypatch, test_image, test_db_path, demo_mode
):
    """Vision backend in demo mode should return placeholder text."""
    import ocr_service as sb

    monkeypatch.setattr(sb, "OCR_BACKEND", "vision")

    result = sb.run_ocr(test_image)

    assert result["backend"] == "vision"
    assert "[DEMO]" in result["text"]
    assert result["confidence"] > 0


def test_run_ocr_auto_prefers_vision_when_available(
    monkeypatch, test_image, test_db_path, demo_mode
):
    """Auto backend should use vision when it returns sufficient text."""
    import ocr_service as sb

    monkeypatch.setattr(sb, "OCR_BACKEND", "auto")

    result = sb.run_ocr(test_image)

    assert result["backend"] == "vision"
    assert result.get("vision_fallback_reason") is None


def test_run_ocr_auto_falls_back_to_tesseract_on_insufficient_vision_text(
    monkeypatch, test_image, test_db_path
):
    """Auto backend should fall back to Tesseract if vision returns too little text."""
    import ocr_service as sb

    monkeypatch.setattr(sb, "OCR_BACKEND", "auto")
    monkeypatch.setattr(
        sb,
        "run_ocr_multimodal",
        lambda image_path, task_id=None: {
            "text": "",
            "confidence": 0.0,
            "words": [],
            "backend": "vision",
        },
    )
    monkeypatch.setattr(
        sb,
        "_run_tesseract_ocr",
        lambda image_path, lang="chi_sim+eng": {
            "text": "tesseract fallback text",
            "confidence": 0.9,
            "words": [],
        },
    )

    result = sb.run_ocr(test_image)

    assert result["backend"] == "tesseract"
    assert result["text"] == "tesseract fallback text"
    assert "vision_fallback_reason" in result


def test_run_ocr_tesseract_forced_uses_tesseract(
    monkeypatch, test_image, test_db_path
):
    """Forcing tesseract backend should skip vision entirely."""
    import ocr_service as sb

    monkeypatch.setattr(sb, "OCR_BACKEND", "tesseract")
    monkeypatch.setattr(
        sb,
        "_run_tesseract_ocr",
        lambda image_path, lang="chi_sim+eng": {
            "text": "forced tesseract",
            "confidence": 0.8,
            "words": ["forced"],
        },
    )

    result = sb.run_ocr(test_image)

    assert result["backend"] == "tesseract"
    assert result["text"] == "forced tesseract"


def test_run_ocr_vision_demo_logs_usage_to_database(
    monkeypatch, test_image, test_db_path, demo_mode
):
    """Demo-mode OCR usage should be written to llm_usage_log."""
    import ocr_service as sb
    import db

    monkeypatch.setattr(sb, "OCR_BACKEND", "vision")

    sb.run_ocr(test_image, task_id=999)

    conn = db.get_connection(test_db_path)
    rows = conn.execute(
        "SELECT task_id, call_type, model, cached FROM llm_usage_log WHERE task_id = ?",
        (999,),
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0]["call_type"] == "ocr"
    assert rows[0]["model"] == "kimi-k2.6"
    assert rows[0]["cached"] == 1


def test_call_vision_resizes_oversized_image(
    monkeypatch, tmp_path, demo_mode
):
    """Large images should be resized before being sent to the vision API."""
    import llm
    from PIL import Image
    import random

    # Create a noisy image > 2 MB
    image_path = tmp_path / "large.png"
    img = Image.new("RGB", (2000, 2000), color="white")
    pixels = [(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)) for _ in range(2000 * 2000)]
    img.putdata(pixels)
    img.save(image_path)

    client = llm.LLMClient(model="kimi-k2.6")
    result = client.call_vision(str(image_path), "识别文字")

    assert "_raw_text" in result
    assert "[DEMO]" in result["_raw_text"]


def test_api_status_includes_ocr_fields(test_db_path):
    """The status endpoint should expose OCR backend configuration."""
    import app

    with app.app.test_client() as client:
        # Login is required; we patch the decorator for this test
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user_role"] = "admin"

        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.get_json()
        assert "ocr_backend" in data
        assert "vision_model" in data
