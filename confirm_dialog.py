"""Маленькое диалоговое окошко подтверждения — "свернуть в трей или закрыть
программу полностью?". В том же визуальном стиле, что и остальные окна
приложения (тёмное, скруглённое, полупрозрачное, с плавным появлением).
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame

from ui_kit import show_animated, hide_animated


class ConfirmDialog(QWidget):
    minimize_chosen = Signal()
    quit_chosen = Signal()

    def __init__(self, message: str, opacity_percent: int = 95):
        super().__init__()
        self._opacity_percent = opacity_percent
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(300, 150)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        container = QFrame()
        container.setObjectName("container")
        container.setStyleSheet("#container {background-color: #1e1f22; border-radius: 14px;}")
        outer.addWidget(container)

        main = QVBoxLayout(container)
        main.setContentsMargins(20, 20, 20, 16)
        main.setSpacing(16)

        label = QLabel(message)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #f1f1f1; font-size: 13px;")
        main.addWidget(label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        minimize_btn = QPushButton("Свернуть в трей")
        minimize_btn.setFixedHeight(34)
        minimize_btn.setCursor(Qt.PointingHandCursor)
        minimize_btn.setStyleSheet(
            "QPushButton {background: rgba(255,255,255,20); color: #f1f1f1;"
            "border: none; border-radius: 8px; font-size: 12px;}"
            "QPushButton:hover {background: rgba(255,255,255,35);}"
        )
        minimize_btn.clicked.connect(self._on_minimize)

        quit_btn = QPushButton("Закрыть программу")
        quit_btn.setFixedHeight(34)
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.setStyleSheet(
            "QPushButton {background: #ff5a5a; color: white;"
            "border: none; border-radius: 8px; font-size: 12px; font-weight: 600;}"
            "QPushButton:hover {background: #ff7070;}"
        )
        quit_btn.clicked.connect(self._on_quit)

        btn_row.addWidget(minimize_btn)
        btn_row.addWidget(quit_btn)
        main.addLayout(btn_row)

    def _on_minimize(self):
        self.minimize_chosen.emit()
        hide_animated(self, slide="none", on_finished=self.deleteLater)

    def _on_quit(self):
        self.quit_chosen.emit()
        hide_animated(self, slide="none", on_finished=self.deleteLater)

    def animate_show_centered_on(self, parent_widget):
        px = parent_widget.x() + (parent_widget.width() - self.width()) // 2
        py = parent_widget.y() + (parent_widget.height() - self.height()) // 2
        self.move(max(px, 0), max(py, 0))
        show_animated(self, max(self._opacity_percent, 1) / 100, slide="none")
