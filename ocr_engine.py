"""Распознавание текста на изображении через бесплатный онлайн-сервис
OCR.space (облачный OCR, без локальных нейросетей и без загрузки моделей).

Нужен интернет при каждом распознавании (это ожидаемо — сервис облачный).
Бесплатный личный API-ключ: https://ocr.space/ocrapi/freekey — вводится
только почта, без карты и без оплаты, ключ приходит сразу же. Вписать его
в config.OCR_SPACE_API_KEY вместо демо-ключа "helloworld".
"""
import io

import numpy as np
import requests
from PIL import Image

from config import OCR_SPACE_API_KEY

OCR_URL = "https://api.ocr.space/parse/image"


def _call_ocr(image_bytes: bytes, language: str) -> str:
    response = requests.post(
        OCR_URL,
        files={"file": ("capture.png", image_bytes, "image/png")},
        data={
            "apikey": OCR_SPACE_API_KEY,
            "language": language,
            "OCREngine": 2,      # движок 2 точнее на коротких игровых фразах
            "scale": "true",     # строкой, а не Python-True — иначе сервис не поймёт параметр
        },
        timeout=20,
    )
    result = response.json()
    if result.get("IsErroredOnProcessing"):
        return ""
    parsed = result.get("ParsedResults") or []
    if not parsed:
        return ""
    text = (parsed[0].get("ParsedText") or "")
    # OCR.space разделяет строки как "\r\n" — приводим к обычному "\n",
    # чтобы построчная структура (важно для "Ник: сообщение") дошла до
    # переводчика в целости
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip("\n")


def _letters(text: str) -> int:
    return sum(ch.isalpha() for ch in text)


def image_to_text(image: np.ndarray) -> str:
    """Принимает изображение (numpy array, BGR) и возвращает распознанный текст.

    Сервис за один запрос понимает только один язык, поэтому пробуем русский
    и английский и берём тот результат, где больше распознанных букв —
    так неверный вариант (пустой или "мусорный") просто отбрасывается.
    """
    rgb = image[:, :, ::-1]
    pil_img = Image.fromarray(rgb)
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    text_ru = _call_ocr(image_bytes, "rus")
    text_en = _call_ocr(image_bytes, "eng")

    return text_ru if _letters(text_ru) >= _letters(text_en) else text_en
