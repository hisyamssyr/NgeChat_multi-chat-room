# GUI entry point for the Multi-Chat Room application.

import sys
import os
import argparse
import logging

# Ensure project root is on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

from client.gui.styles import apply_dark_theme
from client.gui.login_window import LoginWindow
from client.gui.main_window import MainWindow

# Suppress networking debug noise on the GUI client.
logging.basicConfig(level=logging.WARNING)

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-Chat Room — GUI Client",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host", default=os.environ.get("CHAT_HOST", "127.0.0.1"),
        help="Default server host (pre-fills the login form)"
    )
    parser.add_argument(
        "--port", default=int(os.environ.get("CHAT_PORT", "9090")), type=int,
        help="Default server port (pre-fills the login form)"
    )
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Multi-Chat Room")
    app.setOrganizationName("NetworkProgramming")

    # Use Fusion style as the base (works well on Windows, Linux, macOS).
    app.setStyle("Fusion")

    # Apply our dark QSS theme on top.
    apply_dark_theme(app)

    # Set a readable default font.
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    login_win = LoginWindow()

    # Pre-fill host/port from CLI args.
    login_win._host_input.setText(args.host)
    login_win._port_input.setText(str(args.port))

    result = login_win.exec()

    if result != QDialog.DialogCode.Accepted:
        # User closed the login dialog — exit cleanly.
        sys.exit(0)

    network  = login_win.network_client
    username = login_win.username

    main_win = MainWindow(network=network, username=username)
    main_win.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
