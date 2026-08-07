"""Голосовой ввод: запись с микрофона + распознавание речи через бесплатный
онлайн-сервис Google (облачное распознавание, без локальных моделей — нужен
только интернет в момент запроса).
"""
import numpy as np
import sounddevice as sd
import speech_recognition as sr

SAMPLE_RATE = 16000


class Recorder:
    """Запись звука с микрофона.

    Кроме самой записи хранит `level` — текущую громкость (0..1), которую
    можно опрашивать таймером в UI, чтобы рисовать "живую" волну, как в
    голосовых сообщениях Telegram.
    """

    def __init__(self):
        self._frames = []
        self._stream = None
        self.level = 0.0

    def _callback(self, indata, frames, time_info, status):
        self._frames.append(indata.copy())
        rms = float(np.sqrt(np.mean(np.square(indata))))
        self.level = min(rms * 8.0, 1.0)  # усиливаем, чтобы шкала была живее

    def start(self):
        self._frames = []
        self.level = 0.0
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        self._stream.stop()
        self._stream.close()
        self.level = 0.0
        if self._frames:
            return np.concatenate(self._frames, axis=0)
        return np.zeros((0, 1), dtype="float32")


def _to_audio_data(audio: np.ndarray) -> sr.AudioData:
    mono = audio[:, 0] if audio.ndim > 1 else audio
    pcm16 = np.clip(mono, -1.0, 1.0)
    pcm16 = (pcm16 * 32767).astype(np.int16).tobytes()
    return sr.AudioData(pcm16, SAMPLE_RATE, 2)


def _recognize(audio_data: sr.AudioData, language: str):
    """Возвращает (текст, уверенность 0..1 либо None, если сервис её не дал)."""
    recognizer = sr.Recognizer()
    try:
        result = recognizer.recognize_google(audio_data, language=language, show_all=True)
    except sr.RequestError:
        return "", None
    except Exception:
        return "", None

    if not result or not result.get("alternative"):
        return "", None

    alt = result["alternative"][0]
    text = (alt.get("transcript") or "").strip()
    confidence = alt.get("confidence")
    return text, confidence


def transcribe(audio: np.ndarray, language: str) -> str:
    """Распознаёт речь на заранее известном языке ("ru-RU" или "en-US")."""
    if audio.size == 0:
        return ""
    text, _ = _recognize(_to_audio_data(audio), language)
    return text


def transcribe_auto(audio: np.ndarray):
    """Сама определяет, русская речь или английская.

    Google не умеет распознавать язык "на лету" — приходится спрашивать оба
    варианта и выбирать более уверенный результат. Возвращает (текст, язык).
    """
    if audio.size == 0:
        return "", "ru-RU"

    audio_data = _to_audio_data(audio)
    ru_text, ru_conf = _recognize(audio_data, "ru-RU")
    en_text, en_conf = _recognize(audio_data, "en-US")

    if not ru_text and not en_text:
        return "", "ru-RU"
    if not en_text:
        return ru_text, "ru-RU"
    if not ru_text:
        return en_text, "en-US"

    # если сервис вернул уверенность (confidence) хотя бы для одного варианта —
    # доверяем ей, это самый надёжный сигнал
    if ru_conf is not None or en_conf is not None:
        if (ru_conf or 0.0) >= (en_conf or 0.0):
            return ru_text, "ru-RU"
        return en_text, "en-US"

    # запасной вариант без confidence: более длинная и связная транскрипция
    # обычно означает, что язык распознавания был угадан верно
    if len(ru_text) >= len(en_text):
        return ru_text, "ru-RU"
    return en_text, "en-US"
