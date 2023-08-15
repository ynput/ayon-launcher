import signal
from qtpy import QtWidgets, QtCore, QtGui

from ayon_common.resources import (
    get_icon_path,
    load_stylesheet,
)
from ayon_common.ui_utils import get_qt_app


class AnimationWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)

        duration = 1200

        # Ball animation
        ball_translate_anim = QtCore.QVariantAnimation()
        ball_translate_anim.setKeyValueAt(0.0, 0.65)
        ball_translate_anim.setKeyValueAt(0.25, 1.0)
        ball_translate_anim.setKeyValueAt(0.5, 0.6)
        ball_translate_anim.setKeyValueAt(0.75, 1.0)
        ball_translate_anim.setKeyValueAt(1.0, 0.65)
        ball_translate_anim.setDuration(duration)

        # Legs animation
        angle_anim = QtCore.QVariantAnimation()
        angle_anim.setKeyValueAt(0.0, 0.0)
        angle_anim.setKeyValueAt(0.4, 0.0)
        angle_anim.setKeyValueAt(0.75, 1.0)
        angle_anim.setKeyValueAt(1.0, 1.0)
        angle_anim.setDuration(duration)

        legs_scale_anim = QtCore.QVariantAnimation()
        legs_scale_anim.setKeyValueAt(0.0, 0.9)
        legs_scale_anim.setKeyValueAt(0.25, 1.0)
        legs_scale_anim.setKeyValueAt(0.5, 0.7)
        legs_scale_anim.setKeyValueAt(0.75, 1.0)
        legs_scale_anim.setKeyValueAt(1.0, 0.9)
        legs_scale_anim.setDuration(duration)

        anim_group = QtCore.QParallelAnimationGroup()
        anim_group.addAnimation(angle_anim)
        anim_group.addAnimation(legs_scale_anim)
        anim_group.addAnimation(ball_translate_anim)

        repaint_timer = QtCore.QTimer()
        repaint_timer.setInterval(10)

        angle_anim.valueChanged.connect(
            self._on_angle_anim)
        legs_scale_anim.valueChanged.connect(
            self._on_legs_scale_anim)
        ball_translate_anim.valueChanged.connect(
            self._on_ball_translate_anim)
        repaint_timer.timeout.connect(self.repaint)

        anim_group.finished.connect(self._on_anim_group_finish)

        self._ball_offset_ratio = ball_translate_anim.startValue()
        self._angle = 0
        self._legs_scale = 1.0
        self._anim_group = anim_group
        self._repaint_timer = repaint_timer

    def _on_angle_anim(self, value):
        self._angle = int(value * 360)

    def _on_legs_scale_anim(self, value):
        self._legs_scale = value

    def _on_ball_translate_anim(self, value):
        self._ball_offset_ratio = value

    def _on_anim_group_finish(self):
        self._anim_group.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._anim_group.start()
        self._repaint_timer.start()

    def sizeHint(self):
        height = self.fontMetrics().height()
        return QtCore.QSize(height, height)

    def paintEvent(self, event):
        painter = QtGui.QPainter()
        painter.begin(self)
        render_hints = (
            QtGui.QPainter.Antialiasing
            | QtGui.QPainter.SmoothPixmapTransform
        )
        if hasattr(QtGui.QPainter, "HighQualityAntialiasing"):
            render_hints |= QtGui.QPainter.HighQualityAntialiasing
        event_rect = event.rect()
        event_width = event_rect.width()
        event_height = event_rect.height()
        base_size = min(event_width, event_height)
        left_offset = (event_width - base_size) * 0.5
        top_offset = (event_height - base_size) * 0.5
        half_base_size = base_size * 0.5

        ball_offset = base_size * 0.1
        legs_content_size = base_size - ball_offset

        legs_content_half = legs_content_size * 0.5
        leg_rect_width = int(legs_content_half * 0.7)
        leg_rect_height = int(legs_content_half * 0.2)
        leg_center_offset = int(legs_content_half * 0.2)
        leg_border_offset = legs_content_half - (
            leg_rect_width + leg_center_offset
        )

        ball_size = ball_offset + leg_border_offset

        top_to_center = top_offset + half_base_size + (ball_size * 0.5)

        y_offset = (top_to_center  * self._ball_offset_ratio) - ball_size
        ball_rect = QtCore.QRect(
            -ball_size * 0.5,
            y_offset,
            ball_size,
            ball_size
        )

        leg_rect = QtCore.QRect(
            leg_center_offset, -leg_rect_height * 0.5,
            leg_rect_width, leg_rect_height
        )

        painter.setRenderHints(render_hints)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(0, 215, 160))

        painter.translate(
            left_offset + half_base_size,
            top_to_center
        )
        painter.scale(self._legs_scale, self._legs_scale)
        painter.rotate(90 + self._angle)
        painter.drawRect(leg_rect)
        painter.rotate(120)
        painter.drawRect(leg_rect)
        painter.rotate(120)
        painter.drawRect(leg_rect)
        painter.rotate(210)
        painter.scale(1.0, 1.0)
        painter.drawEllipse(ball_rect)

        painter.end()


class UpdateWindow(QtWidgets.QWidget):
    aspect = 10.0 / 16.0
    default_width = 300

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        # Set icon and title for task icon
        icon_path = get_icon_path()
        icon = QtGui.QIcon(icon_path)
        self.setWindowIcon(icon)
        self.setWindowTitle("AYON Update...")

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.CustomizeWindowHint)

        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        anim_widget = AnimationWidget(self)

        message_label = QtWidgets.QLabel("<b>AYON is updating...</b>", self)
        message_label.setAlignment(QtCore.Qt.AlignCenter)

        margin = 30
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(margin, margin, margin, margin)
        main_layout.addWidget(anim_widget, 1)
        main_layout.addSpacing(10)
        main_layout.addWidget(message_label, 0)

    def paintEvent(self, event):
        painter = QtGui.QPainter()
        painter.begin(self)
        render_hints = (
            QtGui.QPainter.Antialiasing
            | QtGui.QPainter.SmoothPixmapTransform
        )
        if hasattr(QtGui.QPainter, "HighQualityAntialiasing"):
            render_hints |= QtGui.QPainter.HighQualityAntialiasing

        painter.setRenderHints(render_hints)

        event_rect = event.rect()

        painter.setClipRect(event_rect)
        bg_rect = self.rect()

        size = min(bg_rect.width(), bg_rect.height())
        radius = size * 0.05

        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#2C313A"))
        painter.drawRoundedRect(bg_rect, radius, radius)

        painter.end()

    def showEvent(self, event):
        super().showEvent(event)
        self.setStyleSheet(load_stylesheet())
        self.resize(self.default_width, self.default_width * self.aspect)
        screen_geo = self.screen().geometry()
        new_geo = self.geometry()
        offset = new_geo.center() - screen_geo.center()
        new_geo.translate(-offset)
        self.move(new_geo.topLeft())


if __name__ == "__main__":
    app = get_qt_app()
    window = UpdateWindow()
    window.show()

    def signal_handler(*_args):
        window.close()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app.exec_()
