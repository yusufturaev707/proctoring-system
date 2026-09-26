"""
Kamera qatlami.

Tashqariga faqat `CameraManager` va tavsif turlari chiqadi — qolgan
hamma narsa (qaysi backend, qanday qayta ulanish, FPS qanday
o'lchanadi) shu paketning ichki ishi.
"""

from proctoring.camera.base import (
    CameraHealth,
    CameraInfo,
    CameraSource,
    CameraState,
)
from proctoring.camera.manager import CameraManager, CameraSlot

__all__ = [
    "CameraHealth",
    "CameraInfo",
    "CameraManager",
    "CameraSlot",
    "CameraSource",
    "CameraState",
]
