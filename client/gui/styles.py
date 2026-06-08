"""
client/gui/styles.py
--------------------
Dark theme QSS stylesheet and colour constants for the GUI.

Inspired by GitHub Dark — dark navy tones with blue accent, green for
success, and red for danger.  Applied once to the QApplication at startup.
"""

# ── Colour palette (also used in Python code for dynamic HTML) ────────────────

BG_DEEP     = "#0d1117"    # main window background
BG_SURFACE  = "#161b22"    # panels, sidebars, dialogs
BG_ELEVATED = "#21262d"    # inputs, list items (hover), cards
BORDER      = "#30363d"    # all borders
BLUE        = "#58a6ff"    # accent — links, selection, active room
GREEN       = "#3fb950"    # success, online indicator, own username
RED         = "#f85149"    # danger, error, logout button
AMBER       = "#e3b341"    # warning, unread badge
PURPLE      = "#a78bfa"    # private messages
TEXT        = "#c9d1d9"    # primary text
TEXT_MUTED  = "#8b949e"    # secondary text, timestamps, labels
OWN_MSG_BG  = "#1a3a5c"    # own broadcast message background
PM_BG       = "#2d1b4e"    # incoming private message background
NOTIF_COLOR = "#484f58"    # system notification text

# ── QSS stylesheet ────────────────────────────────────────────────────────────

DARK_THEME = f"""

/* ── Base ─────────────────────────────────────────────────────────── */

QMainWindow, QDialog {{
    background-color: {BG_DEEP};
}}

QWidget {{
    background-color: {BG_DEEP};
    color: {TEXT};
    font-family: "Segoe UI", "SF Pro Display", Arial, sans-serif;
    font-size: 13px;
}}

/* ── Panels ───────────────────────────────────────────────────────── */

QFrame#left_panel {{
    background-color: {BG_SURFACE};
    border-right: 1px solid {BORDER};
}}

QFrame#right_panel {{
    background-color: {BG_SURFACE};
    border-left: 1px solid {BORDER};
}}

QFrame#chat_frame {{
    background-color: {BG_DEEP};
}}

QFrame#title_bar {{
    background-color: {BG_SURFACE};
    border-bottom: 1px solid {BORDER};
}}

QFrame#chat_header_bar {{
    background-color: {BG_SURFACE};
    border-bottom: 1px solid {BORDER};
}}

QFrame#input_bar {{
    background-color: {BG_SURFACE};
    border-top: 1px solid {BORDER};
}}

QFrame#login_card {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}

/* ── Labels ───────────────────────────────────────────────────────── */

QLabel {{
    background-color: transparent;
}}

QLabel#app_title {{
    color: {BLUE};
    font-size: 17px;
    font-weight: bold;
    letter-spacing: 0.5px;
}}

QLabel#username_label {{
    color: {GREEN};
    font-weight: bold;
    font-size: 13px;
}}

QLabel#section_header {{
    color: {TEXT_MUTED};
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 1.5px;
    padding: 10px 14px 4px 14px;
    background-color: transparent;
}}

QLabel#chat_room_name {{
    color: {TEXT};
    font-size: 14px;
    font-weight: bold;
    padding: 0px 14px;
}}

QLabel#status_label {{
    color: {TEXT_MUTED};
    font-size: 12px;
    padding: 4px 0px;
}}

QLabel#error_label {{
    color: {RED};
    font-size: 12px;
    padding: 4px 0px;
}}

QLabel#info_label {{
    color: {GREEN};
    font-size: 12px;
    padding: 4px 0px;
}}

QLabel#login_title {{
    color: {BLUE};
    font-size: 22px;
    font-weight: bold;
}}

QLabel#login_subtitle {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

QLabel#field_label {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}

/* ── Buttons ──────────────────────────────────────────────────────── */

QPushButton {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
    min-height: 28px;
}}

QPushButton:hover {{
    background-color: #2d333b;
    border-color: {BLUE};
    color: #ffffff;
}}

QPushButton:pressed {{
    background-color: {BG_SURFACE};
}}

QPushButton#send_btn {{
    background-color: #238636;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 22px;
    font-weight: bold;
    font-size: 13px;
    min-width: 80px;
}}

QPushButton#send_btn:hover {{
    background-color: #2ea043;
}}

QPushButton#send_btn:pressed {{
    background-color: #1a7f37;
}}

QPushButton#login_btn {{
    background-color: #1f6feb;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 9px 0px;
    font-weight: bold;
    font-size: 13px;
}}

QPushButton#login_btn:hover {{
    background-color: #388bfd;
}}

QPushButton#register_btn {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 9px 0px;
    font-size: 13px;
}}

QPushButton#register_btn:hover {{
    background-color: #2d333b;
    border-color: {BLUE};
}}

QPushButton#danger_btn {{
    background-color: #da3633;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}}

QPushButton#danger_btn:hover {{
    background-color: {RED};
}}

QPushButton#accent_btn {{
    background-color: #1f6feb;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}}

QPushButton#accent_btn:hover {{
    background-color: #388bfd;
}}

QPushButton#icon_btn {{
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    color: {TEXT_MUTED};
    font-size: 16px;
    min-width: 36px;
    max-width: 36px;
    min-height: 32px;
    max-height: 32px;
}}

QPushButton#icon_btn:hover {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
    border-color: {BLUE};
}}

QPushButton:disabled {{
    background-color: {BG_SURFACE};
    color: {NOTIF_COLOR};
    border-color: {BG_ELEVATED};
}}

/* ── Input fields ─────────────────────────────────────────────────── */

QLineEdit {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 13px;
    selection-background-color: #264f78;
}}

QLineEdit:focus {{
    border-color: {BLUE};
    background-color: #1c2128;
}}

QLineEdit#server_input {{
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
}}

/* ── Chat / message area ──────────────────────────────────────────── */

QTextBrowser#chat_area {{
    background-color: {BG_DEEP};
    color: {TEXT};
    border: none;
    padding: 8px 12px;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
    line-height: 1.5;
    selection-background-color: #264f78;
}}

QTextEdit#msg_input {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: #264f78;
}}

QTextEdit#msg_input:focus {{
    border-color: {BLUE};
    background-color: #1c2128;
}}

/* ── List widgets ─────────────────────────────────────────────────── */

QListWidget {{
    background-color: transparent;
    border: none;
    outline: none;
    padding: 4px;
}}

QListWidget::item {{
    padding: 7px 12px;
    border-radius: 6px;
    color: {TEXT_MUTED};
    margin: 1px 0px;
    font-size: 13px;
}}

QListWidget::item:hover {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
}}

QListWidget::item:selected {{
    background-color: #1f3a5f;
    color: {BLUE};
    font-weight: 600;
}}

/* ── Scrollbar ────────────────────────────────────────────────────── */

QScrollBar:vertical {{
    background-color: transparent;
    width: 8px;
    border: none;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {TEXT_MUTED};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
}}

/* ── Status bar ───────────────────────────────────────────────────── */

QStatusBar {{
    background-color: {BG_SURFACE};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER};
    font-size: 11px;
    padding: 0px 8px;
}}

QStatusBar QLabel {{
    color: {TEXT_MUTED};
    padding: 2px 4px;
}}

/* ── Tooltips ─────────────────────────────────────────────────────── */

QToolTip {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}}

/* ── Splitter ─────────────────────────────────────────────────────── */

QSplitter::handle {{
    background-color: {BORDER};
    width: 1px;
}}

QSplitter::handle:hover {{
    background-color: {BLUE};
}}

/* ── Message box ──────────────────────────────────────────────────── */

QMessageBox {{
    background-color: {BG_SURFACE};
}}

QMessageBox QLabel {{
    color: {TEXT};
}}

QMessageBox QPushButton {{
    min-width: 80px;
}}
"""


def apply_dark_theme(app) -> None:
    """Apply the dark QSS theme to a QApplication instance."""
    app.setStyleSheet(DARK_THEME)
