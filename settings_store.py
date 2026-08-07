"""Хранение пользовательских настроек между перезапусками приложения.

Простой JSON-файл рядом со скриптом.
"""
import copy
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_settings.json")

DEFAULTS = {
    "opacity_percent": 90,  # 0..100, шаг 5
    # scan_code — физический скан-код клавиши (см. hotkey_state.py), не
    # зависит от раскладки. 41 — клавиша "ё" / "`".
    "capture_hotkey": {"scan_code": 41, "ctrl": False, "alt": False, "shift": False},
    "toggle_hotkey": {"scan_code": 41, "ctrl": True, "alt": False, "shift": False},
    "pin_mode": "always",   # "always" | "games" | "normal"
    "auto_copy": True,      # копировать перевод в буфер обмена автоматически
    "sound_enabled": True,  # звук после готовности OCR-перевода
    "ui_scale": 100,        # 100 | 125 | 150 (% масштаба интерфейса)
    "window_x": None,       # запомненное положение окна чата
    "window_y": None,
    "settings_window_x": None,  # запомненное положение окна настроек
    "settings_window_y": None,
}


def load() -> dict:
    settings = copy.deepcopy(DEFAULTS)
    if os.path.exists(_PATH):
        try:
            with open(_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            settings.update(saved)
        except Exception:
            pass  # повреждённый файл настроек — просто используем значения по умолчанию
    return settings


def save(settings: dict):
    try:
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # не удалось сохранить — не критично, продолжаем работать
