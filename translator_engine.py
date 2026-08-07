"""Перевод текста между русским и английским.

Основной движок — DeepL, если в config.py задан бесплатный ключ: по
качеству на живой, разговорной и игровой речи заметно превосходит Google
Translate, особенно на паре RU-EN. Если ключ не задан (по умолчанию) или
DeepL временно недоступен — автоматический откат на Google Translate,
полностью бесплатно, без ключа и без ограничений.

Перевод сохраняет исходный построчный формат — это важно для игрового
чата и скриншотов:
- пустые строки/переносы остаются на месте;
- строки вида "Ник: сообщение" переводится только сама фраза, ник
  остаётся как есть (иначе имена игроков превращались бы в бессмысленный
  "перевод" и текст переставал быть похож на оригинал).
"""
import re
import requests

from deep_translator import GoogleTranslator

from config import LANG_A, LANG_B, DEEPL_API_KEY

_DEEPL_LANG = {"ru": "RU", "en": "EN-US"}

# "Ник: сообщение" — ник: только буквы/цифры/подчёркивание/дефис/скобки,
# без пробелов, разумной длины. Так по ошибке не зацепим обычные фразы
# вроде "Кстати: я согласен" (там после двоеточия обычно есть пробел, но
# сам "ник" — не одно "слово"-идентификатор, а тут проверка мягкая и
# осознанно чуть более широкая, это нормально для эвристики).
_NICK_LINE = re.compile(r'^([A-Za-zА-Яа-яЁё0-9_\-\[\]]{1,24}):\s*(.+)$')


def detect_lang(text: str) -> str:
    """Определяет язык для пары RU/EN по наличию кириллицы."""
    if re.search(r'[а-яА-ЯёЁ]', text):
        return LANG_A
    return LANG_B


def _parse_lines(text: str):
    """Возвращает список (ник_или_None, текст_строки) для каждой строки
    исходного текста, сохраняя пустые строки как есть."""
    parsed = []
    for raw_line in text.split('\n'):
        line = raw_line.strip()
        if not line:
            parsed.append((None, ''))
            continue
        m = _NICK_LINE.match(line)
        if m:
            parsed.append((m.group(1), m.group(2)))
        else:
            parsed.append((None, line))
    return parsed


def _deepl_batch(texts, src, dst):
    """Переводит список строк через DeepL за один запрос. None при
    отсутствии ключа или любой ошибке — тогда вызывающий код откатится
    на Google."""
    if not DEEPL_API_KEY or not texts:
        return None
    try:
        response = requests.post(
            "https://api-free.deepl.com/v2/translate",
            data={
                "auth_key": DEEPL_API_KEY,
                "text": texts,
                "source_lang": _DEEPL_LANG[src],
                "target_lang": _DEEPL_LANG[dst],
            },
            timeout=15,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        translations = data.get("translations") or []
        if len(translations) != len(texts):
            return None
        return [t.get("text", "").strip() for t in translations]
    except Exception:
        return None


def _google_batch(texts, src, dst):
    translator = GoogleTranslator(source=src, target=dst)
    try:
        result = translator.translate_batch(texts)
        # translate_batch иногда возвращает None для отдельных элементов
        # при сбое — подстрахуемся оригиналом, чтобы ничего не потерять
        return [r if r else orig for r, orig in zip(result, texts)]
    except Exception:
        out = []
        for t in texts:
            try:
                out.append(translator.translate(t))
            except Exception:
                out.append(t)
        return out


def translate(text: str):
    """Переводит текст, автоматически определяя направление RU <-> EN и
    сохраняя построчный формат (пустые строки, "Ник: сообщение").

    Возвращает (исходный_язык, целевой_язык, переведённый_текст).
    """
    text = text.strip('\n')
    if not text.strip():
        return LANG_A, LANG_B, ""

    src = detect_lang(text)
    dst = LANG_B if src == LANG_A else LANG_A

    parsed = _parse_lines(text)
    to_translate = [msg for _, msg in parsed if msg]

    if not to_translate:
        return src, dst, text

    translated_texts = _deepl_batch(to_translate, src, dst)
    if translated_texts is None:
        translated_texts = _google_batch(to_translate, src, dst)

    translated_iter = iter(translated_texts)
    result_lines = []
    for nick, msg in parsed:
        if not msg:
            result_lines.append('')
            continue
        translated_msg = next(translated_iter)
        result_lines.append(f"{nick}: {translated_msg}" if nick else translated_msg)

    return src, dst, '\n'.join(result_lines)
