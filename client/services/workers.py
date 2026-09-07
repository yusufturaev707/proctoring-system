"""
Umumiy fon ishchisi.

QOIDA: HECH BIR tarmoq chaqiruvi UI thread'da bajarilmaydi. Sinxron
so'rov UI thread'da bo'lsa, oyna so'rov davomida muzlaydi:
`setEnabled(False)` ko'rinmaydi va shu paytdagi bosishlar navbatga
tushib, javob kelgach qayta ishlaydi (ikki marta login, ikki marta
sessiya).

Har bir sahifa uchun alohida QThread klassi yozish o'rniga bitta
universal worker: chaqiriladigan funksiyani oladi, natijani signal
bilan qaytaradi.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt6.QtCore import QEventLoop, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.errors import ClientError

log = logging.getLogger(__name__)


class ApiWorker(QThread):
    """
    Bitta chaqiruvni fon thread'ida bajaradi.

    succeeded(object) - natija (dict, list yoki None)
    failed(str, str)  - (foydalanuvchiga xabar, backend `code`)
    """

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str, str)

    def __init__(self, func: Callable[..., Any], *args, parent=None, **kwargs) -> None:
        super().__init__(parent)
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._func(*self._args, **self._kwargs)
        except ClientError as exc:
            # Kutilgan xato - xabar allaqachon foydalanuvchi tilida
            # (`ApiClient._unwrap` uni `core.errors` orqali tarjima qilgan).
            self.failed.emit(exc.message, exc.code)
        except Exception as exc:
            log.exception("Fon vazifasida kutilmagan xato")
            self.failed.emit("Kutilmagan xato: {}".format(str(exc)[:120]), "internal")
        else:
            self.succeeded.emit(result)


class WorkerHolder:
    """
    Ishlab turgan worker'larga referens ushlaydi.

    Sababi ikkita:
      1. Python referensi yo'qolsa, QThread garbage collector'ga tushadi
         va "QThread: Destroyed while thread is still running" bilan
         dastur qulaydi.
      2. Sahifa yopilayotganda ularni kutish kerak (`wait_all`).
    """

    def __init__(self) -> None:
        self._workers: list[ApiWorker] = []

    def run(self, worker: ApiWorker) -> ApiWorker:
        self._workers.append(worker)
        worker.finished.connect(lambda: self._discard(worker))
        worker.start()
        return worker

    def _discard(self, worker: ApiWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    @property
    def busy(self) -> bool:
        return any(worker.isRunning() for worker in self._workers)

    def wait_all(self, msec: int = 8_000) -> None:
        """
        Ishlab turgan worker'larni tugatadi - dastur yopilayotganda.

        Uch qaror va uchalasi ham chiqish tezligi uchun:

        * kutish KICHIK bo'laklarda va har bo'lak orasida hodisa
          navbati aylanadi - aks holda UI thread muzlaydi va Windows
          oynani "javob bermayapti" deb oqartirib qo'yadi;
        * chegara 35 s dan 8 s ga tushirildi - natija endi hech kimga
          kerak emas, kerak bo'lgani thread'ning tugashi. Osilib
          qolgan HTTP so'rovi `API_TIMEOUT` (30 s) gacha kutishi
          mumkin va shuncha vaqt dastur vazifalar ro'yxatida qolib
          ketardi;
        * chegaradan oshsa `terminate()`: jarayon baribir tugayapti,
          ishlab turgan QThread bilan chiqish esa qulash demak.
        """
        deadline_slices = max(1, msec // 250)
        for worker in list(self._workers):
            if not worker.isRunning():
                continue
            finished = False
            for _ in range(deadline_slices):
                if worker.wait(250):
                    finished = True
                    break
                application = QApplication.instance()
                if application is not None:
                    application.processEvents(
                        QEventLoop.ProcessEventsFlag.AllEvents, 25
                    )
            if not finished:
                log.warning("Worker tugamadi (%s ms) - terminate", msec)
                worker.terminate()
                worker.wait(1000)
