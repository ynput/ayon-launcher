import os
import sys
import json

from qtpy import QtWidgets, QtGui

from ayon_common.resources import (
    get_icon_path,
    load_stylesheet,
)
from ayon_common.ui_utils import get_qt_app


class MessageWindow(QtWidgets.QDialog):
    default_width = 410
    default_height = 170

    def __init__(
        self, title, message, sub_message, parent=None
    ):
        super().__init__(parent)

        icon_path = get_icon_path()
        icon = QtGui.QIcon(icon_path)
        self.setWindowIcon(icon)
        self.setWindowTitle(title)

        self._first_show = True

        body_widget = QtWidgets.QWidget(self)

        icon_side = QtWidgets.QWidget(body_widget)
        icon_label = QtWidgets.QLabel(icon_side)
        icon_side_layout = QtWidgets.QVBoxLayout(icon_side)
        icon_side_layout.setContentsMargins(3, 3, 3, 3)
        icon_side_layout.addWidget(icon_label, 0)
        icon_side_layout.addStretch(1)

        info_widget = QtWidgets.QWidget(body_widget)
        info_label = QtWidgets.QLabel(message, info_widget)
        info_label.setWordWrap(True)

        sub_message_label = None
        if sub_message:
            sub_message_label = QtWidgets.QLabel(sub_message, info_widget)

        info_layout = QtWidgets.QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.addWidget(info_label, 0)
        info_layout.addStretch(1)
        if sub_message_label:
            info_layout.addWidget(sub_message_label, 0)

        body_layout = QtWidgets.QHBoxLayout(body_widget)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(icon_side, 0)
        body_layout.addWidget(info_widget, 1)

        btns_widget = QtWidgets.QWidget(self)
        confirm_btn = QtWidgets.QPushButton("Close", btns_widget)

        btns_layout = QtWidgets.QHBoxLayout(btns_widget)
        btns_layout.setContentsMargins(0, 0, 0, 0)
        btns_layout.addStretch(1)
        btns_layout.addWidget(confirm_btn, 0)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(body_widget, 1)
        main_layout.addWidget(btns_widget, 0)

        confirm_btn.clicked.connect(self._on_confirm_click)

        self._icon_label = icon_label
        self._confirm_btn = confirm_btn

    def showEvent(self, event):
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            self._on_first_show()
        self._recalculate_sizes()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalculate_sizes()

    def _update_icon(self):
        style = self.style()
        size = style.pixelMetric(
            QtWidgets.QStyle.PM_MessageBoxIconSize, None, self)
        icon = style.standardIcon(
            QtWidgets.QStyle.SP_MessageBoxCritical, None, self)

        self._icon_label.setPixmap(icon.pixmap(size, size))

    def _recalculate_sizes(self):
        hint = self._confirm_btn.sizeHint()
        new_width = max((hint.width(), hint.height() * 3))
        self._confirm_btn.setMinimumWidth(new_width)
        self._update_icon()

    def _on_first_show(self):
        self.setStyleSheet(load_stylesheet())
        self.resize(self.default_width, self.default_height)

    def _on_confirm_click(self):
        self.accept()
        self.close()


def main():
    """Show message that server does not have set bundle to use.

    It is possible to pass url as argument to show it in the message. To use
        this feature, pass `--url <url>` as argument to this script.
    """

    filepath = sys.argv[-1]
    with open(filepath, "r") as stream:
        data = json.load(stream)

    app = get_qt_app()
    window = MessageWindow(
        data["title"],
        data["message"],
        data["sub_message"],
    )
    window.show()
    app.exec_()


if __name__ == "__main__":
    main()
