"""Dark theme QSS stylesheet and colour constants for the GUI."""

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

DARK_THEME = f"""QMainWindow, QDialog {{"""

def apply_dark_theme(app) -> None:
    """Apply the dark QSS theme to a QApplication instance."""
    app.setStyleSheet(DARK_THEME)
