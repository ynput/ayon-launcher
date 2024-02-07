import os
import sys
import json

from qtpy import QtWidgets, QtCore, QtGui

from ayon_common.resources import (
    get_icon_path,
    load_stylesheet,
)
from ayon_common.ui_utils import get_qt_app


class InvalidCredentialsWindow(QtWidgets.QDialog):
    default_width = 420
    default_height = 170

    def __init__(self, message, *args, **kwargs):
        super().__init__(*args, **kwargs)

        icon_path = get_icon_path()
        icon = QtGui.QIcon(icon_path)
        self.setWindowIcon(icon)
        self.setWindowTitle("Invalid credentials")

        info_widget = QtWidgets.QWidget(self)

        message_label = url_cred_sep = None
        if message:
            # --- Custom message ---
            message_label = QtWidgets.QLabel(message, info_widget)
            message_label.setWordWrap(True)
            message_label.setTextInteractionFlags(
                QtCore.Qt.TextBrowserInteraction
            )

            # --- URL separator ---
            url_cred_sep = QtWidgets.QFrame(info_widget)
            url_cred_sep.setObjectName("Separator")
            url_cred_sep.setMinimumHeight(2)
            url_cred_sep.setMaximumHeight(2)

        common_label = QtWidgets.QLabel(
            (
                " You are running AYON launcher in <b>'bypass login'</b>"
                " mode. Meaning your AYON connection information is"
                " defined by environment variables."
                "<br/><br/>Please contact your administrator or use valid"
                " credentials."
            ),
            info_widget
        )
        common_label.setWordWrap(True)
        common_label.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)

        info_layout = QtWidgets.QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        if message_label is not None:
            info_layout.addWidget(message_label, 0)
            info_layout.addWidget(url_cred_sep, 0)
        info_layout.addWidget(common_label, 0)

        footer_widget = QtWidgets.QWidget(self)
        close_btn = QtWidgets.QPushButton("Close", footer_widget)

        footer_layout = QtWidgets.QHBoxLayout(footer_widget)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.addStretch(1)
        footer_layout.addWidget(close_btn, 0)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(info_widget, 0)
        main_layout.addStretch(1)
        main_layout.addWidget(footer_widget, 0)

        close_btn.clicked.connect(self._on_close_click)

        self._first_show = True
        self._message_label = message_label
        self._common_label = common_label

    def resizeEvent(self, event):
        super().resizeEvent(event)
        print(self.size())

    def showEvent(self, event):
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            self._on_first_show()

    def _on_first_show(self):
        self.setStyleSheet(load_stylesheet())
        self.resize(self.default_width, self.default_height)
        self._center_window()

    def _center_window(self):
        """Move window to center of screen."""

        if hasattr(QtWidgets.QApplication, "desktop"):
            desktop = QtWidgets.QApplication.desktop()
            screen_idx = desktop.screenNumber(self)
            screen_geo = desktop.screenGeometry(screen_idx)
        else:
            screen = self.screen()
            screen_geo = screen.geometry()

        geo = self.frameGeometry()
        geo.moveCenter(screen_geo.center())
        if geo.y() < screen_geo.y():
            geo.setY(screen_geo.y())
        self.move(geo.topLeft())

    def _on_close_click(self):
        self.close()


def invalid_credentials(message, always_on_top=False):
    """Tell user that his credentials are invalid.

    This functionality is used when credentials that user did use were
        not received from keyring or login window.

    Args:
        message (str): Some information that can caller define.
        always_on_top (Optional[bool]): Window will be drawn on top of
            other windows.
    """

    app_instance = get_qt_app()
    window = InvalidCredentialsWindow(message)
    if always_on_top:
        window.setWindowFlags(
            window.windowFlags()
            | QtCore.Qt.WindowStaysOnTopHint
        )

    if not app_instance.startingUp():
        window.exec_()
    else:
        window.open()
        # This can become main Qt loop. Maybe should live elsewhere
        app_instance.exec_()


def main(output_path):
    with open(output_path, "r") as stream:
        data = json.load(stream)

    os.remove(output_path)

    message = data["message"]
    always_on_top = data.get("always_on_top", False)
    invalid_credentials(message, always_on_top=always_on_top)


if __name__ == "__main__":
    main(sys.argv[-1])
