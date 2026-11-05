"""Grep-level checks for the responsive shell and admin (issues #269-#274).

Без браузера: проверяем только то, что видно в исходнике src/web/index.html.
"""
import re
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "src" / "web" / "index.html"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _rule(text, needle, last=False):
    """Вернуть содержимое CSS-блока {…}, идущего за needle (последним, если last)."""
    start = text.rfind(needle) if last else text.find(needle)
    if start < 0:
        return ""
    open_brace = text.find("{", start)
    close_brace = text.find("}", open_brace)
    if open_brace < 0 or close_brace < 0:
        return ""
    return text[open_brace:close_brace]


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


def test_table_card_scrolls_not_clips():
    block = _rule(_html(), ".table-card")
    assert "overflow-x: auto" in block
    assert "overflow: hidden" not in block


def test_kb_matrix_scrolls_and_sticks_first_column():
    text = _html()
    scroll = _rule(text, ".kb-scroll")
    assert "overflow-x: auto" in scroll
    first_col = _rule(text, ".kb-matrix th:first-child")
    assert "position: sticky" in first_col
    assert "left: 0" in first_col


def test_admin_nav_becomes_ribbon_below_900():
    text = _html()
    assert "@media (max-width: 899.98px)" in text
    nav = _rule(text, ".admin-nav {", last=True)
    assert "flex-direction: row" in nav
    assert "overflow-x: auto" in nav


def test_no_fixed_window_min_width():
    text = _html()
    for value in re.findall(r"min-width: ([^;]+);", text):
        value = value.strip()
        assert value == "0" or value.endswith("rem"), f"фиксированный min-width: {value}"


def test_no_inner_html():
    text = _html()
    assert "innerHTML" not in text
    assert "insertAdjacentHTML" not in text


def test_dark_theme_preserved():
    assert 'body[data-theme="dark"]' in _html()
