"""Полупрозрачный оверлей на весь экран для выделения области мышью."""
from PySide6.QtCore import Qt, QRect, Signal, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QGuiApplication
from PySide6.QtWidgets import QWidget
import mss
import numpy as np


class SelectionOverlay(QWidget):
    area_selected = Signal(np.ndarray)  # захваченное изображение выделенной области

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)

        geo = QGuiApplication.primaryScreen().virtualGeometry()
        self.setGeometry(geo)

        self._origin = QPoint()
        self._current_rect = QRect()
        self._selecting = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        if self._selecting and not self._current_rect.isNull():
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(self._current_rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(80, 170, 255), 2))
            painter.drawRect(self._current_rect)

    def mousePressEvent(self, event):
        self._origin = event.globalPosition().toPoint()
        self._current_rect = QRect(self._origin, self._origin)
        self._selecting = True
        self.update()

    def mouseMoveEvent(self, event):
        if self._selecting:
            self._current_rect = QRect(self._origin, event.globalPosition().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        self._selecting = False
        rect = self._current_rect
        self.close()
        if rect.width() > 3 and rect.height() > 3:
            self._grab(rect)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def _grab(self, rect: QRect):
        with mss.mss() as sct:
            monitor = {
                "left": rect.left(), "top": rect.top(),
                "width": rect.width(), "height": rect.height(),
            }
            shot = sct.grab(monitor)
            img = np.array(shot)[:, :, :3]  # BGRA -> BGR
            self.area_selected.emit(img)
