"""Singleton metaklassi — `ApiClient` va `FaceEngine` uchun.

Ikkalasi ham qimmat resurs ushlaydi (HTTP pool, ~300 MB ONNX sessiya).
Har sahifada yangisini yaratish xotira va ulanishlarni isrof qiladi.
"""

import threading


class SingletonMeta(type):
    _instances: dict = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        # Qulf kerak: `FaceEngine()` ham UI thread'dan, ham kamera
        # thread'idan chaqiriladi. Qulfsiz ikkita ONNX sessiya ochilib,
        # xotira ikki barobar bo'lishi mumkin.
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
