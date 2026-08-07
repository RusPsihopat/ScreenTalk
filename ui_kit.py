"""Общие визуальные элементы интерфейса.

Иконки нарисованы через QPainter (векторно), а не взяты эмодзи-символами —
эмодзи на маленьком размере часто выглядят пиксельно или размыто в
зависимости от системного шрифта. Векторная отрисовка чёткая на любом
масштабе и на любой системе.

Здесь же — переиспользуемые анимации (появление/исчезновение окон,
затухание новых сообщений) и пара маленьких кастомных виджетов (тумблер,
спиннер загрузки), оформленные в одном визуальном стиле.
"""
import math

from PySide6.QtCore import (
    Qt, QRectF, QPoint, QPropertyAnimation, QParallelAnimationGroup,
    QEasingCurve, Property, QTimer, Signal
)
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import QPushButton, QWidget, QGraphicsOpacityEffect


# ==================== векторные иконки ====================

class IconButton(QPushButton):
    """Кнопка с чётко нарисованной векторной иконкой + плавное увеличение
    при наведении мыши."""

    def __init__(self, icon: str, size=32, icon_color="#9aa0a6",
                 hover_color="#f1f1f1", hover_bg=True):
        super().__init__()
        self.icon_name = icon
        self._icon_color = QColor(icon_color)
        self._hover_color = QColor(hover_color)
        self._hover_bg = hover_bg
        self._hovered = False
        self._scale = 1.0
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton {background: transparent; border: none;}")

        self._grow_anim = QPropertyAnimation(self, b"iconScale")
        self._grow_anim.setDuration(120)
        self._pulse_anim = None

    def getIconScale(self):
        return self._scale

    def setIconScale(self, value):
        self._scale = value
        self.update()

    iconScale = Property(float, getIconScale, setIconScale)

    def set_size(self, size: int):
        self.setFixedSize(size, size)
        self.update()

    def set_color(self, color: str):
        self._icon_color = QColor(color)
        self.update()

    def set_icon(self, icon: str):
        self.icon_name = icon
        self.update()

    # ---- пульсация (для микрофона во время записи) ----
    def start_pulse(self):
        self.stop_pulse()
        anim = QPropertyAnimation(self, b"iconScale")
        anim.setDuration(900)
        anim.setLoopCount(-1)
        anim.setKeyValueAt(0, 1.0)
        anim.setKeyValueAt(0.5, 1.28)
        anim.setKeyValueAt(1, 1.0)
        anim.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse_anim = anim
        anim.start()

    def stop_pulse(self):
        if self._pulse_anim is not None:
            self._pulse_anim.stop()
            self._pulse_anim = None
        self._animate_scale(1.0)

    def enterEvent(self, event):
        self._hovered = True
        if self._pulse_anim is None:
            self._animate_scale(1.15)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        if self._pulse_anim is None:
            self._animate_scale(1.0)
        super().leaveEvent(event)

    def _animate_scale(self, target):
        self._grow_anim.stop()
        self._grow_anim.setStartValue(self._scale)
        self._grow_anim.setEndValue(target)
        self._grow_anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._hovered and self._hover_bg:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 28))
            painter.drawRoundedRect(self.rect(), 6, 6)

        color = self._hover_color if self._hovered else self._icon_color
        painter.setPen(QPen(color, 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(color)

        w, h = self.width(), self.height()
        painter.translate(w / 2, h / 2)
        painter.scale(self._scale, self._scale)
        painter.translate(-w / 2, -h / 2)

        draw_fn = getattr(self, f"_draw_{self.icon_name}", None)
        if draw_fn:
            draw_fn(painter, w, h)

    def _draw_close(self, p, w, h):
        pen = QPen(p.brush().color(), max(1.6, w * 0.09), Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        m = w * 0.30
        p.drawLine(int(m), int(m), int(w - m), int(h - m))
        p.drawLine(int(w - m), int(m), int(m), int(h - m))

    def _draw_minimize(self, p, w, h):
        pen = QPen(p.brush().color(), max(1.6, w * 0.09), Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        y = h * 0.66
        p.drawLine(int(w * 0.26), int(y), int(w * 0.74), int(y))

    def _draw_send(self, p, w, h):
        path = QPainterPath()
        m = w * 0.20
        path.moveTo(m, h * 0.18)
        path.lineTo(w - m * 0.5, h / 2)
        path.lineTo(m, h * 0.82)
        path.lineTo(m + w * 0.20, h / 2)
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.drawPath(path)

    def _draw_mic(self, p, w, h):
        color = p.brush().color()
        body_w, body_h = w * 0.26, h * 0.38
        cx, top = w / 2, h * 0.14
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(cx - body_w / 2, top, body_w, body_h), body_w / 2, body_w / 2)
        pen = QPen(color, max(1.4, w * 0.07), Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        arc_rect = QRectF(cx - body_w * 0.95, top + body_h * 0.3, body_w * 1.9, body_h * 1.35)
        p.drawArc(arc_rect, 200 * 16, 140 * 16)
        p.drawLine(int(cx), int(top + body_h * 1.55), int(cx), int(h * 0.84))
        p.drawLine(int(cx - body_w * 0.6), int(h * 0.84), int(cx + body_w * 0.6), int(h * 0.84))

    def _draw_settings(self, p, w, h):
        color = p.brush().color()
        cx, cy = w / 2, h / 2
        r_outer, r_inner = w * 0.30, w * 0.14
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for i in range(8):
            p.save()
            p.translate(cx, cy)
            p.rotate(45 * i)
            p.drawRoundedRect(QRectF(-w * 0.05, -r_outer - w * 0.06, w * 0.10, w * 0.13), 2, 2)
            p.restore()
        p.drawEllipse(QRectF(cx - r_outer * 0.7, cy - r_outer * 0.7, r_outer * 1.4, r_outer * 1.4))
        p.setBrush(QColor(30, 31, 34))
        p.drawEllipse(QRectF(cx - r_inner, cy - r_inner, r_inner * 2, r_inner * 2))

    def _draw_pin_always(self, p, w, h):
        self._draw_pin(p, w, h, filled=True, slash=False)

    def _draw_pin_games(self, p, w, h):
        self._draw_pin(p, w, h, filled=True, slash=False, dot=True)

    def _draw_pin_normal(self, p, w, h):
        self._draw_pin(p, w, h, filled=False, slash=True)

    def _draw_pin(self, p, w, h, filled, slash, dot=False):
        color = p.brush().color()
        cx = w / 2
        head_r = w * 0.15
        head_rect = QRectF(cx - head_r, h * 0.16, head_r * 2, head_r * 2)
        body = QPainterPath()
        body.moveTo(cx - head_r * 0.55, h * 0.16 + head_r * 1.7)
        body.lineTo(cx + head_r * 0.55, h * 0.16 + head_r * 1.7)
        body.lineTo(cx, h * 0.82)
        body.closeSubpath()

        if filled:
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(head_rect)
            p.drawPath(body)
        else:
            pen = QPen(color, max(1.2, w * 0.07))
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(head_rect)
            p.drawPath(body)

        if dot:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(30, 31, 34))
            p.drawEllipse(QRectF(cx - head_r * 0.35, h * 0.16 + head_r * 0.65, head_r * 0.7, head_r * 0.7))

        if slash:
            pen = QPen(color, max(1.4, w * 0.09), Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(int(w * 0.2), int(h * 0.2), int(w * 0.8), int(h * 0.8))

    def _draw_copy(self, p, w, h):
        color = p.brush().color()
        pen = QPen(color, max(1.3, w * 0.09))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        back = QRectF(w * 0.22, h * 0.20, w * 0.5, h * 0.5)
        front = QRectF(w * 0.32, h * 0.32, w * 0.5, h * 0.5)
        p.drawRoundedRect(back, 2, 2)
        p.setBrush(QColor(30, 31, 34))
        p.setPen(Qt.NoPen)
        p.drawRect(front)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(front, 2, 2)

    def _draw_check(self, p, w, h):
        pen = QPen(QColor("#3ddc84"), max(1.8, w * 0.13), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.drawLine(int(w * 0.22), int(h * 0.52), int(w * 0.42), int(h * 0.72))
        p.drawLine(int(w * 0.42), int(h * 0.72), int(w * 0.80), int(h * 0.26))


# ==================== тумблер-переключатель ====================

class ToggleSwitch(QWidget):
    """Компактный тумблер вкл/выкл в едином векторном стиле с приложением."""
    toggled = Signal(bool)

    def __init__(self, checked=False):
        super().__init__()
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._checked = checked
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knobPos")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def getKnobPos(self):
        return self._pos

    def setKnobPos(self, value):
        self._pos = value
        self.update()

    knobPos = Property(float, getKnobPos, setKnobPos)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked, animate=True):
        self._checked = checked
        target = 1.0 if checked else 0.0
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._pos = target
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        off = QColor(255, 255, 255, 40)
        on = QColor("#5aa0ff")
        t = self._pos
        track = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        painter.setBrush(track)
        painter.drawRoundedRect(self.rect(), self.height() / 2, self.height() / 2)

        knob_d = self.height() - 4
        x = 2 + self._pos * (self.width() - knob_d - 4)
        painter.setBrush(QColor("white"))
        painter.drawEllipse(QRectF(x, 2, knob_d, knob_d))


# ==================== спиннер загрузки (три прыгающие точки) ====================

class SpinnerDots(QWidget):
    def __init__(self, color="#5aa0ff"):
        super().__init__()
        self.setFixedSize(40, 16)
        self._color = QColor(color)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._phase = 0.0
        self._timer.start()
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._phase += 0.28
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        r = 3.4
        spacing = 12
        base_y = self.height() / 2
        for i in range(3):
            offset = math.sin(self._phase + i * 1.1) * 4.5
            cx = 7 + i * spacing
            cy = base_y + offset
            painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))


# ==================== анимации окон и виджетов ====================

def fade_in_widget(widget, duration=200):
    """Плавное появление виджета (например, нового сообщения в чате)."""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    widget._fade_effect = effect  # держим ссылки, чтобы не удалило сборщиком мусора
    widget._fade_anim = anim
    anim.start()


def show_animated(window, target_opacity: float, slide="bottom", distance=26, duration=200):
    """Плавное появление окна: затухание + лёгкое выезжание сбоку/снизу."""
    final_pos = window.pos()
    if slide == "bottom":
        start_pos = final_pos + QPoint(0, distance)
    elif slide == "side":
        start_pos = final_pos + QPoint(distance, 0)
    else:
        start_pos = final_pos

    window.move(start_pos)
    window.setWindowOpacity(0.0)
    window.show()

    pos_anim = QPropertyAnimation(window, b"pos")
    pos_anim.setDuration(duration)
    pos_anim.setStartValue(start_pos)
    pos_anim.setEndValue(final_pos)
    pos_anim.setEasingCurve(QEasingCurve.OutCubic)

    op_anim = QPropertyAnimation(window, b"windowOpacity")
    op_anim.setDuration(duration)
    op_anim.setStartValue(0.0)
    op_anim.setEndValue(max(target_opacity, 0.05))
    op_anim.setEasingCurve(QEasingCurve.OutCubic)

    group = QParallelAnimationGroup()
    group.addAnimation(pos_anim)
    group.addAnimation(op_anim)
    window._show_anim = group
    group.start()


def hide_animated(window, slide="bottom", distance=26, duration=160, on_finished=None):
    """Плавное исчезновение окна: затухание + лёгкое выезжание сбоку/снизу."""
    start_pos = window.pos()
    if slide == "bottom":
        end_pos = start_pos + QPoint(0, distance)
    elif slide == "side":
        end_pos = start_pos + QPoint(distance, 0)
    else:
        end_pos = start_pos

    pos_anim = QPropertyAnimation(window, b"pos")
    pos_anim.setDuration(duration)
    pos_anim.setStartValue(start_pos)
    pos_anim.setEndValue(end_pos)
    pos_anim.setEasingCurve(QEasingCurve.InCubic)

    op_anim = QPropertyAnimation(window, b"windowOpacity")
    op_anim.setDuration(duration)
    op_anim.setStartValue(window.windowOpacity())
    op_anim.setEndValue(0.0)
    op_anim.setEasingCurve(QEasingCurve.InCubic)

    group = QParallelAnimationGroup()
    group.addAnimation(pos_anim)
    group.addAnimation(op_anim)

    def _finish():
        window.hide()
        window.move(start_pos)  # возвращаем на место для следующего показа
        if on_finished:
            on_finished()

    group.finished.connect(_finish)
    window._hide_anim = group
    group.start()
