"""
PyInstaller bundle uchun xavfsiz fayl yo'llari.

Frozen (.exe) rejimda asset'lar boshqa katalogda yotadi:
  --onedir  : sys._MEIPASS = <exe>/_internal/
  --onefile : sys._MEIPASS = %TEMP%/_MEIxxxx/  (har ishga tushishda yangi)

Shuning uchun O'QISH (`resource_root`) va YOZISH (`writable_root`)
kataloglari ATAYLAB ajratilgan: onefile rejimda resource katalogi
vaqtinchalik va unga yozilgan narsa dastur yopilishi bilan yo'qoladi.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "ProctoringClient"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Read-only asset'lar (InsightFace modellari, ikonkalar) ildizi."""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        return Path(meipass) if meipass else Path(sys.executable).parent
    # Dev rejim: core/ ning ota katalogi = client ildizi
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str | Path = "") -> Path:
    return resource_root() / relative


def writable_root() -> Path:
    """
    Log, kesh va qurilma identifikatori saqlanadigan katalog.

    %APPDATA%/ProctoringClient — frozen va dev rejimda BIR XIL. Bu muhim:
    dev rejimda yaratilgan `device_id` .exe ga o'tganda ham topiladi,
    ya'ni qurilma qayta ro'yxatdan o'tishi shart emas.

    O'rnatuvchi bu katalogni uninstall'da O'CHIRMAYDI
    (`installer/proctoring_client.iss`): `device_id` serverdagi qurilma
    yozuvining kaliti va u yo'qolsa, qayta o'rnatilgan mashina
    administrator tasdig'ini qaytadan kutib qoladi.
    """
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    root = Path(base) / APP_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


# --------------------------------------------------------------------------
# `.env` — sozlama fayli qayerda
# --------------------------------------------------------------------------
#: Ochiq ko'rsatilgan `.env` yo'li (muhit o'zgaruvchisi). Bir mashinada
#: ikki xil sozlama bilan sinash yoki nostandart o'rnatish uchun.
ENV_FILE_VAR = "PROCTORING_ENV_FILE"


def machine_config_root() -> Path:
    """
    Mashina darajasidagi sozlama katalogi: `%ProgramData%\\ProctoringClient`.

    NIMA UCHUN ProgramData, `.exe` yoni EMAS. O'rnatuvchi dasturni
    `Program Files` ga qo'yadi va u yerga oddiy foydalanuvchi ham,
    dasturning o'zi ham yoza olmaydi - administrator server manzilini
    o'zgartirmoqchi bo'lsa, faylni `Program Files` ichida tahrirlash
    UAC bilan kurash bo'lardi, yangilash esa uni ustidan yozib
    yuborishi mumkin edi. ProgramData esa:

      * mashinaning BARCHA hisoblari uchun bitta (imtihon mashinasida
        operator va talabgor boshqa-boshqa Windows hisobi bo'lishi
        mumkin - `%APPDATA%` esa har hisobniki alohida);
      * dastur katalogidan MUSTAQIL - yangilash va qayta o'rnatish
        unga tegmaydi;
      * administrator yaratgan faylni oddiy foydalanuvchi faqat
        O'QIY OLADI (standart ACL) - talabgor `KIOSK_MODE=false`
        yozib qo'ya olmaydi.

    Katalog YARATILMAYDI (`writable_root` dan farqli): bu o'qish uchun
    manba, uni o'rnatuvchi yaratadi.
    """
    base = os.environ.get("ProgramData") or os.environ.get("ALLUSERSPROFILE")
    if not base:
        # Muhit buzilgan holat (xizmat yoki qisqartirilgan muhit bilan
        # ishga tushirish). Windows'da standart joy o'zgarmaydi.
        base = r"C:\ProgramData"
    return Path(base) / APP_DIR_NAME


def env_file_candidates() -> list[Path]:
    """
    `.env` qidiriladigan joylar — USTUNLIK TARTIBIDA.

      1. `PROCTORING_ENV_FILE` — ochiq ko'rsatilgan yo'l har doim ustun;
      2. frozen: `%ProgramData%\\ProctoringClient\\.env` — o'rnatuvchi
         yozadigan asosiy joy;
      3. frozen: `.exe` yonidagi `.env` — o'rnatuvchisiz ("portable")
         nusxa va eski o'rnatishlar uchun (ilgari `config` faqat
         shu yerga qarardi);
      4. dev: `client/.env`.

    Dev rejimda ProgramData QARALMAYDI: shu mashinada o'rnatilgan
    client'ning sozlamasi dasturchining `client/.env` ini jimgina
    soyalab qo'yardi va "nega server manzili boshqa?" degan savolga
    javob topish qiyin bo'lardi.

    Frozen rejimda dev yo'li ham QARALMAYDI: u `_internal/.env` bo'lardi,
    ya'ni build'ga tasodifan tushib qolgan dasturchi fayli.
    """
    candidates: list[Path] = []

    explicit = (os.environ.get(ENV_FILE_VAR) or "").strip()
    if explicit:
        candidates.append(Path(os.path.expandvars(explicit)).expanduser())

    if is_frozen():
        candidates.append(machine_config_root() / ".env")
        candidates.append(Path(sys.executable).resolve().parent / ".env")
    else:
        candidates.append(resource_root() / ".env")

    return candidates


def env_file_path() -> Path | None:
    """
    Birinchi MAVJUD `.env` — yoki `None`.

    `None` xato emas: sozlamalar muhit o'zgaruvchilaridan ham kelishi
    mumkin, qolganlari esa `config` dagi standart qiymatlarni oladi.
    Lekin frozen rejimda bu deyarli har doim o'rnatish nosozligi
    (server manzili yo'q) - chaqiruvchi buni log'ga yozishi kerak.

    DIQQAT: `PROCTORING_ENV_FILE` berilgan, lekin fayl YO'Q bo'lsa,
    keyingi nomzodga o'tiladi. Chaqiruvchi `env_file_candidates()[0]`
    ni solishtirib, bu holatni ogohlantirish sifatida yozishi mumkin.
    """
    for candidate in env_file_candidates():
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            # Tarmoq yo'li yoki ruxsat yo'q - keyingi nomzodga o'tamiz,
            # ishga tushishni to'xtatmaymiz.
            continue
    return None
