"""Общее изменяемое состояние горячих клавиш.

Один экземпляр HotkeyState создаётся при запуске и передаётся и в обработчик
хоткеев (main.py), и в окно настроек. Настройки правят его поля прямо на
лету — обработчик хоткеев читает их каждый раз заново, так что новая
комбинация начинает работать сразу, без перезапуска приложения.
"""

# Небольшой словарь понятных названий для типичных скан-кодов — остальные
# просто показываются как "клавиша #<код>"
_KNOWN_SCAN_CODES = {
    41: "ё / `",
    1: "Esc",
    57: "Пробел",
    28: "Enter",
    15: "Tab",
}


class HotkeyState:
    def __init__(self, capture: dict, toggle: dict):
        self.capture = dict(capture)
        self.toggle = dict(toggle)


def scan_code_label(scan_code: int) -> str:
    return _KNOWN_SCAN_CODES.get(scan_code, f"клавиша #{scan_code}")


def combo_label(combo: dict) -> str:
    """Человекочитаемое описание комбинации, например 'Ctrl + ё / `'."""
    parts = []
    if combo.get("ctrl"):
        parts.append("Ctrl")
    if combo.get("alt"):
        parts.append("Alt")
    if combo.get("shift"):
        parts.append("Shift")
    parts.append(scan_code_label(combo["scan_code"]))
    return " + ".join(parts)
