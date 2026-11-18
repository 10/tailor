import os

from tailor.traffic_store import BODY_PREVIEW_LIMIT, TrafficStore, body_preview


def test_new_history_is_private(tmp_path):
    path = tmp_path / "history.db"
    old_mask = os.umask(0o022)
    try:
        TrafficStore(path)
    finally:
        os.umask(old_mask)
    assert path.stat().st_mode & 0o077 == 0

    path.chmod(0o640)
    TrafficStore(path)
    assert path.stat().st_mode & 0o777 == 0o640


def test_preview_reports_decoded_length_for_multibyte_text():
    text = "é" * BODY_PREVIEW_LIMIT
    assert body_preview(text) == text
    assert body_preview(text + "é") == f"{text}\n... [{len(text) + 1} characters total]"
