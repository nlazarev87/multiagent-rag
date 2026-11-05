"""Grep-level checks for the responsive shell (issue #269 / task 10.1).

Без браузера: проверяем только то, что можно увидеть в исходнике index.html.
"""
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "src" / "web" / "index.html"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def test_media_breakpoints_present():
    text = _html()
    assert "@media" in text
    for width in ("1279.98px", "1079.98px", "899.98px", "719.98px", "559.98px"):
        assert width in text, f"нет брейкпоинта {width}"


def test_columns_are_fluid_not_fixed():
    text = _html()
    assert "clamp(" in text
    assert "minmax(" in text
    assert "--left: 260px" not in text
    assert "--mid: 380px" not in text


def test_body_has_no_horizontal_scroll():
    assert "overflow-x: hidden" in _html()


def test_sash_clamps_to_window_width():
    assert "window.innerWidth" in _html()


def test_dialogs_collapse_into_drawer():
    text = _html()
    assert "drawer" in text
    assert 'id="dialog-toggle"' in text


def test_single_panel_with_tabs_on_mobile():
    text = _html()
    assert "mobile-doc" in text
    assert 'id="mtab-chat"' in text
    assert 'id="mtab-doc"' in text


def test_no_inner_html():
    text = _html()
    assert "innerHTML" not in text
    assert "insertAdjacentHTML" not in text


def test_dark_theme_preserved():
    assert 'body[data-theme="dark"]' in _html()
