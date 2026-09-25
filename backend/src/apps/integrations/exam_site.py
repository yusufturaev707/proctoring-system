"""
Imtihonning O'Z test platformasi bilan integratsiya (`Exam.site_url`).

BACKEND — KO'PRIK. Client tashqi platformaga hech qachon o'zi
murojaat qilmaydi: u faqat bizning API'mizni biladi, biz esa
platformaga boramiz va javobni tushunarli shaklga keltirib
qaytaramiz. Sababi ikkita va ikkalasi ham qat'iy:

  * kredensial (`Exam.site_header_encrypted`) serverda qoladi.
    Uni client'ga berish har bir imtihon mashinasiga platforma
    API'sining kalitini tarqatish demak edi — 500 mashinaga
    tarqalgan token bekor qilinmaydi ham, kuzatilmaydi ham;
  * platformaning javob sxemasi BITTA joyda talqin qilinadi.
    Client'da talqin qilinsa, sxema o'zgarganda barcha
    mashinalarni yangilash kerak bo'lardi.

NIMA UCHUN `exam_platform.py` DAN ALOHIDA. U markazlashgan ntest
API'si bilan ishlaydi: bitta `BASE_URL`, bitta global API kalit,
POST va boshqa javob sxemasi. Bu yerdagi chaqiruv esa HAR IMTIHON
uchun boshqa manzil va boshqa sarlavha bilan ketadi. Ikkalasini
bitta `requests.Session` da birlashtirish xavfli bo'lardi: u
yerdagi global `Authorization` sarlavhasi bu yerdagi begona
platformaga ham yuborilib, ntest kalitini oshkor qilardi.

HIMOYA QATLAMLARI `exam_platform.py` dagi bilan bir xil sababdan:
qat'iy timeout, jitter bilan cheklangan retry va circuit breaker.
Bu chaqiruv KRITIK YO'LDA — operator ekran oldida uni kutib
turadi, ya'ni "javob kelmadi" holati "cheksiz kutish" ga
aylanmasligi kerak.

Circuit breaker HAR HOST uchun alohida: bitta imtihon platformasi
yiqilgani boshqasiga tegishli emas.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter

from apps.common.circuit_breaker import CircuitBreaker, CircuitOpenError
from apps.common.exceptions import (
    CandidateNotEligible,
    CandidateNotFound,
    ExternalPlatformError,
    ExternalPlatformUnavailable,
)

logger = logging.getLogger(__name__)

#: JSHSHIR shu nom bilan uzatiladi: `?imie=30309975270036`.
#:
#: Nom javobdagi maydon bilan bir xil (`data.imie`). Sozlama qilib
#: qo'yilgan, chunki bu ikki tizim orasidagi SHARTNOMA va uni
#: o'zgartirish uchun kodga tegish kerak bo'lmasligi kerak.
PINFL_PARAM = "imie"

#: Javob konverti: `status` maydonining "topildi" qiymati.
_FOUND = 1

_session_lock = threading.Lock()
_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """
    Pool bilan yagona sessiya — LEKIN global sarlavhalarsiz.

    `exam_platform.py` dagi sessiyadan farqi shu: u yerda global
    `Authorization` o'rnatiladi va u har bir so'rovga qo'shiladi.
    Bu yerda sarlavha HAR SO'ROVDA alohida beriladi, chunki u
    imtihonga tegishli.
    """
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                pool = settings.EXTERNAL_PLATFORM["POOL_SIZE"]
                sess = requests.Session()
                adapter = HTTPAdapter(
                    pool_connections=pool,
                    pool_maxsize=pool,
                    # Retry O'ZIMIZDA (jitter kerak).
                    max_retries=0,
                )
                sess.mount("https://", adapter)
                sess.mount("http://", adapter)
                sess.headers.update(
                    {
                        "User-Agent": "ProctoringSystem/1.0",
                        "Accept": "application/json",
                    }
                )
                _session = sess
    return _session


def _breaker(host: str) -> CircuitBreaker:
    conf = settings.EXTERNAL_PLATFORM
    return CircuitBreaker(
        name=f"exam_site:{host}",
        fail_threshold=conf["CB_FAIL_THRESHOLD"],
        window=conf["CB_WINDOW"],
        reset_timeout=conf["CB_RESET_TIMEOUT"],
    )


def build_url(site_url: str, pinfl: str) -> str:
    """
    So'rov manzili: `site_url` + `?imie=<jshshir>`.

    Mavjud query parametrlar SAQLANADI — manzilda allaqachon
    kalit yoki versiya bo'lishi mumkin
    (`.../check?v=2` -> `.../check?v=2&imie=...`).
    """
    parts = urlparse(site_url)
    query = [(key, value) for key, value in parse_qsl(parts.query) if key != PINFL_PARAM]
    query.append((PINFL_PARAM, pinfl))
    return urlunparse(parts._replace(query=urlencode(query)))


def parse_header(raw_header: str) -> dict:
    """
    `"Authorization: Bearer xxx"` -> `{"Authorization": "Bearer xxx"}`.

    Bo'sh yoki formatga mos kelmagan qiymat BO'SH lug'at qaytaradi:
    sarlavhasiz so'rov yuborish platformadan 401 oladi va sabab
    javobda ko'rinadi. Bu yerda istisno tashlash esa "sozlanmagan"
    holatni "buzilgan" holatdan ajratmasdi.
    """
    raw = (raw_header or "").strip()
    if not raw:
        return {}
    name, separator, value = raw.partition(":")
    if not separator or not name.strip() or not value.strip():
        logger.warning("Imtihon sarlavhasi formatga mos emas — so'rov usiz ketadi")
        return {}
    return {name.strip(): value.strip()}


def check_candidate(*, site_url: str, site_header: str, pinfl: str) -> dict:
    """
    Talabgorni imtihon platformasida tekshiradi.

    Javob konverti (muvaffaqiyat):

        {"status": 1, "message": "Success",
         "data": {"id":…, "abitur_id":…, "imie":…, "is_finished":…,
                  "image_base64":…, "lname":…, "fname":…, "mname":…,
                  "duration_time": 180, "test_link":…, "message":…,
                  "status": true}}

    Topilmasa: `{"status": 0, "message": "Not found"}`.

    IKKI XIL "YO'Q" BOR va ular ajratiladi:

        status != 1        — talabgor umuman topilmadi;
        data.status false  — topildi, lekin testga ruxsat yo'q.

    Birinchisida JSHSHIR xato kiritilgan bo'lishi mumkin, ikkinchisida
    esa raqam to'g'ri va sabab platformada (`data.message`) — operator
    uchun bular butunlay boshqa harakatlar.

    KESH YO'Q. Javobda `test_link` bor va u tirik kredensial: eski
    havolani qaytarish talabgorni allaqachon yopilgan sessiyaga
    yuborardi. Takroriy bosishdan client tomondagi tugma blokirovkasi
    va throttling himoya qiladi.
    """
    if settings.EXTERNAL_PLATFORM["MOCK"]:
        return _mock(pinfl)

    if not site_url:
        raise ExternalPlatformError(
            "Imtihonda test platformasining manzili ko'rsatilmagan"
        )

    url = build_url(site_url, pinfl)
    host = urlparse(url).hostname or "noma'lum"
    breaker = _breaker(host)
    try:
        payload = breaker.call(_request, url, parse_header(site_header))
    except CircuitOpenError:
        logger.warning("Imtihon platformasi circuit ochiq: %s", host)
        raise ExternalPlatformUnavailable()
    return _normalize(payload)


def _request(url: str, headers: dict) -> dict:
    conf = settings.EXTERNAL_PLATFORM
    timeout = (conf["CONNECT_TIMEOUT"], conf["READ_TIMEOUT"])
    last_error: Exception | None = None

    for attempt in range(conf["MAX_RETRIES"] + 1):
        try:
            response = _get_session().get(url, headers=headers, timeout=timeout)
        except requests.Timeout as exc:
            last_error = exc
            logger.warning("Imtihon platformasi timeout (%s-urinish)", attempt + 1)
        except requests.RequestException as exc:
            last_error = exc
            logger.warning("Imtihon platformasi tarmoq xatosi: %s", exc)
        else:
            if response.status_code in (401, 403):
                # Sarlavha xato yoki muddati o'tgan. Bu KONFIGURATSIYA
                # xatosi va uni qayta urinish tuzatmaydi.
                logger.error(
                    "Imtihon platformasi avtorizatsiyani rad etdi (%s): %s",
                    response.status_code, url.split("?")[0],
                )
                raise ExternalPlatformError(
                    "Test platformasi avtorizatsiyani rad etdi — imtihon "
                    "sozlamasidagi sarlavhani tekshiring"
                )
            if 400 <= response.status_code < 500:
                raise ExternalPlatformError(
                    "Test platformasi so'rovni rad etdi ({})".format(response.status_code)
                )
            if response.status_code >= 500:
                last_error = ExternalPlatformError(
                    "Test platformasi {}".format(response.status_code)
                )
                logger.warning("Imtihon platformasi 5xx: %s", response.status_code)
            else:
                try:
                    return response.json()
                except ValueError as exc:
                    raise ExternalPlatformError(
                        "Test platformasi JSON bo'lmagan javob qaytardi"
                    ) from exc

        if attempt < conf["MAX_RETRIES"]:
            # Jitter'siz barcha worker'lar bir vaqtda qayta uradi va
            # tiklanayotgan platformani yana yiqitadi.
            time.sleep((0.2 * (2**attempt)) + random.uniform(0, 0.2))

    raise ExternalPlatformError(
        str(last_error) if last_error else "Test platformasi javob bermadi"
    )


def _normalize(raw: dict) -> dict:
    """Platforma javobini ichki shaklga keltiradi."""
    envelope = raw if isinstance(raw, dict) else {}
    if _as_int(envelope.get("status")) != _FOUND:
        # Platformaning o'z matni ko'rsatiladi: u "Not found" dan
        # ko'ra aniqroq bo'lishi mumkin ("Imtihon kuni emas").
        raise CandidateNotFound(
            _clean(envelope.get("message")) or "Talabgor test platformasida topilmadi"
        )

    data = envelope.get("data")
    if not isinstance(data, dict):
        raise ExternalPlatformError("Test platformasi bo'sh javob qaytardi")

    message = _clean(data.get("message")) or _clean(envelope.get("message"))
    if not _as_bool(data.get("status")):
        raise CandidateNotEligible(message or "Bu testga ruxsat berilmagan")

    test_link = _clean(data.get("test_link"))
    if not test_link:
        # Ruxsat bor, lekin havola yo'q — WebView'ni ochib bo'lmaydi.
        # Buni FaceID'dan KEYIN emas, hozir aytish kerak: aks holda
        # talabgor butun tekshiruvdan o'tib, oxirida to'xtardi.
        logger.error("Platforma ruxsat berdi, lekin `test_link` bermadi")
        raise CandidateNotEligible(
            "Test platformasi test havolasini bermadi — administratorga murojaat qiling"
        )

    names = _names(data)
    return {
        "eligible": True,
        "external_id": _clean(data.get("id")),
        "abitur_id": _clean(data.get("abitur_id")),
        "pinfl": _clean(data.get("imie")),
        **names,
        # `is_finished` MA'LUMOT uchun, to'siq emas: platformaning o'z
        # namunasida u `1` bo'lgani holda `status: true` va "Testga
        # ruxsat!" qaytadi. Ya'ni ruxsat qarori faqat `data.status` da.
        "is_finished": _as_bool(data.get("is_finished")),
        "photo_base64": strip_data_uri(_clean(data.get("image_base64"))),
        # Test davomiyligi DAQIQADA (`duration_time`). Platformadan
        # kelgan qiymat AYNAN shu birlikda va uni soatga bu yerda
        # aylantirmaymiz: ko'rsatish shakli client tomonda tanlanadi
        # ("3 soat"), saqlanadigan qiymat esa bitta va bir xil
        # birlikda bo'lishi kerak.
        "duration_minutes": _as_minutes(data.get("duration_time")),
        "test_link": test_link,
        "message": message,
    }


#: F.I.Sh. maydonlarining mumkin bo'lgan nomlari.
#:
#: Platforma ismni `lname`/`fname`/`mname` da beradi va bu ro'yxatdagi
#: BIRINCHI nom — aynan shu o'rnatish bilan ishlaymiz. Qolgan
#: variantlar saqlanadi: o'rnatishlar bir xil emas va javob sxemasi
#: ilgari umuman ismsiz edi. Kelgan ismni TASHLAB YUBORISH eng yomon
#: variant bo'lardi: operator ekranda faqat raqamlarni ko'rib,
#: talabgorni ism bo'yicha tekshira olmasdi.
#:
#: Tartib MUHIM: birinchi bo'sh bo'lmagan qiymat olinadi.
_NAME_ALIASES = {
    "full_name": ("fio", "full_name", "fullname", "name"),
    "last_name": ("lname", "last_name", "surname", "familiya"),
    "first_name": ("fname", "first_name", "firstname", "ism"),
    "middle_name": ("mname", "middle_name", "patronymic", "otasining_ismi"),
}


def _names(data: dict) -> dict:
    """
    F.I.Sh. — kelsa oladi, kelmasa bo'sh qoldiradi.

    To'liq ism ikki yo'ldan kelishi mumkin: bitta maydon (`fio`)
    yoki uch bo'lak. Ikkalasi ham qo'llab-quvvatlanadi va bitta
    maydon bo'lsa u bo'laklarga AJRATILMAYDI — "Aliyev Vali Sobir
    o'g'li" ni to'g'ri bo'lish uchun qoida kerak, u esa har tilda
    boshqacha va xato bo'lgani ekranda darhol ko'rinardi.
    """
    result = {key: "" for key in _NAME_ALIASES}
    for key, aliases in _NAME_ALIASES.items():
        for alias in aliases:
            value = _clean(data.get(alias))
            if value:
                result[key] = value
                break

    if not result["full_name"]:
        result["full_name"] = " ".join(
            part
            for part in (result["last_name"], result["first_name"], result["middle_name"])
            if part
        ).strip()
    return result


def _mock(pinfl: str) -> dict:
    """Dev rejimi (`BASE_API_MOCK=true`) — platformasiz to'liq oqim."""
    return {
        "eligible": True,
        "external_id": "mock-{}".format(pinfl[-5:]),
        "abitur_id": "mock-abitur-{}".format(pinfl[-5:]),
        "pinfl": pinfl,
        "full_name": "Testov Test Testovich",
        "last_name": "Testov",
        "first_name": "Test",
        "middle_name": "Testovich",
        "is_finished": False,
        # Platforma bergan qiymat bilan bir xil birlikda (daqiqa).
        "duration_minutes": 180,
        # Etalon rasm YO'Q — client bu holatda "enrollment" rejimiga
        # tushadi (solishtirmaydi, faqat yuzni qayd etadi).
        "photo_base64": "",
        "test_link": "https://example.test/login?token=mock-{}".format(pinfl[-5:]),
        "message": "Testga ruxsat! (mock)",
    }


# --------------------------------------------------------------------------
def strip_data_uri(value: str) -> str:
    """`data:image/jpeg;base64,XXXX` -> `XXXX` (client toza base64 kutadi)."""
    text = str(value or "")
    if text.startswith("data:") and "," in text:
        return text.split(",", 1)[1]
    return text


def _clean(value) -> str:
    """`None` va raqamlarni bir xil shaklga keltiradi (`imie` — son)."""
    if value is None:
        return ""
    return str(value).strip()


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _as_minutes(value) -> int:
    """
    Test davomiyligi (daqiqa). Xato qiymat — 0, ISTISNO EMAS.

    Davomiylik MA'LUMOT, to'siq emas: uni o'qib bo'lmagani uchun
    talabgorni imtihonga qo'ymaslik butun tekshiruvni ikkinchi
    darajali maydonga bog'lab qo'yardi. 0 esa client uchun "ma'lum
    emas" degani va u o'sha maydonni umuman ko'rsatmaydi.
    """
    try:
        minutes = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0
    return minutes if 0 < minutes <= 24 * 60 else 0


def _as_bool(value) -> bool:
    """`true`, `1`, `"1"` — hammasi rost. Platformalar bir xil emas."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in ("1", "true", "yes", "ha")
