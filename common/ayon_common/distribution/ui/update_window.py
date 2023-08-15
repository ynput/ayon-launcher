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

        legs_start_anim = QtCore.QVariantAnimation()
        legs_start_anim.setStartValue(0.0)
        legs_start_anim.setEndValue(1.0)
        legs_start_anim.setDuration(1000)
        legs_start_anim.setEasingCurve(QtCore.QEasingCurve.InQuart)

        legs_mid_anim = QtCore.QVariantAnimation()
        legs_mid_anim.setStartValue(0.0)
        legs_mid_anim.setEndValue(4.0)
        legs_mid_anim.setDuration(1000)

        legs_end_anim = QtCore.QVariantAnimation()
        legs_end_anim.setStartValue(1.0)
        legs_end_anim.setEndValue(0.0)
        legs_end_anim.setDuration(2000)
        legs_end_anim.setEasingCurve(QtCore.QEasingCurve.OutElastic)

        legs_anim_group = QtCore.QSequentialAnimationGroup()
        legs_anim_group.addPause(300)
        legs_anim_group.addAnimation(legs_start_anim)
        legs_anim_group.addAnimation(legs_mid_anim)
        legs_anim_group.addAnimation(legs_end_anim)

        # Ball animation
        ball_start_anim = QtCore.QVariantAnimation()
        ball_start_anim.setStartValue(1.0)
        ball_start_anim.setEndValue(0.0)
        ball_start_anim.setDuration(300)
        ball_start_anim.setEasingCurve(QtCore.QEasingCurve.InBack)

        ball_end_anim = QtCore.QVariantAnimation()
        ball_end_anim.setStartValue(ball_start_anim.endValue())
        ball_end_anim.setEndValue(ball_start_anim.startValue())
        ball_end_anim.setDuration(300)
        ball_end_anim.setEasingCurve(QtCore.QEasingCurve.OutBack)

        ball_anim_group = QtCore.QSequentialAnimationGroup()
        ball_anim_group.addPause(300)
        ball_anim_group.addAnimation(ball_start_anim)
        ball_anim_group.addPause(
            (
                legs_start_anim.duration()
                + legs_mid_anim.duration()
                + (legs_end_anim.duration() * 0.5)
            )
            - ball_anim_group.duration()
        )
        ball_anim_group.addAnimation(ball_end_anim)
        ball_anim_group.addPause(
            legs_anim_group.duration() - ball_anim_group.duration()
        )

        anim_group = QtCore.QParallelAnimationGroup()
        anim_group.addAnimation(legs_anim_group)
        anim_group.addAnimation(ball_anim_group)

        repaint_timer = QtCore.QTimer()
        repaint_timer.setInterval(10)

        legs_start_anim.valueChanged.connect(self._on_legs_anim_value_change)
        legs_end_anim.valueChanged.connect(self._on_legs_anim_value_change)
        legs_mid_anim.valueChanged.connect(self._on_legs_mid_valud_change)
        ball_start_anim.valueChanged.connect(self._on_ball_anim_value_change)
        ball_end_anim.valueChanged.connect(self._on_ball_anim_value_change)
        repaint_timer.timeout.connect(self.repaint)

        anim_group.finished.connect(self._on_anim_group_finish)

        self._ball_offset_ratio = ball_start_anim.startValue()
        self._legs_angle = 0
        self._anim_group = anim_group
        self._repaint_timer = repaint_timer

    def _on_legs_anim_value_change(self, value):
        self._legs_angle = int(value * 360)

    def _on_legs_mid_valud_change(self, value):
        self._legs_angle = int(360 * value) % 360

    def _on_ball_anim_value_change(self, value):
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

        ball_top_offset = (
            ((leg_border_offset * 2) + ball_offset)
            * self._ball_offset_ratio
        )
        ball_rect = QtCore.QRect(
            (left_offset + half_base_size) - (ball_size * 0.5),
            top_offset + ball_top_offset,
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

        painter.drawEllipse(ball_rect)
        painter.translate(
            left_offset + half_base_size,
            top_offset + half_base_size + (ball_size * 0.5)
        )
        painter.rotate(self._legs_angle + 90)
        painter.drawRect(leg_rect)
        painter.rotate(120)
        painter.drawRect(leg_rect)
        painter.rotate(120)
        painter.drawRect(leg_rect)

        painter.end()


class UpdateWindow(QtWidgets.QWidget):
    aspect = 9.0 / 16.0
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

        message_label = QtWidgets.QLabel("Updating...", self)
        message_label.setStyleSheet("font-size: 20pt;")
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
