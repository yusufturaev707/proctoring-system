"""
"Server bilan aloqa bormi?" — butun dastur uchun BITTA holat.

Manba — `ApiClient`: har HTTP javob (hatto 4xx) "aloqa bor", ulanish
bosqichidagi xato (DNS, rad etilgan ulanish, timeout) va 502/503/504
"aloqa yo'q". Alohida "ping" so'rovi YO'Q va bu ataylab: 5000 mashina
bo'sh turgan paytda ham serverni urib turishi kerak emas — holat
mavjud so'rovlardan (heartbeat, presence, sahifa so'rovlari) chiqadi.

`changed(bool)` signali istalgan thread'dan chiqadi (so'rov fon
ishchisida), Qt esa uni UI thread'dagi qabul qiluvchiga navbat orqali
yetkazadi — shuning uchun obyekt UI thread'iga ko'chiriladi.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)


class NetworkStatus(QObject):
    #: True — aloqa tiklandi, False — uzildi. Faqat O'ZGARISHDA chiqadi.
    changed = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._online = True

    @property
    def is_online(self) -> bool:
        return self._online

    def report(self, online: bool) -> None:
        with self._lock:
            if online == self._online:
                return
            self._online = online
        log.warning("Server bilan aloqa %s", "tiklandi" if online else "uzildi")
        try:
            self.changed.emit(online)
        except RuntimeError:
            # Dastur yopilayotganda C++ obyekti o'chgan bo'lishi mumkin.
            pass


def on_power_resumed(slot) -> bool:
    """
    `slot` ni "kompyuter uyqudan uyg'ondi" signaliga ulaydi.

    `core/system_events.py` bo'lmasa yoki ishlamasa — jimgina `False`:
    uyg'onish tezlatkich xolos, usiz ham davriy so'rovlar aloqani
    o'zi topadi (faqat kechroq).
    """
    try:
        from core.system_events import system_events

        system_events().power_resumed.connect(slot)
        return True
    except Exception:
        log.debug("power_resumed signaliga ulanib bo'lmadi", exc_info=True)
        return False


_instance: Optional[NetworkStatus] = None
_instance_lock = threading.Lock()


def network_status() -> NetworkStatus:
    """
    Yagona nusxa. Birinchi chaqiruv fon thread'ida bo'lsa ham obyekt UI
    thread'iga ko'chiriladi — aks holda u o'lgan ishchi thread'iga
    bog'lanib qolar va signallari hech kimga yetmasdi.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            status = NetworkStatus()
            try:
                from PyQt6.QtCore import QCoreApplication

                app = QCoreApplication.instance()
                if app is not None and status.thread() is not app.thread():
                    status.moveToThread(app.thread())
            except Exception:
                log.debug("NetworkStatus UI thread'iga ko'chirilmadi", exc_info=True)
            _instance = status
        return _instance
