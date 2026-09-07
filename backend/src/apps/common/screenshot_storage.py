"""
Skrinshot fayllari uchun storage qatlami.

Nima uchun alohida interfeys kerak: bugun fayllar shu serverning diskida
yotadi, ertaga ular S3-mos storage'ga ko'chishi mumkin. Agar `open()`,
`os.path.join()` va `unlink()` chaqiruvlari view, service va Celery task
bo'ylab sochilib ketsa, bu ko'chish o'nlab joyni qayta yozishni talab
qiladi va ularning bittasi albatta e'tibordan chetda qoladi. Shuning
uchun tashqi dunyo faqat beshta amalni biladi:

    save / delete / exists / serve / prune_empty_dirs

`serve` ataylab HTTP javobini qaytaradi, `bytes` emas — "faylni qanday
yetkazish" storage'ning O'Z ishi:

    filesystem  ->  `X-Accel-Redirect` (baytlarni nginx o'qiydi)
    S3          ->  presigned URL'ga 302

Ikkala holatda ham binary Python worker'idan O'TMAYDI, lekin ruxsat
tekshiruvi Django'da qoladi. Yangi backend qo'shish uchun shu klassdan
meros olib, `SCREENSHOT_STORAGE["BACKEND"]` ni o'zgartirish yetarli.
"""

from __future__ import annotations

import abc
import functools
import logging
import os
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, HttpResponse, HttpResponseBase
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

__all__ = [
    "ScreenshotStorage",
    "FilesystemScreenshotStorage",
    "ScreenshotAlreadyExists",
    "get_screenshot_storage",
    "reset_screenshot_storage",
    "safe_relative_path",
]


class ScreenshotAlreadyExists(Exception):
    """
    Shu nomli fayl allaqachon bor.

    Chaqiruvchi buni ko'rib nomni o'zgartiradi (`seq` ni oshiradi).
    Ustidan yozib yuborish MUMKIN EMAS: har bir fayl bitta DB qatoriga
    tegishli va uni bosib o'tish boshqa sessiyaning dalilini yo'q qiladi.
    """


def safe_relative_path(value: str) -> PurePosixPath:
    """
    Nisbiy yo'lni tekshiradi va normallashtiradi.

    Yo'l DB'dan keladi, ya'ni "ishonchli" ko'rinadi. Lekin u o'sha DB'ga
    bir marta xato yozilsa yoki migratsiya paytida buzilsa, `../../..`
    bilan storage root'idan tashqariga chiqish mumkin bo'ladi — bu esa
    `serve` orqali `/etc/passwd` ni o'qish demakdir. Shuning uchun har bir
    chaqiruvda qaytadan tekshiriladi.
    """
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        raise SuspiciousFileOperation("Skrinshot yo'li bo'sh")
    if "\x00" in text:
        raise SuspiciousFileOperation("Skrinshot yo'lida NUL bayt bor")

    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        raise SuspiciousFileOperation(f"Xavfli skrinshot yo'li: {text!r}")
    # Windows'da `C:/x` POSIX yo'l sifatida absolyut HISOBLANMAYDI, lekin
    # `Path` uni disk ildizi deb tushunadi.
    if ":" in pure.parts[0]:
        raise SuspiciousFileOperation(f"Xavfli skrinshot yo'li: {text!r}")
    return pure


# --------------------------------------------------------------------------
# Interfeys
# --------------------------------------------------------------------------
class ScreenshotStorage(abc.ABC):
    """Skrinshot baytlari bilan ishlashning yagona yuzasi."""

    @abc.abstractmethod
    def save(self, relative_path: str, data: bytes, *, overwrite: bool = False) -> int:
        """
        Faylni ATOMIK yozadi va yozilgan bayt sonini qaytaradi.

        `overwrite=False` (standart) da fayl mavjud bo'lsa
        `ScreenshotAlreadyExists` ko'tariladi.

        Atomiklik shart: yarim yozilgan fayl proktor uchun buzilgan rasm,
        retention uchun esa "bor" deb ko'rinadigan axlat bo'ladi.
        """

    @abc.abstractmethod
    def delete(self, relative_path: str) -> bool:
        """Faylni o'chiradi. Fayl topilmasa `False` (xato EMAS)."""

    @abc.abstractmethod
    def exists(self, relative_path: str) -> bool:
        """Fayl mavjudligini tekshiradi."""

    @abc.abstractmethod
    def serve(
        self, relative_path: str, *, content_type: str, filename: str = ""
    ) -> HttpResponseBase:
        """
        Faylni yetkazadigan HTTP javobini yig'adi.

        Fayl topilmasa `FileNotFoundError` ko'taradi — view uni 404 ga
        aylantiradi.
        """

    def prune_empty_dirs(self, limit: int = 1000) -> int:
        """
        Bo'shab qolgan kataloglarni tozalaydi (retention'dan keyin).

        Obyekt storage'ida katalog tushunchasi yo'q, shuning uchun bu
        standart holatda hech nima qilmaydi.
        """
        return 0


# --------------------------------------------------------------------------
# Fayl tizimi
# --------------------------------------------------------------------------
class FilesystemScreenshotStorage(ScreenshotStorage):
    """
    Skrinshotlarni lokal (yoki NFS) fayl tizimida saqlaydi.

    Katalog strukturasi: `{exam_id}/{session_id}/{captured_at}_{seq}.jpg`.
    Sessiya bo'yicha guruhlash ataylab: bitta imtihon sessiyasining barcha
    dalili bitta katalogda yotadi, uni arxivlash ham, ko'chirish ham,
    retention'dan keyin butunlay o'chirish ham bitta amal.
    """

    def __init__(
        self,
        *,
        root: str | os.PathLike | None = None,
        internal_location: str | None = None,
        serve_directly: bool | None = None,
        dir_mode: int | None = None,
        file_mode: int | None = None,
    ) -> None:
        conf = settings.SCREENSHOT_STORAGE
        self.root = Path(root or conf["ROOT"]).resolve()
        self.internal_location = (
            internal_location if internal_location is not None else conf["INTERNAL_LOCATION"]
        )
        self.serve_directly = (
            conf["SERVE_DIRECTLY"] if serve_directly is None else serve_directly
        )
        self.dir_mode = conf["DIR_MODE"] if dir_mode is None else dir_mode
        self.file_mode = conf["FILE_MODE"] if file_mode is None else file_mode

    # ---- ichki yordamchilar -------------------------------------------
    def _absolute(self, relative_path: str) -> Path:
        relative = safe_relative_path(relative_path)
        absolute = (self.root / relative).resolve()

        # Tekshiruv `resolve()` dan KEYIN: satr darajasida toza ko'ringan
        # yo'l symlink orqali root'dan tashqariga olib chiqishi mumkin.
        if absolute != self.root and self.root not in absolute.parents:
            raise SuspiciousFileOperation(
                f"Skrinshot yo'li storage root'idan tashqarida: {relative_path!r}"
            )
        return absolute

    @staticmethod
    def _unlink_quietly(path: str | os.PathLike) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        """
        Katalog yozuvini diskka tushiradi.

        `os.replace` faylni atomik almashtiradi, lekin serverdan elektr
        uzilsa yangi nom hali katalog jurnaliga tushmagan bo'lishi mumkin.
        Windows'da katalogni `open()` qilib bo'lmaydi — u yerda o'tkazib
        yuboriladi (dev muhit, bunday kafolat talab qilinmaydi).
        """
        try:
            fd = os.open(directory, os.O_RDONLY)
        except (OSError, AttributeError):
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    # ---- interfeys ----------------------------------------------------
    def save(self, relative_path: str, data: bytes, *, overwrite: bool = False) -> int:
        absolute = self._absolute(relative_path)
        absolute.parent.mkdir(parents=True, exist_ok=True)

        reserved = False
        if not overwrite:
            # Yakuniy nomni O_EXCL bilan BAND QILAMIZ. "Avval tekshirib,
            # keyin yozish" bu yerda ishlamaydi: ikkita parallel yuklash
            # tekshiruvdan birga o'tib, keyin biri ikkinchisining faylini
            # bosib yozadi (TOCTOU). O_EXCL — yagona atomik "band qilish".
            try:
                os.close(
                    os.open(absolute, os.O_CREAT | os.O_EXCL | os.O_WRONLY, self.file_mode)
                )
            except FileExistsError as exc:
                raise ScreenshotAlreadyExists(str(relative_path)) from exc
            reserved = True

        # Vaqtinchalik fayl AYNAN SHU katalogda yaratiladi: `os.replace`
        # faqat bitta fayl tizimi ichida atomik. `/tmp` boshqa mount
        # bo'lsa, u ko'chirishga aylanadi va yarim fayl ko'rinib qoladi.
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=absolute.parent, prefix=f".{absolute.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                # Nomni almashtirishdan OLDIN diskka tushiramiz, aks holda
                # yiqilishdan keyin "nomi bor, ichi bo'sh" fayl qoladi.
                os.fsync(handle.fileno())
            os.chmod(tmp_name, self.file_mode)

            # `os.rename` EMAS: Windows'da mavjud faylning ustiga yozmaydi
            # va biz yuqorida nomni O_EXCL bilan band qilib bo'lganmiz.
            # `os.replace` ikkala platformada ham atomik almashtiradi.
            os.replace(tmp_name, absolute)
        except BaseException:
            self._unlink_quietly(tmp_name)
            if reserved:
                self._unlink_quietly(absolute)
            raise

        self._fsync_directory(absolute.parent)
        return len(data)

    def delete(self, relative_path: str) -> bool:
        try:
            absolute = self._absolute(relative_path)
        except SuspiciousFileOperation:
            # Buzilgan yo'lli qator o'chirilishi kerak, lekin uning
            # nomidan hech narsa o'chirmaymiz.
            logger.error("Xavfli skrinshot yo'li o'chirilmadi: %r", relative_path)
            return False
        try:
            os.unlink(absolute)
        except FileNotFoundError:
            return False
        return True

    def exists(self, relative_path: str) -> bool:
        try:
            return self._absolute(relative_path).is_file()
        except SuspiciousFileOperation:
            return False

    def serve(
        self, relative_path: str, *, content_type: str, filename: str = ""
    ) -> HttpResponseBase:
        absolute = self._absolute(relative_path)

        if self.serve_directly:
            # Faqat ishlab chiqish uchun: oldida nginx yo'q, shuning uchun
            # faylni Django o'zi beradi. Production'da BU YO'L YOPIQ —
            # 120 MB/s oqim gunicorn worker'larini bloklaydi.
            return FileResponse(
                absolute.open("rb"), content_type=content_type, filename=filename or None
            )

        if not absolute.is_file():
            # `internal` location'da fayl yo'q bo'lsa nginx 404 qaytaradi,
            # lekin biz uni standart konvertda bergan ma'qul.
            raise FileNotFoundError(str(relative_path))

        # Bo'sh tanali javob: baytlarni nginx o'zi o'qiydi. Django faqat
        # "kimga ruxsat bor" degan savolga javob berdi.
        response = HttpResponse(b"", content_type=content_type)
        response["X-Accel-Redirect"] = self.internal_url(relative_path)
        if filename:
            response["Content-Disposition"] = f'inline; filename="{filename}"'
        # Skrinshot dalil — u kesh yoki proxy'da qolib ketmasligi kerak.
        response["Cache-Control"] = "private, no-store"
        return response

    def internal_url(self, relative_path: str) -> str:
        """`X-Accel-Redirect` uchun ichki URI (nginx `internal` location)."""
        relative = safe_relative_path(relative_path)
        return f"{self.internal_location.rstrip('/')}/{quote(str(relative))}"

    def prune_empty_dirs(self, limit: int = 1000) -> int:
        """
        Retention'dan keyin bo'shab qolgan kataloglarni o'chiradi.

        Har bir sessiya o'z katalogini yaratadi. Ular o'chirilmasa, bir
        yildan keyin diskda millionlab bo'sh katalog qoladi va `find`,
        backup, hatto `ls` ham imkonsiz bo'lib qoladi.
        """
        removed = 0
        if not self.root.is_dir():
            return 0

        # `topdown=False` — avval ichkarisi, keyin tashqarisi. Aks holda
        # bo'shagan ota-katalog o'sha yurishda ko'rinmaydi.
        for current, directories, files in os.walk(self.root, topdown=False):
            if removed >= limit:
                break
            path = Path(current)
            if path == self.root or directories or files:
                continue
            try:
                path.rmdir()
                removed += 1
            except OSError:
                # Parallel yuklash aynan shu katalogga yozayotgan bo'lishi
                # mumkin — keyingi yurishda tozalanadi.
                continue
        return removed


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def get_screenshot_storage() -> ScreenshotStorage:
    """Sozlamada ko'rsatilgan backend'ning process bo'yicha yagona nusxasi."""
    return import_string(settings.SCREENSHOT_STORAGE["BACKEND"])()


def reset_screenshot_storage() -> None:
    """Testlar va `override_settings` dan keyin chaqiriladi."""
    get_screenshot_storage.cache_clear()
