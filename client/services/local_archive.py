"""
Skrinshot va dalillarning MAHALLIY arxivi.

NIMA UCHUN MASHINANING O'ZIDA. Serverga yuborish joyida qoladi va
panel avvalgidek ishlaydi — bu qatlam undan MUSTAQIL ikkinchi nusxa:

  * tarmoq uzilsa yoki server to'lib qolsa, imtihon kuni yig'ilgan
    dalil yo'qolmaydi (yuborish navbati RAM'da va dastur yopilganda
    u bilan birga ketadi);
  * tekshiruv komissiyasi ko'pincha mashinaning O'ZIDAN dalil
    so'raydi va o'shanda "serverga qarang" degan javob ish
    bermaydi.

DISK ENG BO'SHI TANLANADI. Imtihon mashinasida tizim diski odatda
kichik (120 GB SSD) va u to'lganda Windows'ning o'zi ishlamay
qoladi — skrinshot esa kuniga gigabaytlar yig'adi. Shuning uchun
ildiz ish boshida bir marta tanlanadi: eng ko'p bo'sh joyi bor
yozish mumkin bo'lgan disk.

KATALOG:

    <ildiz>/<test turi>/<test>/<sana>/<sessiya>_<jshshir>_<mac>/
        shot_00001.jpg      skrinshot (serverga ham ketadi)
        clip_00001.mp4      kamera klipi (FAQAT shu yerda)
        screen.mp4          ekran yozuvi (FAQAT shu yerda)

HAR SESSIYAGA ALOHIDA PAPKA. Ilgari barcha fayllar sana
papkasida yonma-yon yotardi va nom bilan ajratilardi. Bitta
mashinada kuniga o'nlab talabgor bo'ladi, ya'ni papkada minglab
fayl to'planardi: uni ochish sekin, kerakli sessiyani topish esa
qo'lda saralash edi. Endi bitta imtihonning HAMMA dalili bitta
papkada — komissiyaga uni butunlay berish kifoya.

Papka nomida uchala belgi ham qoladi (sessiya — qaysi urinish,
JSHSHIR — kim, MAC — qaysi mashina): papka ko'chirilganda ham bu
ma'lumot yo'qolmaydi, chunki u nomning ichida.

DISK ENG BO'SHI, LEKIN FAQAT QAT'IY DISK. Olinadigan (USB, tashqi)
va tarmoq disklari CHETLAB O'TILADI: ularda odatda eng ko'p bo'sh
joy bo'ladi va talabgorlar ekranining nusxasi mashinadan chiqib
ketardi. Tarmoq diski esa `disk_usage` da osilib qolishi mumkin.

MUDDAT: `LOCAL_ARCHIVE_RETENTION_DAYS` (standart 30 kun). Tozalash
dastur ishga tushganda bir marta bajariladi — imtihon davomida
diskka tegmaslik kerak. Muddatsiz arxiv diskni to'ldirardi: bitta
ekran yozuvi ~360 MB, kuniga 2-3 imtihon.

YOZISH HECH QACHON OQIMNI TO'XTATMAYDI. Har bir xato yutiladi va
faqat jurnalga tushadi: arxiv qulaylik, kuzatuvning sharti emas —
disk to'lgani uchun imtihonni to'xtatish eng noto'g'ri xulq
bo'lardi.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import string
import sys
import threading
from datetime import date, datetime, timedelta
from typing import Optional

from config import (
    LOCAL_ARCHIVE_ENABLED,
    LOCAL_ARCHIVE_RETENTION_DAYS,
    LOCAL_ARCHIVE_ROOT,
)

log = logging.getLogger(__name__)

#: Arxiv katalogining nomi (tanlangan diskning ildizida).
ARCHIVE_DIR = "ProctoringArchive"

#: Diskda shundan kam joy qolsa, u tanlanmaydi (bayt).
#:
#: 2 GB — imtihon davomidagi bitta sessiyaning skrinshotlari uchun
#: yetarli zaxira. Undan kam joyi bor diskka yozish "birinchi
#: soatda to'ldi" degan holatni yaratardi.
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024

#: Windows fayl nomida taqiqlangan belgilar.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')

_lock = threading.Lock()
_root: Optional[str] = None


# --------------------------------------------------------------------------
def _candidate_roots() -> list:
    """
    Yozish mumkin bo'lgan disk ildizlari.

    FAQAT QAT'IY (ichki) DISKLAR. `GetDriveTypeW` bilan filtrlanadi
    va bu xavfsizlik qarori, tezlik emas: olinadigan diskda
    (fleshka, tashqi disk) odatda eng ko'p bo'sh joy bo'ladi, ya'ni
    avtomatik tanlov aynan o'shani tanlardi — va talabgorlar
    ekranining nusxasi mashinadan chiqib ketardi. Tarmoq diski esa
    ikkinchi muammo: `disk_usage` unda sekundlab osilib qolishi
    mumkin va skrinshot oqimi shu vaqtga tutilib turardi.

    Harflar bo'yicha aylanib chiqiladi, psutil bilan emas: uning
    bitta chaqiruvi CD va tarmoq qurilmalarini ham ochadi.
    """
    if sys.platform != "win32":
        return ["/"]
    roots = []
    for letter in string.ascii_uppercase:
        path = "{}:\\".format(letter)
        if os.path.isdir(path) and _is_fixed_drive(path):
            roots.append(path)
    return roots


#: `GetDriveTypeW` natijasi: ichki (qat'iy) disk.
_DRIVE_FIXED = 3


def _is_fixed_drive(path: str) -> bool:
    """
    Disk ICHKI (qat'iy) diskmi.

    Aniqlab bo'lmasa `False` — ya'ni shubhali disk ishlatilmaydi.
    Teskarisi xavfliroq: noma'lum qurilma fleshka bo'lib chiqsa,
    dalil o'sha yerga yozilardi.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetDriveTypeW.restype = ctypes.c_uint
        return kernel32.GetDriveTypeW(path) == _DRIVE_FIXED
    except Exception:
        log.debug("Disk turini aniqlab bo'lmadi: %s", path, exc_info=True)
        return False


def _free_bytes(path: str) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def pick_root(*, force: bool = False) -> Optional[str]:
    """
    Arxiv ildizini tanlaydi (eng bo'sh disk) va uni YARATADI.

    Natija ESLAB QOLINADI: disk ish o'rtasida almashsa, bitta
    sessiyaning fayllari ikki joyga bo'linib ketardi va ularni
    yig'ish qo'lda ish bo'lardi. `force=True` — qayta tanlash
    (diagnostika uchun).
    """
    global _root
    with _lock:
        if _root is not None and not force:
            return _root

        # OCHIQ KO'RSATILGAN YO'L USTUN. Administrator diskni o'zi
        # tanlagan bo'lsa, avtomatik tanlov unga aralashmasligi
        # kerak - aks holda yangi disk ulangan kuni fayllar boshqa
        # joyga ketardi va eski papkani hech kim izlamasdi.
        if LOCAL_ARCHIVE_ROOT:
            try:
                os.makedirs(LOCAL_ARCHIVE_ROOT, exist_ok=True)
                _root = LOCAL_ARCHIVE_ROOT
                log.info("Arxiv ildizi (sozlamadan): %s", _root)
                return _root
            except OSError as exc:
                log.warning(
                    "Sozlamadagi arxiv ildizini yaratib bo'lmadi (%s): %s - "
                    "avtomatik tanlovga o'tildi", LOCAL_ARCHIVE_ROOT, exc,
                )

        best = None
        best_free = 0
        for root in _candidate_roots():
            free = _free_bytes(root)
            if free > best_free:
                best, best_free = root, free

        if best is None or best_free < MIN_FREE_BYTES:
            log.warning(
                "Arxiv uchun mos disk topilmadi (eng bo'shi %s, %.1f GB)",
                best, best_free / (1024 ** 3),
            )
            _root = ""
            return None

        target = os.path.join(best, ARCHIVE_DIR)
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as exc:
            log.warning("Arxiv katalogini yaratib bo'lmadi (%s): %s", target, exc)
            _root = ""
            return None

        log.info("Arxiv diski: %s (%.1f GB bo'sh)", target, best_free / (1024 ** 3))
        _root = target
        return _root


def safe(value: str, *, limit: int = 60) -> str:
    """
    Fayl/katalog nomi uchun xavfsiz satr.

    Bo'sh natija "-" ga aylanadi: nomsiz katalog `os.makedirs` da
    ildizga yozib yuborardi.
    """
    text = _UNSAFE.sub(" ", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    # Nuqta bilan tugagan nom Windows'da ochilmaydi.
    text = text.rstrip(". ")
    return (text[:limit] or "-")


def session_folder(
    *,
    exam_type: str,
    exam: str,
    session_id: str,
    pinfl: str,
    mac: str,
    when: Optional[date] = None,
) -> Optional[str]:
    """
    Sessiyaning papkasi (yaratib beradi). `None` - arxiv ishlamaydi.

    BITTA IMTIHONNING HAMMA DALILI BITTA PAPKADA: skrinshotlar,
    kamera kliplari va ekran yozuvi. Komissiyaga papkani butunlay
    berish kifoya va hech nimani tanlab o'tirish kerak emas.
    """
    if not LOCAL_ARCHIVE_ENABLED:
        return None
    root = pick_root()
    if not root:
        return None

    # MAC nuqta-vergullari CHIZIQQA aylanadi: Windows fayl nomida
    # ":" taqiqlangan va uni bo'sh joyga almashtirish manzilni
    # o'qib bo'lmaydigan qilardi ("AA BB CC ..."). Chiziqli shakl
    # (AA-BB-CC-DD-EE-FF) Windows'ning o'zida ham standart.
    mac = str(mac or "").replace(":", "-")
    day = (when or date.today()).isoformat()
    stem = "_".join(
        part for part in (
            safe(session_id, limit=40), safe(pinfl, limit=20), safe(mac, limit=20)
        )
        if part and part != "-"
    ) or "sessiya"

    folder = os.path.join(root, safe(exam_type), safe(exam), day, stem)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        log.warning("Arxiv papkasini yaratib bo'lmadi (%s): %s", folder, exc)
        return None
    return folder


def save(
    data: bytes,
    *,
    exam_type: str,
    exam: str,
    session_id: str,
    pinfl: str,
    mac: str,
    extension: str = "jpg",
    prefix: str = "shot",
    when: Optional[date] = None,
) -> Optional[str]:
    """
    Faylni sessiya papkasiga yozadi. Qaytadi: to'liq yo'l (yoki `None`).

    ISTISNO TASHLAMAYDI (modul izohi): chaqiruvchi natijani
    tekshirishi shart emas.
    """
    if not data or not LOCAL_ARCHIVE_ENABLED:
        return None

    folder = session_folder(
        exam_type=exam_type, exam=exam, session_id=session_id,
        pinfl=pinfl, mac=mac, when=when,
    )
    if not folder:
        return None

    try:
        # Tartib raqami FAYL TIZIMIDAN emas, hisoblagichdan: katalogni
        # har kadrda o'qish 10 soniyada bir marta minglab yozuvni
        # sanashga aylanardi.
        index = _next_index(folder, prefix)
        path = os.path.join(folder, "{}_{:05d}.{}".format(prefix, index, extension))
        with open(path, "wb") as handle:
            handle.write(data)
        return path
    except OSError as exc:
        log.warning("Arxivga yozib bo'lmadi (%s): %s", folder, exc)
        return None


# ---------------------------------------------------------------------
# Savol kadri: nom savoldan, qayta belgilashda ALMASHADI
# ---------------------------------------------------------------------
#: `q003_id<savol-id>_14-05-33.jpg` (`q_n` bo'lmasa `id<...>_...`). Vaqt
#: qismi OXIRDA va qat'iy shaklda - savol ID'si `_` saqlasa ham nom
#: bir ma'noli ajraladi (regex oxiridan bog'langan).
_QUESTION_FILE_RE = re.compile(
    r"^(?:q\d+_)?id(?P<qid>.+)_\d{2}-\d{2}-\d{2}(?:-\d+)?\.jpg$"
)


def question_file_name(question_id: str, question_number: Optional[int], moment: datetime,
                       attempt: int = 0) -> str:
    """Savol kadrining fayl nomi. Raqam 3 xonali: papkada tartib bilan turadi."""
    number = "q{:03d}_".format(question_number) if question_number else ""
    suffix = "-{}".format(attempt) if attempt else ""
    return "{}id{}_{:%H-%M-%S}{}.jpg".format(number, question_id, moment, suffix)


def save_question_shot(
    data: bytes,
    *,
    question_id: str,
    question_number: Optional[int],
    captured_at: datetime,
    exam_type: str,
    exam: str,
    session_id: str,
    pinfl: str,
    mac: str,
) -> Optional[str]:
    """
    Savol kadrini yozadi; shu savolning OLDINGI kadri o'chiriladi.

    Talabgor savolga qaytib javobni o'zgartirsa papkada BITTA fayl qoladi
    - oxirgi holat, nomida yangi vaqt bilan. Tartib: avval yangi fayl
    (vaqtinchalik nom -> `os.replace`, ya'ni yarim yozilgan fayl hech
    qachon ko'rinmaydi), keyin eskisi - yozish yiqilsa eski dalil joyida
    qoladi. Eski fayl band bo'lsa (ko'ruvchida ochiq) u keyingi saqlashda
    qayta o'chiriladi: har saqlash papkani shu savol bo'yicha to'liq
    tozalaydi.

    ISTISNO TASHLAMAYDI (modul izohi). `captured_at` - buyruq lahzasi
    (UTC); nomga MAHALLIY vaqt yoziladi - komissiya soatni shunday o'qiydi.
    """
    if not data or not LOCAL_ARCHIVE_ENABLED or not question_id:
        return None
    folder = session_folder(
        exam_type=exam_type, exam=exam, session_id=session_id, pinfl=pinfl, mac=mac,
        when=captured_at.astimezone().date() if captured_at.tzinfo else None,
    )
    if not folder:
        return None

    local = captured_at.astimezone() if captured_at.tzinfo else captured_at
    path = None
    for attempt in range(5):
        name = question_file_name(question_id, question_number, local, attempt)
        candidate = os.path.join(folder, name)
        temp = candidate + ".tmp"
        try:
            with open(temp, "wb") as handle:
                handle.write(data)
            os.replace(temp, candidate)
            path = candidate
            break
        except OSError as exc:
            # Bir soniyada qayta belgilash va eski fayl band - keyingi nom.
            log.debug("Savol kadri yozilmadi (%s): %s", candidate, exc)
            try:
                os.remove(temp)
            except OSError:
                pass
    if path is None:
        log.warning("Savol kadrini arxivga yozib bo'lmadi: %s (id=%s)", folder, question_id)
        return None

    keep = os.path.basename(path)
    try:
        names = os.listdir(folder)
    except OSError:
        names = []
    for name in names:
        match = _QUESTION_FILE_RE.match(name)
        if name == keep or match is None or match.group("qid") != question_id:
            continue
        try:
            os.remove(os.path.join(folder, name))
        except OSError as exc:
            log.debug("Eski savol kadri o'chirilmadi (%s): %s", name, exc)
    return path


def purge_old(days: int = 0) -> int:
    """
    Muddati o'tgan SANA papkalarini o'chiradi. Qaytadi: o'chirilgani.

    ISHGA TUSHISHDA bir marta chaqiriladi va bu ataylab: imtihon
    davomida diskni kezish skrinshot oqimi bilan bitta diskda
    raqobatlashardi, ekran yozuvi esa unga uzluksiz yozib turadi.

    SANA PAPKASI bo'yicha o'chiriladi, fayl vaqti bo'yicha emas:
    `os.stat` ni har faylda chaqirish o'n minglab chaqiruv degani,
    papka nomidagi sana esa allaqachon tayyor javob. Nomi sanaga
    o'xshamagan papkaga TEGILMAYDI - u administrator qo'lda qo'ygan
    narsa bo'lishi mumkin.
    """
    days = int(days or LOCAL_ARCHIVE_RETENTION_DAYS)
    if days <= 0 or not LOCAL_ARCHIVE_ENABLED:
        return 0
    root = pick_root()
    if not root:
        return 0

    edge = date.today() - timedelta(days=days)
    removed = 0
    # Ildiz -> test turi -> test -> SANA. `os.walk` butun arxivni
    # (o'n minglab fayl) kezardi, bu yerda esa uch qavat katalog
    # nomi yetarli.
    for type_dir in _subdirs(root):
        for exam_dir in _subdirs(type_dir):
            for day_dir in _subdirs(exam_dir):
                try:
                    when = date.fromisoformat(os.path.basename(day_dir))
                except ValueError:
                    continue
                if when >= edge:
                    continue
                try:
                    shutil.rmtree(day_dir)
                    removed += 1
                except OSError as exc:
                    log.warning(
                        "Eski arxivni o'chirib bo'lmadi (%s): %s", day_dir, exc
                    )
    if removed:
        log.info(
            "Arxivdan %s ta eski kun o'chirildi (muddat %s kun)", removed, days
        )
    return removed


def _subdirs(path: str) -> list:
    try:
        return [
            os.path.join(path, name)
            for name in os.listdir(path)
            if os.path.isdir(os.path.join(path, name))
        ]
    except OSError:
        return []


#: `(papka, nom)` -> oxirgi tartib raqami.
_counters: dict = {}


def _next_index(folder: str, stem: str) -> int:
    """
    Keyingi tartib raqami.

    Birinchi chaqiruvda katalogdagi mavjud fayllar SANALADI — dastur
    qayta ishga tushganda (masalan quvvat uzilgandan keyin) hisob
    noldan boshlansa, eski fayllar ustiga yozilardi.
    """
    key = (folder, stem)
    with _lock:
        if key not in _counters:
            try:
                existing = [
                    name for name in os.listdir(folder) if name.startswith(stem + "_")
                ]
            except OSError:
                existing = []
            _counters[key] = len(existing)
        _counters[key] += 1
        return _counters[key]


def reset() -> None:
    """Holatni tozalaydi (testlar va disk almashgan holat uchun)."""
    global _root
    with _lock:
        _root = None
        _counters.clear()


# --------------------------------------------------------------------------
# Sessiya konteksti
# --------------------------------------------------------------------------
#: Joriy sessiya konteksti (`set_context` bilan qo'yiladi).
#:
#: NIMA UCHUN MODUL DARAJASIDA. Kadrni yozadigan ikkita joy bor va
#: ular butunlay boshqa qatlamlarda: skrinshot oqimi
#: (`services/screen_capture.py`) va dalil yuklovchi
#: (`services/proctoring_supervisor.py`). Kontekstni ikkalasiga
#: parametr sifatida uzatish uch-to'rt qatlamdan o'tgan argument
#: zanjiri degani bo'lardi - va u birinchi refaktoringda uzilardi.
_context: dict = {}


def set_context(
    *, exam_type: str = "", exam: str = "", session_id: str = "", pinfl: str = "",
    mac: str = "",
) -> None:
    """Sessiya boshida bir marta chaqiriladi."""
    global _context
    _context = {
        "exam_type": exam_type or "Belgilanmagan",
        "exam": exam or "Test",
        "session_id": session_id,
        "pinfl": pinfl,
        "mac": mac,
    }


def clear_context() -> None:
    """Sessiya tugagach: keyingi talabgorning fayllari aralashmasin."""
    global _context
    _context = {}


def context() -> dict:
    """
    Joriy sessiya kontekstining NUSXASI.

    Fon thread'ida yoziladigan fayl uchun kontekst BUYRUQ paytida
    olinadi (`screen_capture`): kodlash tugaguncha sessiya yopilib,
    `_context` tozalanib ulgurishi mumkin - oxirgi javobning kadri
    aynan shunda yo'qolardi.
    """
    return dict(_context)


def save_frame(
    data: bytes, *, extension: str = "jpg", prefix: str = "shot"
) -> Optional[str]:
    """
    Joriy sessiya konteksti bilan yozadi.

    Kontekst yo'q bo'lsa YOZILMAYDI: sessiyasiz fayl nomida na
    JSHSHIR, na sessiya raqami bo'ladi va u arxivda "kimningdir
    kadri" bo'lib qolardi.
    """
    if not _context:
        return None
    return save(data, extension=extension, prefix=prefix, **_context)


def current_folder() -> Optional[str]:
    """
    Joriy sessiyaning papkasi - ekran yozuvi TO'G'RIDAN-TO'G'RI shu
    yerga yoziladi.

    Klip va skrinshotdan farqi: ular tayyor baytlar ko'rinishida
    keladi, ekran yozuvi esa soatlab davom etadi va uni RAM'da
    ushlab bo'lmaydi - `cv2.VideoWriter` faylga oqim bilan yozadi.
    """
    if not _context:
        return None
    return session_folder(**_context)
