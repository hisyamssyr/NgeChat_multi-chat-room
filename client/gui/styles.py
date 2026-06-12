# client/gui/styles.py
# --------------------
# Premium Modern Dark Theme QSS stylesheet and colour constants for the GUI.
# Inspired by modern chat apps (Discord / Slack) using Slate & Indigo palettes.

# ── Colour palette (also used in Python code for dynamic HTML) ────────────────

BG_DEEP     = "#0F172A"    # slate-900: main window background
BG_SURFACE  = "#1E293B"    # slate-800: panels, sidebars, dialogs
BG_ELEVATED = "#334155"    # slate-700: inputs, list items (hover), cards
BORDER      = "#475569"    # slate-600: all borders
BLUE        = "#6366F1"    # indigo-500: accent — links, selection, active room
GREEN       = "#10B981"    # emerald-500: success, online indicator
RED         = "#EF4444"    # red-500: danger, error, logout button
AMBER       = "#F59E0B"    # amber-500: warning, unread badge
PURPLE      = "#8B5CF6"    # violet-500: private messages
TEXT        = "#F8FAFC"    # slate-50: primary text
TEXT_MUTED  = "#94A3B8"    # slate-400: secondary text, timestamps, labels
OWN_MSG_BG  = "#3730A3"    # indigo-800: own broadcast message background
PM_BG       = "#4C1D95"    # violet-900: incoming private message background
NOTIF_COLOR = "#64748B"    # slate-500: system notification text

# ── QSS stylesheet ────────────────────────────────────────────────────────────

DARK_THEME = f"""

/* ── Base ─────────────────────────────────────────────────────────── */

QMainWindow, QDialog {{
    background-color: {BG_DEEP};
}}

QWidget {{
    background-color: {BG_DEEP};
    color: {TEXT};
    font-family: "Inter", "Segoe UI", "SF Pro Display", sans-serif;
    font-size: 14px;
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
    background-color: {BG_DEEP};
    border-top: 1px solid {BORDER};
}}

QFrame#login_card {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}

/* ── Labels ───────────────────────────────────────────────────────── */

QLabel {{
    background-color: transparent;
}}

QLabel#app_title {{
    color: {TEXT};
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 0.5px;
}}

QLabel#username_label {{
    color: {TEXT_MUTED};
    font-weight: bold;
    font-size: 14px;
}}

QLabel#section_header {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1.5px;
    padding: 14px 16px 6px 16px;
    background-color: transparent;
}}

QLabel#chat_room_name {{
    color: {TEXT};
    font-size: 16px;
    font-weight: bold;
    padding: 0px 14px;
}}

QLabel#status_label {{
    color: {TEXT_MUTED};
    font-size: 13px;
    padding: 4px 0px;
}}

QLabel#error_label {{
    color: {RED};
    font-size: 13px;
    padding: 4px 0px;
}}

QLabel#info_label {{
    color: {GREEN};
    font-size: 13px;
    padding: 4px 0px;
}}

QLabel#login_title {{
    color: {TEXT};
    font-size: 24px;
    font-weight: 800;
}}

QLabel#login_subtitle {{
    color: {TEXT_MUTED};
    font-size: 14px;
}}

QLabel#field_label {{
    color: {TEXT_MUTED};
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}

/* ── Buttons ──────────────────────────────────────────────────────── */

QPushButton {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    min-height: 32px;
}}

QPushButton:hover {{
    background-color: #475569; /* slate-600 */
}}

QPushButton:pressed {{
    background-color: {BORDER};
}}

QPushButton#send_btn {{
    background-color: {BLUE};
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 24px;
    font-weight: bold;
    font-size: 14px;
    min-width: 80px;
}}

QPushButton#send_btn:hover {{
    background-color: #4F46E5; /* indigo-600 */
}}

QPushButton#send_btn:pressed {{
    background-color: #4338CA; /* indigo-700 */
}}

QPushButton#login_btn {{
    background-color: {BLUE};
    color: #ffffff;
    border: none;
    border-radius: 10px;
    padding: 12px 0px;
    font-weight: bold;
    font-size: 14px;
}}

QPushButton#login_btn:hover {{
    background-color: #4F46E5;
}}

QPushButton#register_btn {{
    background-color: transparent;
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 12px 0px;
    font-weight: 600;
    font-size: 14px;
}}

QPushButton#register_btn:hover {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
}}

QPushButton#danger_btn {{
    background-color: transparent;
    color: {RED};
    border: 1px solid {RED};
    border-radius: 8px;
    padding: 6px 16px;
    font-weight: 600;
}}

QPushButton#danger_btn:hover {{
    background-color: {RED};
    color: #ffffff;
}}

QPushButton#accent_btn {{
    background-color: transparent;
    color: {BLUE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}}

QPushButton#accent_btn:hover {{
    background-color: {BG_ELEVATED};
    border-color: {BLUE};
}}

QPushButton#icon_btn {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px;
    color: {TEXT_MUTED};
    font-size: 16px;
}}

QPushButton#icon_btn:hover {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
}}

QPushButton:disabled {{
    background-color: {BG_SURFACE};
    color: {BORDER};
    border-color: {BG_SURFACE};
}}

/* ── Input fields ─────────────────────────────────────────────────── */

QLineEdit {{
    background-color: {BG_DEEP};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 14px;
    selection-background-color: {BLUE};
}}

QLineEdit:focus {{
    border-color: {BLUE};
    background-color: #0B1120;
}}

QLineEdit#server_input {{
    font-family: "Consolas", "Courier New", monospace;
    font-size: 13px;
}}

/* ── Chat / message area ──────────────────────────────────────────── */

QTextBrowser#chat_area {{
    background-color: {BG_DEEP};
    color: {TEXT};
    border: none;
    padding: 16px 24px;
    font-family: "Inter", "Segoe UI", Arial, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    selection-background-color: {BLUE};
}}

QTextEdit#msg_input {{
    background-color: {BG_SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 10px 16px;
    font-size: 14px;
    selection-background-color: {BLUE};
}}

QTextEdit#msg_input:focus {{
    border-color: {BLUE};
}}

/* ── List widgets ─────────────────────────────────────────────────── */

QListWidget {{
    background-color: transparent;
    border: none;
    outline: none;
    padding: 8px;
}}

QListWidget::item {{
    padding: 10px 14px;
    border-radius: 8px;
    color: {TEXT_MUTED};
    margin: 2px 0px;
    font-size: 14px;
    font-weight: 500;
}}

QListWidget::item:hover {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
}}

QListWidget::item:selected {{
    background-color: {BLUE};
    color: #ffffff;
    font-weight: 700;
}}

/* ── Scrollbar ────────────────────────────────────────────────────── */

QScrollBar:vertical {{
    background-color: transparent;
    width: 10px;
    border: none;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {BG_ELEVATED};
    border-radius: 5px;
    min-height: 30px;
    margin: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {BORDER};
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
    font-size: 12px;
    padding: 0px 12px;
}}

QStatusBar QLabel {{
    color: {TEXT_MUTED};
    padding: 4px 6px;
}}

/* ── Tooltips ─────────────────────────────────────────────────────── */

QToolTip {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
}}

/* ── Splitter ─────────────────────────────────────────────────────── */

QSplitter::handle {{
    background-color: transparent;
    width: 2px;
}}

QSplitter::handle:hover {{
    background-color: {BORDER};
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
    # Apply the dark QSS theme to a QApplication instance.
    app.setStyleSheet(DARK_THEME)
